"""/api/sessions/{name}/runs/* 路由:启动 / 状态 / 取消 / SSE 流。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from ZBot.backend.dependencies import (
    get_config_or_503,
    get_run_registry,
    get_session_manager,
)
from ZBot.backend.agent_service_pool import get_or_create_agent_service
from ZBot.backend.handlers.agent_sse import run_worker, stream_run_events
from ZBot.backend.schemas.agent import (
    RunResponse,
    RunStartRequest,
    RunStatusResponse,
)
from ZBot.services.agent_run.run_registry import RunRegistry, RunState
from ZBot.session.manager import SessionManager
from ZBot.services.heartbeat.hb import ActivityTracker, ActivityWatchdog

router = APIRouter(prefix="/api/sessions", tags=["runs"])


async def _resolve_run(registry: RunRegistry, name: str, run_id: str) -> RunState:
    """run 必须存在且属于给定的 session,否则 404。"""
    state = await registry.get(run_id)
    if state is None or state.session_name != name:
        raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
    return state


@router.post(
    "/{name}/runs",  # 会话名字作为路径参数
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=True,
)
async def start_run(
    name: str,
    body: RunStartRequest,
    request: Request,
    _config=Depends(get_config_or_503),  # 必须在 manager.exists 前求值 → 无 config 直接 503
    manager: SessionManager = Depends(get_session_manager),
    runs: RunRegistry = Depends(get_run_registry),
) -> RunResponse:
    """一次请求，就是一个协程，各个协程独立，只要是在内部的（函数底下、类底下）变量、类等等，都是局部的，
    不会共享，如果在外部，就是顶层的变量，就会共享，不安全
    # 加入中途打断取消或者各自原因执行失败，再发一次信息（算另一个协程，之前的协程销毁，状态消失），会创建一个新的状态
    启动任务后立刻返回，这个协程就结束了
    """
    if not await manager.exists(name):
        raise HTTPException(status_code=404, detail=f"session 不存在: {name}")

    state = await runs.create(name)
    
    # 开启协程任务，这算是第二个协程,那么可以在这个协程await的时候，直接往下执行
    # 执行完成或者发生异常，就执行结束，这个协程就销毁，那么这个协程的局部变量啥的，都没有了
    # 但是后面会结束，会将消息保存进磁盘，第二次请求的时候，由于会话名字相同，从磁盘读取就相同
    # ZBot 改: 跨 run 复用一个共享的 AgentRunService (避免每次 sendMessage 重建 + 重连 MCP)
    shared_service = await get_or_create_agent_service(request.app)
    task = asyncio.create_task(
        run_worker(state, runs, body.message, file_id=body.file_id, service=shared_service)
    )

    # 获取当前事件循环,传入后可以用loop.call_soon_threadsafe，把其他线程想干的事情，放入这个事件循环中，比如安全的取消
    loop = asyncio.get_running_loop()
    activity_watchdog = ActivityWatchdog(tracker=ActivityTracker(),loop=loop,task=task)

    # 开启心跳狗线程,这个主要是管理，任务在执行，怕一直卡着，错误不用他管，都用try，except管错误
    activity_watchdog.start()
    await runs.attach_task(state.run_id, task)

    base = f"/api/sessions/{name}/runs/{state.run_id}"
    # 返回之后，交给下面的处理
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
) -> StreamingResponse:
    """
    SSE入口：SSE = 浏览器（客户端）建立一个 HTTP 长连接，然后只接收服务器持续推送的数据流
    前端连接这里 = 建立“事件流订阅”
    """
    # 1. 找到当前 run 的运行状态（RunState）
    state = await _resolve_run(registry, name, run_id)

    # 2. 把“事件流生成器”交给 FastAPI StreamingResponse
    #    => FastAPI 会持续从 stream_run_events() 取数据并推给前端
    return StreamingResponse(
        stream_run_events(state),
        media_type="text/event-stream",
    )
