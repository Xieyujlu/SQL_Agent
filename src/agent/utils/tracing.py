"""Langfuse 集成模块 — trace 跟踪与 token 统计。"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from langfuse import Langfuse  # noqa: E402
from langfuse.langchain import CallbackHandler  # noqa: E402

_client: Langfuse | None = None


def get_langfuse_client() -> Langfuse:
    """获取全局单例 Langfuse 客户端。"""
    global _client
    if _client is None:
        _client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            base_url=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        )
    return _client


def get_langfuse_callback(
    user_id: str = "",
    session_id: str = "",
) -> CallbackHandler:
    """为单个请求创建独立的 CallbackHandler（保证 trace 隔离）。

    每个请求应调用此函数创建新实例，避免不同会话的 trace 相互串扰。
    """
    trace_context: dict = {}
    if user_id:
        trace_context["user_id"] = user_id
    if session_id:
        trace_context["session_id"] = session_id

    return CallbackHandler(trace_context=trace_context if trace_context else None)


def get_trace_url(trace_id: str) -> str:
    """根据 trace_id 生成 Langfuse UI 链接。"""
    base = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    return f"{base.rstrip('/')}/trace/{trace_id}"


# 别名（兼容旧代码）
get_client = get_langfuse_client


def build_langfuse_metadata(user_id: str = "", session_id: str = "") -> dict:
    """构建 trace 元数据。"""
    metadata: dict = {}
    if user_id:
        metadata["user_id"] = user_id
    if session_id:
        metadata["session_id"] = session_id
    metadata["tags"] = ["sql-agent-ms"]
    return metadata
