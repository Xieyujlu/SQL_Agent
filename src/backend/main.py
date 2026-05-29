"""FastAPI 应用入口 — 提供聊天 API 并托管前端静态文件。"""

import json
import logging
import uuid
from pathlib import Path

from dotenv import load_dotenv

# 在导入任何项目模块之前加载 .env
load_dotenv(Path(__file__).resolve().parent.parent / "agent" / ".env")

from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agent.tools.memory_tools import current_user_id
from src.backend.agent_runner import AgentRunner

logger = logging.getLogger(__name__)

app = FastAPI(title="SQLAgent-ms", description="多智能体数据查询助手")

# 全局 AgentRunner 实例
agent_runner = AgentRunner()


# ── 请求模型 ─────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str = "default"


class FeedbackRequest(BaseModel):
    session_id: str
    decision: str  # "准确" / "错误" / "其他建议"
    message: str = ""


# ── 生命周期 ─────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """服务启动时初始化 deep_agent。"""
    await agent_runner.initialize()


# ── 杂项路由 ─────────────────────────────────────────────────────
@app.get("/favicon.ico")
async def favicon():
    """消除浏览器 favicon 请求的 404 日志。"""
    return Response(status_code=204)


# ── API 路由 ─────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(req: ChatRequest):
    """接收用户消息，流式返回 agent 的回复（SSE）。"""

    async def event_stream():
        sid = req.session_id or str(uuid.uuid4())
        current_user_id.set(req.user_id)
        async for item in agent_runner.astream_chat(req.message, sid, req.user_id):
            if isinstance(item, dict):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            elif item:
                yield f"data: {json.dumps({'token': item}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True, 'session_id': sid})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/chat/feedback")
async def submit_feedback(req: FeedbackRequest):
    """提交人工审核反馈，保存到 MySQL 并通过 Command(resume=...) 恢复对话。"""

    # 保存反馈到 MySQL
    try:
        from src.agent.utils.feedback_db import save_feedback
        save_feedback(
            session_id=req.session_id,
            decision=req.decision,
            message=req.message,
        )
    except Exception as e:
        logger.warning("保存反馈失败: %s", e)

    async def event_stream():
        current_user_id.set("default")
        async for item in agent_runner.resume_chat(
            req.session_id, req.decision, req.message, "default"
        ):
            if isinstance(item, dict):
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            elif item:
                yield f"data: {json.dumps({'token': item}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True, 'session_id': req.session_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── 静态文件（前端） ──────────────────────────────────────────────
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
