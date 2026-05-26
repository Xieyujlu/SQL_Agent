"""FastAPI 应用入口 — 提供聊天 API 并托管前端静态文件。"""

import json
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.backend.agent_runner import AgentRunner

app = FastAPI(title="SQLAgent-ms", description="多智能体数据查询助手")

# 全局 AgentRunner 实例
agent_runner = AgentRunner()


# ── 请求模型 ─────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ── 生命周期 ─────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """服务启动时初始化 deep_agent。"""
    await agent_runner.initialize()


# ── API 路由 ─────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(req: ChatRequest):
    """接收用户消息，流式返回 agent 的回复（SSE）。"""

    async def event_stream():
        sid = req.session_id or str(uuid.uuid4())
        async for token in agent_runner.astream_chat(req.message, sid):
            if token:
                yield f"data: {json.dumps({'token': token})}\n\n"
        yield f"data: {json.dumps({'done': True, 'session_id': sid})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── 静态文件（前端） ──────────────────────────────────────────────
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
