"""Thread 业务逻辑层。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ZBot.session.manager import Thread, ThreadManager


def _display_content(content: Any) -> str:
    """把 Thread 里的 content(可能是 str 或 content-block list)显示成纯文本。"""
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


def thread_message_detail(thread: Thread) -> list[dict[str, Any]]:
    """把 Thread.messages 转成 ThreadMessage 列表。"""
    messages: list[dict[str, Any]] = []
    for index, message in enumerate(thread.messages):
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = _display_content(message.get("content"))
        if role == "assistant" and not content and message.get("tool_calls"):
            continue
        if not content:
            continue
        item: dict[str, Any] = {
            "id": f"{thread.thread_name}-{index}",
            "role": role,
            "content": content,
            "timestamp": message.get("timestamp"),
        }
        tools_used = message.get("tools_used")
        if isinstance(tools_used, list) and tools_used:
            item["tools_used"] = tools_used
        messages.append(item)
    return messages


def thread_summary(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": meta.get("name", ""),
        "created_at": meta.get("created_at", datetime.now().isoformat()),
        "updated_at": meta.get("updated_at", datetime.now().isoformat()),
        "message_count": int(meta.get("message_count", 0)),
        "title": meta.get("title"),
        "pinned": bool(meta.get("pinned", False)),
        "archived": bool(meta.get("archived", False)),
    }


def thread_detail_from_thread(thread: Thread) -> dict[str, Any]:
    messages = thread_message_detail(thread)
    return {
        "name": thread.thread_name,
        "created_at": thread.created_at.isoformat(),
        "updated_at": thread.updated_at.isoformat(),
        "message_count": len(messages),
        "messages": messages,
        "title": thread.title,
        "pinned": thread.pinned,
        "archived": thread.archived,
    }


# ---------------------------------------------------------------------------
# 业务操作
# ---------------------------------------------------------------------------

class ThreadAlreadyExists(Exception):
    pass


class ThreadNotFound(Exception):
    pass


async def list_threads(
    manager: ThreadManager,
    *,
    archived: bool = False,
    pinned_only: bool = False,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    metas = await manager.list_sessions(
        archived=archived, pinned_only=pinned_only, search=search
    )
    return [thread_summary(m) for m in metas]


async def get_thread_detail(manager: ThreadManager, name: str) -> dict[str, Any]:
    session = await manager.get(name)
    if session is None:
        raise ThreadNotFound(name)
    return thread_detail_from_thread(session)


async def create_thread(manager: ThreadManager, name: str) -> dict[str, Any]:
    if await manager.exists(name):
        raise ThreadAlreadyExists(name)
    session, _ = await manager.get_or_create(name)
    await manager.save(session)
    return thread_detail_from_thread(session)


async def update_thread(
    manager: ThreadManager,
    old_name: str,
    *,
    new_name: Optional[str] = None,
    title: Optional[str] = None,
    pinned: Optional[bool] = None,
    archived: Optional[bool] = None,
) -> dict[str, Any]:
    if new_name is not None and new_name != old_name:
        ok = await manager.rename(old_name, new_name)
        if not ok:
            raise ThreadNotFound(f"{old_name} (或 {new_name} 已存在)")
        old_name = new_name

    if title is not None or pinned is not None or archived is not None:
        await manager.update_metadata(
            old_name,
            title=title,
            pinned=pinned,
            archived=archived,
        )

    session = await manager.get(old_name)
    if session is None:
        raise ThreadNotFound(old_name)
    return thread_detail_from_thread(session)


async def delete_thread(manager: ThreadManager, name: str) -> bool:
    return await manager.delete(name)
