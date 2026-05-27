"""事件长期记忆 — ChromaDB 向量存储，支持语义检索。"""

import os
from datetime import datetime

import chromadb
from chromadb.config import Settings

PERSIST_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "chroma")
PERSIST_DIR = os.path.abspath(PERSIST_DIR)

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        os.makedirs(PERSIST_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=PERSIST_DIR,
            settings=Settings(anonymized_telemetry=False),
        )
        _collection = _client.get_or_create_collection(
            name="event_memory",
            metadata={"description": "重大事件记忆（任务失败、用户纠正等）"},
        )
    return _collection


def save_event(user_id: str, content: str, event_type: str = "", session_id: str = ""):
    """存储事件到向量数据库。

    Args:
        user_id: 用户标识
        content: 事件文本（用于生成向量）
        event_type: 事件类型标签（如 "error", "correction", "preference"）
        session_id: 关联的会话 ID
    """
    col = _get_collection()
    doc_id = f"{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    col.add(
        documents=[content],
        metadatas=[{
            "user_id": user_id,
            "event_type": event_type,
            "session_id": session_id,
            "created_at": datetime.utcnow().isoformat(),
        }],
        ids=[doc_id],
    )


def search_events(user_id: str, query: str, n: int = 5) -> list[dict]:
    """语义搜索相关事件。

    Args:
        user_id: 用户标识（用于过滤）
        query: 搜索查询文本
        n: 返回数量

    Returns:
        [{"content": ..., "event_type": ..., "created_at": ...}, ...]
    """
    col = _get_collection()
    try:
        results = col.query(
            query_texts=[query],
            n_results=n,
            where={"user_id": user_id},
        )
    except Exception:
        # 可能 collection 为空，或元数据过滤不匹配
        return []

    if not results["documents"] or not results["documents"][0]:
        return []

    events = []
    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i] if results["metadatas"] else {}
        dist = results["distances"][0][i] if results["distances"] else None
        events.append({
            "content": doc,
            "event_type": meta.get("event_type", ""),
            "created_at": meta.get("created_at", ""),
            "relevance": round(1 - dist, 3) if dist is not None else None,
        })
    return events
