"""Session 业务逻辑层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ZBot.session.manager import Session, SessionManager


# ---------------------------------------------------------------------------
# 显示工具
# ---------------------------------------------------------------------------

def _display_content(content: Any) -> str:
    """把 Session.message.content(可能是 str 或 content-block list)显示成纯文本。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block.get("type") == "image_url":
            parts.append("[image]")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 业务异常
# ---------------------------------------------------------------------------

class SessionAlreadyExists(Exception):
    pass


class SessionNotFound(Exception):
    pass


# ---------------------------------------------------------------------------
# 响应组装
# ---------------------------------------------------------------------------

def session_message_detail(session: Session) -> list[dict[str, Any]]:
    """把 Session.messages 转成前端展示用的消息列表(每条带 id/role/content/timestamp/tools_used)。"""
    messages: list[dict[str, Any]] = []
    for index, message in enumerate(session.messages):
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = _display_content(message.get("content"))
        if role == "assistant" and not content and message.get("tool_calls"):
            continue
        if not content:
            continue
        item: dict[str, Any] = {
            "id": f"{session.session_name}-{index}",
            "role": role,
            "content": content,
            "timestamp": message.get("timestamp"),
        }
        tools_used = message.get("tools_used")
        if isinstance(tools_used, list) and tools_used:
            item["tools_used"] = tools_used
        messages.append(item)
    return messages


def session_summary(meta: dict[str, Any]) -> dict[str, Any]:
    """把磁盘元数据 dict 转换成前端 list 接口的轻量记录。"""
    return {
        "name": meta.get("name", ""),
        "created_at": meta.get("created_at", datetime.now().isoformat()),
        "updated_at": meta.get("updated_at", datetime.now().isoformat()),
        "message_count": int(meta.get("message_count", 0)),
    }


def session_detail_from_session(session: Session) -> dict[str, Any]:
    """组装 GET /api/sessions/{name} 的完整响应。"""
    messages = session_message_detail(session)
    return {
        "name": session.session_name,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "message_count": len(messages),
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# 业务操作
# ---------------------------------------------------------------------------

async def list_sessions(
    manager: SessionManager,
    *,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    """列出所有会话的摘要元信息。可选 `search` 关键字按 name 子串(忽略大小写)过滤。"""
    metas = await manager.list_sessions()
    if search:
        needle = search.lower()
        metas = [m for m in metas if needle in str(m.get("name", "")).lower()]
    return [session_summary(m) for m in metas]


async def get_session_detail(manager: SessionManager, name: str) -> dict[str, Any]:
    """只读获取指定会话详情。磁盘/缓存都不存在则抛 SessionNotFound。"""
    session = await manager.get(name)
    if session is None:
        raise SessionNotFound(name)
    return session_detail_from_session(session)


async def create_session(manager: SessionManager, name: str) -> dict[str, Any]:
    """创建新会话。若同名已存在,抛 SessionAlreadyExists。"""
    if await manager.exists(name):
        raise SessionAlreadyExists(name)
    session, _ = await manager.get_or_create(name)
    await manager.save(session)
    return session_detail_from_session(session)


async def rename_session(manager: SessionManager, old_name: str, new_name: str) -> dict[str, Any]:
    """重命名会话。原名不存在或新名已被占用,抛 SessionNotFound。"""
    ok = await manager.rename(old_name, new_name)
    if not ok:
        raise SessionNotFound(f"{old_name} (或 {new_name} 已存在)")
    session = await manager.get(new_name)
    if session is None:
        raise SessionNotFound(new_name)
    return session_detail_from_session(session)


async def delete_session(manager: SessionManager, name: str) -> bool:
    """删除指定会话。返回是否成功(不存在则为 False)。"""
    return await manager.delete(name)
