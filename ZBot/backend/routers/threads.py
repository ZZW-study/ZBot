"""Thread REST API router.

URL:
  GET    /api/threads                          -> list
  POST   /api/threads                          -> create (201 + Location)
  GET    /api/threads/{name}                   -> detail (404 if missing)
  PATCH  /api/threads/{name}                   -> composite update (rename/title/pinned/archived)
  DELETE /api/threads/{name}                   -> 204 (404 if missing)
  GET    /api/threads/{name}/follow-ups        -> list queued follow-ups
  POST   /api/threads/{name}/follow-ups        -> enqueue a follow-up
  DELETE /api/threads/{name}/follow-ups/{id}   -> remove a queued follow-up

All endpoints use thread manager from app.state via get_thread_manager dependency.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ZBot.backend.dependencies import (
    get_follow_up_queue,
    get_thread_manager,
)
from ZBot.backend.handlers.threads import (
    ThreadAlreadyExists,
    ThreadNotFound,
    create_thread,
    delete_thread,
    get_thread_detail,
    list_threads,
    update_thread,
)
from ZBot.backend.schemas.agent import FollowUp, FollowUpCreate
from ZBot.backend.schemas.threads import (
    ThreadCreate,
    ThreadDetail,
    ThreadSummary,
    ThreadUpdate,
)
from ZBot.services.agent_run.follow_up_queue import FollowUpQueue
from ZBot.session.manager import ThreadManager

router = APIRouter(prefix="/api/threads", tags=["threads"])


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ThreadSummary], response_model_by_alias=True)
async def list_endpoint(
    archived: bool = Query(default=False, description="Include archived threads"),
    pinned_only: bool = Query(default=False, alias="pinnedOnly"),
    search: str | None = Query(default=None, description="Case-insensitive name/title filter"),
    manager: ThreadManager = Depends(get_thread_manager),
) -> list[dict]:
    return await list_threads(manager, archived=archived, pinned_only=pinned_only, search=search)


@router.post("", response_model=ThreadDetail, status_code=status.HTTP_201_CREATED, response_model_by_alias=True)
async def create_endpoint(
    body: ThreadCreate,
    response: Response,
    manager: ThreadManager = Depends(get_thread_manager),
) -> dict:
    try:
        detail = await create_thread(manager, body.name)
    except ThreadAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=f"thread \u5df2\u5b58\u5728: {exc}")
    response.headers["Location"] = f"/api/threads/{body.name}"
    return detail


# ---------------------------------------------------------------------------
# Single thread
# ---------------------------------------------------------------------------

@router.get("/{name}", response_model=ThreadDetail, response_model_by_alias=True)
async def get_endpoint(
    name: str,
    manager: ThreadManager = Depends(get_thread_manager),
) -> dict:
    try:
        return await get_thread_detail(manager, name)
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail=f"thread \u4e0d\u5b58\u5728: {name}")


@router.patch("/{name}", response_model=ThreadDetail, response_model_by_alias=True)
async def patch_endpoint(
    name: str,
    body: ThreadUpdate,
    manager: ThreadManager = Depends(get_thread_manager),
) -> dict:
    if not any([body.name, body.title is not None, body.pinned is not None, body.archived is not None]):
        raise HTTPException(
            status_code=400,
            detail="\u81f3\u5c11\u63d0\u4f9b\u4e00\u4e2a\u8981\u66f4\u65b0\u7684\u5b57\u6bb5",
        )
    try:
        return await update_thread(
            manager,
            name,
            new_name=body.name,
            title=body.title,
            pinned=body.pinned,
            archived=body.archived,
        )
    except ThreadNotFound as exc:
        raise HTTPException(status_code=404, detail=f"thread \u4e0d\u5b58\u5728: {exc}")


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    name: str,
    manager: ThreadManager = Depends(get_thread_manager),
) -> Response:
    deleted = await delete_thread(manager, name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"thread \u4e0d\u5b58\u5728: {name}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Follow-ups (steering)
# ---------------------------------------------------------------------------

def _to_follow_up(fu) -> FollowUp:
    return FollowUp(
        follow_up_id=fu.follow_up_id,
        thread_name=fu.thread_name,
        message=fu.message,
        queued_at=fu.queued_at,
    )


@router.get("/{name}/follow-ups", response_model=list[FollowUp], response_model_by_alias=True)
async def list_follow_ups(
    name: str,
    manager: ThreadManager = Depends(get_thread_manager),
    queue: FollowUpQueue = Depends(get_follow_up_queue),
) -> list[FollowUp]:
    if not await manager.exists(name):
        raise HTTPException(status_code=404, detail=f"thread \u4e0d\u5b58\u5728: {name}")
    items = await queue.list(name)
    return [_to_follow_up(fu) for fu in items]


@router.post("/{name}/follow-ups", response_model=FollowUp, status_code=status.HTTP_201_CREATED, response_model_by_alias=True)
async def create_follow_up(
    name: str,
    body: FollowUpCreate,
    manager: ThreadManager = Depends(get_thread_manager),
    queue: FollowUpQueue = Depends(get_follow_up_queue),
) -> FollowUp:
    if not await manager.exists(name):
        raise HTTPException(status_code=404, detail=f"thread \u4e0d\u5b58\u5728: {name}")
    fu = await queue.enqueue(name, body.message)
    return _to_follow_up(fu)


@router.delete("/{name}/follow-ups/{fu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow_up(
    name: str,
    fu_id: str,
    queue: FollowUpQueue = Depends(get_follow_up_queue),
) -> Response:
    # 校验 follow-up 是否属于当前 thread，防止用其他 thread 的 fu_id 误删。
    removed = await queue.remove(fu_id, thread_name=name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"follow-up \u4e0d\u5b58\u5728: {fu_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
