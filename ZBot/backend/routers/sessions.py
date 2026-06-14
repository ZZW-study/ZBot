"""Session REST API router.

URL:
  GET    /api/sessions                          -> list
  POST   /api/sessions                          -> create (201 + Location)
  GET    /api/sessions/{name}                   -> detail (404 if missing)
  PATCH  /api/sessions/{name}                   -> rename
  DELETE /api/sessions/{name}                   -> 204 (404 if missing)

All endpoints use the session manager from app.state via get_session_manager dependency.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ZBot.backend.dependencies import get_session_manager
from ZBot.backend.handlers.sessions import (
    SessionAlreadyExists,
    SessionNotFound,
    create_session,
    delete_session,
    get_session_detail,
    list_sessions,
    rename_session,
)
from ZBot.backend.schemas.sessions import (
    SessionCreate,
    SessionDetail,
    SessionSummary,
    SessionUpdate,
)
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
