"""长期记忆工具 — 用户属性（MySQL）+ 事件记忆（ChromaDB）。"""

import json
from contextvars import ContextVar
from typing import Optional

from langchain_core.tools import BaseTool
from pydantic import Field, create_model

from src.agent.utils.event_memory import save_event, search_events
from src.agent.utils.user_profile_db import get_profile, set_profile

# 通过 contextvar 从 API 层传递当前 user_id
current_user_id: ContextVar[str] = ContextVar("current_user_id", default="default")


class GetUserProfileTool(BaseTool):
    """读取用户已存储的属性/偏好。"""

    name: str = "get_user_profile"
    description: str = (
        "读取当前用户已存储的个人信息与偏好。输入属性名列表（逗号分隔），"
        "留空则返回全部已存储属性。用于在回答问题前获取用户的偏好设置。"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.args_schema = create_model(
            "GetUserProfileArgs",
            keys=(Optional[str], Field(default=None, description="要查询的属性名，逗号分隔，如'称呼,偏好输出'。留空返回全部。")),
        )

    def _run(self, keys: Optional[str] = None) -> str:
        uid = current_user_id.get()
        profile = get_profile(uid)
        if not profile:
            return "当前用户暂无已存储的个人信息或偏好。"
        if keys:
            wanted = {k.strip() for k in keys.split(",") if k.strip()}
            filtered = {k: v for k, v in profile.items() if k in wanted}
            if not filtered:
                return f"未找到属性: {keys}。已存储的属性有: {', '.join(profile.keys())}"
            return json.dumps(filtered, ensure_ascii=False, indent=2)
        return json.dumps(profile, ensure_ascii=False, indent=2)


class SetUserProfileTool(BaseTool):
    """存储或更新用户属性/偏好。"""

    name: str = "set_user_profile"
    description: str = (
        "存储或更新当前用户的个人信息/偏好。每次设置一个属性。"
        "例如：用户说'以后用表格展示'，则 attribute='偏好输出', value='表格'。"
        "用户说'我是做量化分析的'，则 attribute='领域', value='量化分析'。"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.args_schema = create_model(
            "SetUserProfileArgs",
            attribute=(str, Field(description="属性名，如'称呼'、'领域'、'偏好输出'")),
            value=(str, Field(description="属性值，如'张工'、'量化分析'、'表格'")),
        )

    def _run(self, attribute: str, value: str) -> str:
        uid = current_user_id.get()
        set_profile(uid, attribute, value)
        return f"已记住：{attribute} = {value}"


class SaveEventTool(BaseTool):
    """存储重大事件到向量记忆（用于后续语义检索）。"""

    name: str = "save_event"
    description: str = (
        "记录重大事件到长期记忆，用于未来的经验回溯。"
        "适用场景：SQL 查询失败原因、用户纠正了错误理解、用户给出了重要反馈。"
        "event_type 可选值: error（错误）、correction（纠正）、feedback（反馈）、preference（偏好变更）。"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.args_schema = create_model(
            "SaveEventArgs",
            content=(str, Field(description="事件详细描述。尽可能具体，便于后续语义检索。")),
            event_type=(Optional[str], Field(default="", description="事件类型: error/correction/feedback/preference")),
        )

    def _run(self, content: str, event_type: str = "") -> str:
        uid = current_user_id.get()
        save_event(uid, content, event_type)
        return f"事件已记录（类型: {event_type or '通用'}）: {content[:100]}"


class SearchEventTool(BaseTool):
    """语义搜索历史事件。"""

    name: str = "search_event"
    description: str = (
        "搜索历史事件记忆。用于查询类似错误、过往纠正、历史反馈。"
        "在遇到问题或不确定时先搜索相关事件，借鉴过往经验。"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.args_schema = create_model(
            "SearchEventArgs",
            query=(str, Field(description="搜索查询，如'表名错误'、'SQL语法问题'")),
            n_results=(int, Field(default=3, description="返回结果数量")),
        )

    def _run(self, query: str, n_results: int = 3) -> str:
        uid = current_user_id.get()
        events = search_events(uid, query, n_results)
        if not events:
            return "未找到相关历史事件。"
        lines = []
        for i, ev in enumerate(events):
            lines.append(
                f"{i+1}. [{ev['event_type'] or '通用'}] {ev['content']}\n"
                f"   时间: {ev['created_at']}  相关度: {ev['relevance']}"
            )
        return "\n\n".join(lines)
