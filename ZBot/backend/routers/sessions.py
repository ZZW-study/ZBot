"""Session REST API router.

URL:
  GET    /api/sessions                          -> list
  POST   /api/sessions                          -> create (201 + Location)
  GET    /api/sessions/{name}                   -> detail (404 if missing)
  PATCH  /api/sessions/{name}                   -> rename
  DELETE /api/sessions/{name}                   -> 204 (404 if missing)
  GET    /api/sessions/{name}/follow-ups        -> list queued follow-ups
  POST   /api/sessions/{name}/follow-ups        -> enqueue a follow-up
  DELETE /api/sessions/{name}/follow-ups/{id}   -> remove a queued follow-up

All endpoints use the session manager from app.state via get_session_manager dependency.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ZBot.backend.dependencies import (
    get_follow_up_queue,
    get_session_manager,
)
from ZBot.backend.handlers.sessions import (
    SessionAlreadyExists,
    SessionNotFound,
    create_session,
    delete_session,
    get_session_detail,
    list_sessions,
    rename_session,
)
from ZBot.backend.schemas.agent import FollowUp, FollowUpCreate
from ZBot.backend.schemas.sessions import (
    SessionCreate,
    SessionDetail,
    SessionSummary,
    SessionUpdate,
)
from ZBot.services.agent_run.follow_up_queue import FollowUpQueue
from ZBot.session.manager import SessionManager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Collection(集合)
# ---------------------------------------------------------------------------

@router.get("", response_model=list[SessionSummary], response_model_by_alias=True)
async def list_endpoint(
    search: str | None = Query(default=None, description="Case-insensitive name substring filter"),
    manager: SessionManager = Depends(get_session_manager),
) -> list[dict]:
    return await list_sessions(manager, search=search)


@router.post("", response_model=SessionDetail, status_code=status.HTTP_201_CREATED, response_model_by_alias=True)
async def create_endpoint(
    body: SessionCreate,
    response: Response,
    manager: SessionManager = Depends(get_session_manager),
) -> dict:
    try:
        detail = await create_session(manager, body.name)
    except SessionAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=f"session 已存在: {exc}")
    response.headers["Location"] = f"/api/sessions/{body.name}"
    return detail


# ---------------------------------------------------------------------------
# Single session(单个会话)
# ---------------------------------------------------------------------------

@router.get("/{name}", response_model=SessionDetail, response_model_by_alias=True)
async def get_endpoint(
    name: str,
    manager: SessionManager = Depends(get_session_manager),
) -> dict:
    try:
        return await get_session_detail(manager, name)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail=f"session 不存在: {name}")


@router.patch("/{name}", response_model=SessionDetail, response_model_by_alias=True)
async def patch_endpoint(
    name: str,
    body: SessionUpdate,
    manager: SessionManager = Depends(get_session_manager),
) -> dict:
    if body.name is None:
        raise HTTPException(
            status_code=400,
            detail="至少提供一个要更新的字段(name)",
        )
    try:
        return await rename_session(manager, name, body.name)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=f"session 不存在: {exc}")


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    name: str,
    manager: SessionManager = Depends(get_session_manager),
) -> Response:
    deleted = await delete_session(manager, name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"session 不存在: {name}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Follow-ups(steering)
# ---------------------------------------------------------------------------

def _to_follow_up(fu) -> FollowUp:
    return FollowUp(
        follow_up_id=fu.follow_up_id,
        session_name=fu.session_name,
        message=fu.message,
        queued_at=fu.queued_at,
    )


@router.get("/{name}/follow-ups", response_model=list[FollowUp], response_model_by_alias=True)
async def list_follow_ups(
    name: str,
    manager: SessionManager = Depends(get_session_manager),
    queue: FollowUpQueue = Depends(get_follow_up_queue),
) -> list[FollowUp]:
    if not await manager.exists(name):
        raise HTTPException(status_code=404, detail=f"session 不存在: {name}")
    items = await queue.list(name)
    return [_to_follow_up(fu) for fu in items]


@router.post("/{name}/follow-ups", response_model=FollowUp, status_code=status.HTTP_201_CREATED, response_model_by_alias=True)
async def create_follow_up(
    name: str,
    body: FollowUpCreate,
    manager: SessionManager = Depends(get_session_manager),
    queue: FollowUpQueue = Depends(get_follow_up_queue),
) -> FollowUp:
    if not await manager.exists(name):
        raise HTTPException(status_code=404, detail=f"session 不存在: {name}")
    fu = await queue.enqueue(name, body.message)
    return _to_follow_up(fu)


@router.delete("/{name}/follow-ups/{fu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow_up(
    name: str,
    fu_id: str,
    queue: FollowUpQueue = Depends(get_follow_up_queue),
) -> Response:
    # 校验 follow-up 是否属于当前 session,防止用其他 session 的 fu_id 误删。
    removed = await queue.remove(fu_id, session_name=name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"follow-up 不存在: {fu_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
