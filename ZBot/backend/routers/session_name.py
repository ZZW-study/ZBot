from fastapi import APIRouter

from ZBot.backend.handlers.sessions import session_detail
from ZBot.backend.schemas.session import SessionCreateRequest, SessionRenameRequest
from ZBot.config.schema import Config
from ZBot.services.config import config_cache
from ZBot.session.manager import SessionManager


router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
)


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
    return session_detail(session)


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
