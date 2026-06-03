"""Agent WebSocket 请求编排。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from ZBot.backend.handlers.agent_files import file_store
from ZBot.services.agent_run.agent_factory import AgentSetupError
from ZBot.services.agent_run.agent_run_service import (
    AgentEvent,
    AgentRunService,
    create_agent_run_service,
)
from ZBot.services.config import config_cache

EventQueue = asyncio.Queue[dict[str, Any] | None]


async def handle_agent_websocket(
    websocket: WebSocket,
) -> None:
    """
    接收前端命令，并向前端实时推送 Agent 运行事件。
    同一个接口地址 ≠ 同一条 WebSocket 连接,后端就会分别执行一份 agent_websocket() 函数实例,每个实例负责一个 WebSocket 连接，互相独立。
    """

    await websocket.accept()

    queue: EventQueue = asyncio.Queue()
    writer_task = asyncio.create_task(websocket_writer(websocket, queue))

    active_task: asyncio.Task[None] | None = None
    service: AgentRunService | None = None

    # 当前 WebSocket 连接绑定的 session。
    session_name: str = ""

    async def cancel_active_task() -> None:
        """取消当前 WebSocket 连接中正在运行的 Agent 任务。"""
        nonlocal active_task

        if active_task is not None and not active_task.done():
            active_task.cancel()
            # 所有任务执行完毕才返回，不会因为单个报错终止整体等待
            await asyncio.gather(active_task, return_exceptions=True)

        active_task = None

    async def close_service() -> None:
        """关闭当前 WebSocket 连接绑定的 Agent 服务。"""
        nonlocal service

        if service is not None and session_name:
            await service.close(session_name)
            service = None

    try:
        while True:
            command = await websocket.receive_json()

            if not isinstance(command, dict):
                await put_control_event(
                    queue,
                    "run.failed",
                    session_name or "default",
                    "命令格式错误，命令必须为 JSON 对象。",
                )
                continue

            command_type = command.get("type", "")

            # 取消当前连接正在运行的任务。
            if command_type == "run.cancel":
                await cancel_active_task()
                await close_service()
                continue


            received_session_name = command.get("session_name", "")
            message = command.get("message", "")
            file_id = command.get("file_id", "")

            if not isinstance(received_session_name, str) or not received_session_name.strip():
                await put_control_event(
                    queue,
                    "run.failed",
                    session_name or "default",
                    "命令格式错误，必须包含有效的 session_name 字段。",
                )
                continue
            session_name = received_session_name

            # 当前连接同一时间只允许运行一个 Agent 任务。
            if active_task is not None and not active_task.done():
                await put_control_event(
                    queue,
                    "run.failed",
                    received_session_name,
                    "当前已有任务正在运行，请先停止当前任务。",
                )
                continue

            if not isinstance(message, str) or not message.strip():
                await put_control_event(
                    queue,
                    "run.failed",
                    received_session_name,
                    "命令格式错误，run.start 必须包含有效的 message 字段。",
                )
                continue


            # 先校验并组织本次任务输入内容。
            if file_id:
                if not isinstance(file_id, str) or file_id not in file_store:
                    await put_control_event(
                        queue,
                        "run.failed",
                        received_session_name,
                        "文件不存在，请重新上传文件。",
                    )
                    continue

                message_blocks: str | list[dict[str, Any]] = [
                    {"type": "text", "text": message},
                    *file_store[file_id],
                ]
            else:
                message_blocks = message

                
            # 第一次运行或取消后重新运行时，创建当前 session 对应的服务。
            if service is None:
                config = config_cache.get()

                if config is None:
                    await put_control_event(
                        queue,
                        "run.failed",
                        session_name,
                        "无法加载配置文件，请先完成 ZBot 配置。",
                    )
                    continue

                try:
                    service = create_agent_run_service(config)
                except AgentSetupError as exc:
                    await put_control_event(
                        queue,
                        "run.failed",
                        session_name,
                        exc.message,
                        payload={"code": exc.code},
                    )
                    continue

            try:
                await service.start(
                    session_name,
                    event_sink=queue_event_sink(queue),
                )
            except Exception as exc:
                logger.exception("WebSocket Agent service 启动失败")
                await put_control_event(
                    queue,
                    "run.failed",
                    session_name,
                    f"任务启动失败：{exc}",
                )
                await close_service()
                continue

            active_task = asyncio.create_task(
                run_agent(
                    service,
                    message_blocks,
                    session_name,
                    queue,
                )
            )

    except WebSocketDisconnect:
        logger.info("WebSocket 连接已断开，session_name={}", session_name)

    except Exception as exc:
        logger.exception("WebSocket 会话处理失败")
        await put_control_event(
            queue,
            "run.failed",
            session_name or "default",
            f"连接处理失败：{exc}",
        )

    finally:
        await cancel_active_task()
        await close_service()

        await queue.put(None)
        await asyncio.gather(writer_task, return_exceptions=True)


async def run_agent(
    service: AgentRunService,
    message: str | list[dict[str, Any]],
    session_name: str,
    queue: EventQueue,
) -> None:
    """执行一轮 Agent 对话。"""

    try:
        await service.ask(
            message,
            session_name,
            event_sink=queue_event_sink(queue),
        )

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        logger.exception("WebSocket Agent run 失败")
        await put_control_event(
            queue,
            "run.failed",
            session_name,
            f"任务失败：{exc}",
        )


async def websocket_writer(
    websocket: WebSocket,
    queue: EventQueue,
) -> None:
    """持续从事件队列中读取事件，并发送给前端。"""

    while True:
        event = await queue.get()

        if event is None:
            return

        await websocket.send_json(event)


def queue_event_sink(queue: EventQueue):
    """创建 Agent 事件接收函数，将运行事件写入发送队列。"""

    async def _sink(event: AgentEvent) -> None:
        await queue.put(event.to_dict())

    return _sink


async def put_control_event(
    queue: EventQueue,
    event_type: str,
    session_name: str,
    message: str,
    *,
    payload: dict[str, Any] | None = None,
) -> None:
    """创建控制事件，并写入发送队列。"""

    if payload is None:
        event = AgentEvent.control_event(
            event_type,
            session_name,
            message,
        )
    else:
        event = AgentEvent.control_event(
            event_type,
            session_name,
            message,
            payload=payload,
        )

    if isinstance(event, AgentEvent):
        await queue.put(event.to_dict())
    else:
        await queue.put(event)
