"""HITL 反馈存储 — 将用户反馈写入本地 MySQL。"""

import os
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base

Base = declarative_base()


class HitlFeedback(Base):
    __tablename__ = "hitl_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, index=True)
    decision = Column(String(20), nullable=False)
    message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


def _get_engine():
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "123456")
    database = os.getenv("MYSQL_DATABASE", "stock")

    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    return create_engine(url)


_engine = None


def _ensure_table():
    global _engine
    if _engine is None:
        _engine = _get_engine()
        Base.metadata.create_all(_engine)


def save_feedback(session_id: str, decision: str, message: str = ""):
    """保存一条 HITL 反馈记录。"""
    _ensure_table()
    with Session(_engine) as session:
        fb = HitlFeedback(
            session_id=session_id,
            decision=decision,
            message=message,
        )
        session.add(fb)
        session.commit()
