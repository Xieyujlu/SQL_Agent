"""用户属性长期记忆 — MySQL 存储（key-value 模式）。"""

import os
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base

Base = declarative_base()


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    attribute = Column(String(128), nullable=False)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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


def get_profile(user_id: str) -> dict:
    """读取用户所有属性，返回 {attribute: value}。"""
    _ensure_table()
    with Session(_engine) as session:
        rows = session.query(UserProfile).filter(
            UserProfile.user_id == user_id
        ).all()
        return {row.attribute: row.value for row in rows}


def set_profile(user_id: str, attribute: str, value: str):
    """写入或更新用户属性。已存在的 attribute 会覆盖。"""
    _ensure_table()
    with Session(_engine) as session:
        row = session.query(UserProfile).filter(
            UserProfile.user_id == user_id,
            UserProfile.attribute == attribute,
        ).first()
        if row:
            row.value = value
            row.updated_at = datetime.utcnow()
        else:
            session.add(UserProfile(
                user_id=user_id,
                attribute=attribute,
                value=value,
            ))
        session.commit()
