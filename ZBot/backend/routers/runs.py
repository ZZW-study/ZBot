"""/api/sessions/{name}/runs/* 路由:启动 / 状态 / 取消 / SSE 流。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from ZBot.backend.dependencies import (
    get_config_or_503,
    get_follow_up_queue,
    get_run_registry,
    get_session_manager,
)
from ZBot.backend.handlers.agent_sse import run_worker, stream_run_events
from ZBot.backend.schemas.agent import (
    RunResponse,
    RunStartRequest,
    RunStatusResponse,
)
from ZBot.services.agent_run.follow_up_queue import FollowUpQueue
from ZBot.services.agent_run.run_registry import RunRegistry, RunState
from ZBot.session.manager import SessionManager


router = APIRouter(prefix="/api/sessions", tags=["runs"])


async def _resolve_run(registry: RunRegistry, name: str, run_id: str) -> RunState:
    """run 必须存在且属于给定的 session,否则 404。"""
    state = await registry.get(run_id)
    if state is None or state.session_name != name:
        raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
    return state


@router.post(
    "/{name}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=True,
)
async def start_run(
    name: str,
    body: RunStartRequest,
    _config=Depends(get_config_or_503),  # 必须在 manager.exists 前求值 → 无 config 直接 503
    manager: SessionManager = Depends(get_session_manager),
    registry: RunRegistry = Depends(get_run_registry),
    queue: FollowUpQueue = Depends(get_follow_up_queue),
) -> RunResponse:
    if not await manager.exists(name):
        raise HTTPException(status_code=404, detail=f"session 不存在: {name}")

    state = await registry.create(name)
    task = asyncio.create_task(
        run_worker(state, registry, body.message, queue, file_id=body.file_id)
    )
    await registry.attach_task(state.run_id, task)

    base = f"/api/sessions/{name}/runs/{state.run_id}"
    return RunResponse(
        run_id=state.run_id,
        session_name=name,
        status=state.status.value,
        created_at=state.created_at,
        events_url=f"{base}/events",
        status_url=base,
    )


@router.get(
    "/{name}/runs/{run_id}",
    response_model=RunStatusResponse,
    response_model_by_alias=True,
)
async def get_run(
    name: str,
    run_id: str,
    registry: RunRegistry = Depends(get_run_registry),
) -> RunStatusResponse:
    state = await _resolve_run(registry, name, run_id)
    return RunStatusResponse(
        run_id=state.run_id,
        session_name=state.session_name,
        status=state.status.value,
        created_at=state.created_at,
        started_at=state.started_at,
        ended_at=state.ended_at,
        error=state.error,
    )


@router.delete("/{name}/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_run(
    name: str,
    run_id: str,
    registry: RunRegistry = Depends(get_run_registry),
) -> Response:
    await _resolve_run(registry, name, run_id)  # wrong/missing run → 404
    await registry.request_cancel(run_id)       # 已结束则 noop,仍 204
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{name}/runs/{run_id}/events")
async def stream_run(
    name: str,
    run_id: str,
    registry: RunRegistry = Depends(get_run_registry),
    queue: FollowUpQueue | None = Depends(get_follow_up_queue),
) -> StreamingResponse:
    state = await _resolve_run(registry, name, run_id)
    return StreamingResponse(
        stream_run_events(state, registry, queue),
        media_type="text/event-stream",
    )
