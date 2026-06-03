from fastapi import APIRouter
from pydantic import BaseModel
from ZBot.session.manager import Session, SessionManager
from ZBot.config.schema import Config
from typing import Any
from ZBot.service.config_service import config_cache

class SessionCreateRequest(BaseModel):
    name: str


class SessionRenameRequest(BaseModel):
    name: str


router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
)


def _display_content(content: Any) -> str:
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


def _session_message_detail(session: Session) -> list[dict[str, Any]]:
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


def _session_detail(session: Session) -> dict[str, Any]:
    messages = _session_message_detail(session)
    return {
        "name": session.session_name,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "message_count": len(messages),
        "messages": messages,
    }


@router.get("/list_sessions")
async def list_sessions():
    """列出所有会话。"""
    config: Config | None = config_cache.get()
    if config:
        workspace = config.workspace_path
        manager = SessionManager(workspace)
        sessions = await manager.list_sessions()
        return {"sessions": sessions}
    else:
        return {"ok": False, "error": "未配置"}


@router.get("/{session_name}")
async def get_session_detail(session_name: str):
    config = config_cache.get()
    if config is None:
        return {"ok": False, "error": "not configured"}

    manager = SessionManager(config.workspace_path)
    session, _ = await manager.get_or_create(session_name)
    return _session_detail(session)


@router.post("/create_session")
async def create_session(req: SessionCreateRequest):
    """创建新会话。"""
    config = config_cache.get()
    if config is None:
        return {"ok": False, "error": "未配置"}
    workspace = config.workspace_path
    manager = SessionManager(workspace)
    session, _ = await manager.get_or_create(req.name)
    await manager.save(session)
    return {"ok": True, "name": req.name}


@router.put("{session_name}")
async def rename_session(session_name: str, req: SessionRenameRequest):
    """重命名会话。"""
    config = config_cache.get()
    if config is None:
        return {"ok": False, "error": "未配置"}
    workspace = config.workspace_path
    manager = SessionManager(workspace)
    renamed = await manager.rename(session_name, req.name)
    if not renamed:
        return {"ok": False, "error": "原会话不存在或新名称已存在"}
    return {"ok": True, "name": req.name}


@router.delete("{session_name}")
async def delete_session(session_name: str):
    """删除指定会话。"""
    config = config_cache.get()
    if config is None:
        return {"ok": False, "error": "未配置"}

    workspace = config.workspace_path
    manager = SessionManager(workspace)
    deleted = await manager.delete(session_name)
    return {"ok": deleted}