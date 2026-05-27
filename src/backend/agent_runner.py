import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from loguru import logger

from src.multi_agent.multi_agent import create_my_agent


class AgentRunner:
    """封装 deep_agent 的生命周期管理，提供 chat + HITL 中断/恢复接口。"""

    def __init__(self):
        self._agent = None

    async def initialize(self):
        """初始化 deep_agent（在服务启动时调用一次）。"""
        self._agent = await create_my_agent()

    async def chat(self, message: str, session_id: str | None = None) -> str:
        """发送用户消息，返回 agent 的回复文本（非流式，兼容调用）。"""
        if self._agent is None:
            raise RuntimeError("Agent 尚未初始化，请先调用 initialize()")

        thread_id = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        result = await self._agent.ainvoke(
            input={"messages": [HumanMessage(content=message)]},
            config=config,
        )

        messages = result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "ai":
                return msg.content
            if hasattr(msg, "role") and msg.role == "assistant":
                return msg.content
        return str(result)

    async def astream_chat(
        self, message: str, session_id: str | None = None
    ) -> AsyncGenerator[str | dict, None]:
        """流式发送用户消息。

        yield: str (AI token) 或 dict (控制事件 hitl_required)
        """
        if self._agent is None:
            raise RuntimeError("Agent 尚未初始化，请先调用 initialize()")

        thread_id = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        async for item in self._stream(config, {"messages": [HumanMessage(content=message)]}, enable_hitl=True):
            yield item

    async def resume_chat(
        self, session_id: str, decision: str, message: str = ""
    ) -> AsyncGenerator[str | dict, None]:
        """恢复被 HITL 中断的对话。"""
        if self._agent is None:
            raise RuntimeError("Agent 尚未初始化")

        config = {"configurable": {"thread_id": session_id}}
        cmd = Command(resume={"decision": decision, "message": message})

        async for item in self._stream(config, cmd, enable_hitl=True):
            yield item

    # ── 内部方法 ──────────────────────────────────────────────────

    async def _stream(
        self, config: dict, input_data, enable_hitl: bool = True
    ) -> AsyncGenerator[str | dict, None]:
        """统一流式处理。

        StreamChunk = (namespace: tuple[str,...], mode: str, data: Any)
        """
        hitl_sent = False
        seen_tools: set[str] = set()

        async for chunk in self._agent.astream(
            input_data,
            stream_mode=["messages", "updates"],
            subgraphs=True,
            config=config,
        ):
            # StreamChunk 是 3 元组: (namespace, mode, data)
            if not (hasattr(chunk, "__len__") and len(chunk) >= 3):
                continue

            mode = chunk[1]
            data = chunk[2]

            if mode == "messages":
                if hasattr(data, "__len__") and len(data) >= 2:
                    token, _metadata = data[0], data[1]
                    # 检测工具调用开始，输出状态提示
                    if hasattr(token, "tool_call_chunks") and token.tool_call_chunks:
                        for tc in token.tool_call_chunks:
                            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                            if name and name not in seen_tools:
                                seen_tools.add(name)
                                yield f"\n> 🔍 正在执行: {name}\n"
                    # 流式文本内容
                    if token.content and hasattr(token, "tool_call_chunks"):
                        yield token.content

            elif mode == "updates" and not hitl_sent:
                if enable_hitl and isinstance(data, dict) and "__interrupt__" in data:
                    hitl_sent = True
                    interrupt_data = data["__interrupt__"]
                    query = ""
                    result = ""
                    if interrupt_data:
                        iv = interrupt_data[0].value
                        query = iv.get("query", "")
                        result = iv.get("result", "")
                    logger.info(f"[HITL] 发送审核事件, query={query[:80]}...")
                    yield {
                        "type": "hitl_required",
                        "session_id": config["configurable"]["thread_id"],
                        "query": query,
                        "result": result,
                    }
                    break  # 中断后退出流，不再等待更多 chunk（astream 已暂停）
