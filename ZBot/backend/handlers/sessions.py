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
    """把 Session.messages 转成前端展示用的消息列表(每条带 id/role/content/timestamp/tools_used)。

    ZBot 改: agent loop 中间轮的 assistant 消息(有 content + tool_calls 同时存在)被
    折叠掉, 不在历史视图展开成多个 bubble。原因: 这些中间轮是模型"我决定调工具"时的
    过程性输出(例如"我先用 web_search 查天气"), 不是给用户看的最终答案, 在历史
    视图里展示会让用户困惑(用户原话: "重新点进去怎么变成这样")。tool_calls 本身
    已经在 SSE 流式阶段被收进折叠的工具调用摘要卡片, 不需要历史视图再渲染。
    只保留: user 消息 + 最终 assistant 消息(没有 tool_calls 的那一轮)。
    """
    messages: list[dict[str, Any]] = []
    for index, message in enumerate(session.messages):
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = _display_content(message.get("content"))
        # 跳过: assistant 只有 tool_calls 但没有正文
        if role == "assistant" and not content and message.get("tool_calls"):
            continue
        # ZBot 改: 跳过 agent loop 中间轮 — assistant 有正文但同时也带着 tool_calls
        # 这是中间过程(模型"我先查一下"), 不是给用户看的最终回复。
        if role == "assistant" and message.get("tool_calls"):
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
