import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import HumanMessage

from src.multi_agent.multi_agent import create_my_agent


class AgentRunner:
    """封装 deep_agent 的生命周期管理，提供简洁的 chat 接口。"""

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
    ) -> AsyncGenerator[str, None]:
        """流式发送用户消息，逐 token yield 文本内容。"""
        if self._agent is None:
            raise RuntimeError("Agent 尚未初始化，请先调用 initialize()")

        thread_id = session_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        async for chunk in self._agent.astream(
            {"messages": [HumanMessage(content=message)]},
            stream_mode="messages",
            subgraphs=True,
            config=config,
        ):
            # v1 格式：chunk 是 (namespace, (token, metadata)) 元组
            if isinstance(chunk, tuple) and len(chunk) == 2:
                _namespace, (token, _metadata) = chunk
            # v2 格式：chunk 是 {"type": "messages", "data": (token, metadata), ...}
            elif isinstance(chunk, dict) and chunk.get("type") == "messages":
                token, _metadata = chunk["data"]
            else:
                continue

            # 只 yield AI 生成的纯文本 token，跳过工具调用消息
            if token.content and hasattr(token, "tool_call_chunks") and not token.tool_call_chunks:
                yield token.content
