"""Agent WebSocket harness 路由。"""

from __future__ import annotations

import asyncio
import base64
import uuid
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from loguru import logger

from ZBot.service.agent_run.agent_factory import AgentSetupError
from ZBot.service.agent_run.agent_run_service import (
    AgentEvent,
    AgentRunService,
    create_agent_run_service,
)
from ZBot.service.config_service import config_cache
from ZBot.service.utils.file_utils import (
    IMAGE_MIME_TYPES,
    TEXT_MIME_TYPES,
    UNSUPPORTED_FILE_MIME_TYPES,
    decode_text,
    detect_upload_mime,
)


router = APIRouter(prefix="/api/agent", tags=["agent"])

EventQueue = asyncio.Queue[dict[str, Any] | None]

file_store: dict[str, list[dict[str, Any]]] = {}

# **表单数据**就是一组“字段名 = 值”的数据，类似网页填表：
# question = "总结这个文件"
# session_name = "default"
# files = 上传的 PDF 文件
# 它也有结构，但它不是 JSON 对象那种“结构体请求体”。
# 你的接口要同时传**文件 + 文字**，前端通常会这样组织：
# const data = new FormData()
# data.append("files", file)
# data.append("question", "总结这个文件")
# data.append("session_name", "default")

# 后端对应接收：
# async def ask_with_files(
#     files: list[UploadFile] = File(...),  # 接文件
#     question: str = Form("默认问题"),       # 接表单里的文字
#     session_name: str = Form("default"),   # 接表单里的文字
# ):

# 如果只传普通结构化数据，不上传文件，一般会写成 JSON：
# {
#   "question": "总结这个文件",
#   "session_name": "default"
# }

# 后端可能用一个模型接收：
# class AskRequest(BaseModel):
#     question: str
#     session_name: str
# 核心区别：
# JSON / 结构体：适合传普通数据
# Form + File：适合同时传文字和文件
# 所以这里用 `Form`，是因为它要和 `File(...)` 一起接收上传内容。
# -----------------------------------------------------------------------------
# WebSocket 实现原理说明：
#
# WebSocket 本质上是一种基于 TCP 的通信协议。
#
# 前端最开始会发送一次 HTTP 请求，并携带 Upgrade: websocket 请求头。
# 后端执行 await websocket.accept() 后，完成协议升级：
# 此后这条 TCP 连接不再按照普通 HTTP 的“请求一次、响应一次”工作，
# 而是按照 WebSocket 协议传输一帧一帧的消息数据。
#
# -----------------------------------------------------------------------------
#    前端通过 WebSocket 告诉后端“开始”或“停止”；
#    后端通过 WebSocket 持续告诉前端“处理到哪一步”和“生成了什么内容”。
#    该函数不是“前端不停请求、后端不停响应”。就是后端可以在接受前端命令后，可以一直向前端发信息。
#
#    它的底层过程是：
#        一次 HTTP 握手升级为 WebSocket
#        -> 在同一条 TCP 连接上双向传输 WebSocket 数据帧
#        -> asyncio 事件循环并发管理接收命令、执行 Agent、发送事件
#        -> queue 负责在 Agent 执行逻辑与网络发送逻辑之间传递事件。
# -----------------------------------------------------------------------------
@router.post("/have_files")
async def handle_files(
    files: list[UploadFile] = File(...),
) -> dict[str, str]:
    """接收前端上传的文件，并转换为模型可接收的内容块。"""

    content_blocks: list[dict[str, Any]] = []

    for file in files:
        raw_bytes = await file.read()
        mime = detect_upload_mime(file.filename, file.content_type, raw_bytes)

        logger.info("文件 {} 的 MIME 类型检测结果: {}", file.filename, mime)

        if mime == "application/octet-stream":
            raise HTTPException(
                status_code=415,
                detail=f"无法识别文件类型：{file.filename or 'unknown'}",
            )

        if mime in IMAGE_MIME_TYPES:
            image_encoded_content = base64.b64encode(raw_bytes).decode("utf-8")
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{image_encoded_content}",
                    },
                }
            )

        elif mime in TEXT_MIME_TYPES:
            content_blocks.append(
                {
                    "type": "text",
                    "text": decode_text(raw_bytes),
                }
            )

        elif mime in UNSUPPORTED_FILE_MIME_TYPES:
            file_encoded_content = base64.b64encode(raw_bytes).decode("utf-8")
            content_blocks.append(
                {
                    "type": "file",
                    "file": {
                        "file_data": f"data:{mime};base64,{file_encoded_content}",
                    },
                }
            )

        else:
            raise HTTPException(
                status_code=415,
                detail=f"暂不支持该文件类型：{mime}",
            )

    file_id = str(uuid.uuid4())
    file_store[file_id] = content_blocks

    return {"file_id": file_id}

@router.websocket("/ws")
async def agent_websocket(
    websocket: WebSocket,
) -> None:
    """
    接收前端命令，并向前端实时推送 Agent 运行事件。
    同一个接口地址 ≠ 同一条 WebSocket 连接,后端就会分别执行一份 agent_websocket() 函数实例,每个实例负责一个 WebSocket 连接，互相独立。
    """

    await websocket.accept()

    queue: EventQueue = asyncio.Queue()
    writer_task = asyncio.create_task(_websocket_writer(websocket, queue))

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
                await _put_control_event(
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
                await _put_control_event(
                    queue,
                    "run.failed",
                    session_name or "default",
                    "命令格式错误，必须包含有效的 session_name 字段。",
                )
                continue
            session_name = received_session_name

            # 当前连接同一时间只允许运行一个 Agent 任务。
            if active_task is not None and not active_task.done():
                await _put_control_event(
                    queue,
                    "run.failed",
                    received_session_name,
                    "当前已有任务正在运行，请先停止当前任务。",
                )
                continue

            if not isinstance(message, str) or not message.strip():
                await _put_control_event(
                    queue,
                    "run.failed",
                    received_session_name,
                    "命令格式错误，run.start 必须包含有效的 message 字段。",
                )
                continue


            # 先校验并组织本次任务输入内容。
            if file_id:
                if not isinstance(file_id, str) or file_id not in file_store:
                    await _put_control_event(
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
                    await _put_control_event(
                        queue,
                        "run.failed",
                        session_name,
                        "无法加载配置文件，请先完成 ZBot 配置。",
                    )
                    continue

                try:
                    service = create_agent_run_service(config)
                except AgentSetupError as exc:
                    await _put_control_event(
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
                    event_sink=_queue_event_sink(queue),
                )
            except Exception as exc:
                logger.exception("WebSocket Agent service 启动失败")
                await _put_control_event(
                    queue,
                    "run.failed",
                    session_name,
                    f"任务启动失败：{exc}",
                )
                await close_service()
                continue

            active_task = asyncio.create_task(
                _run_agent(
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
        await _put_control_event(
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


async def _run_agent(
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
            event_sink=_queue_event_sink(queue),
        )

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        logger.exception("WebSocket Agent run 失败")
        await _put_control_event(
            queue,
            "run.failed",
            session_name,
            f"任务失败：{exc}",
        )


async def _websocket_writer(
    websocket: WebSocket,
    queue: EventQueue,
) -> None:
    """持续从事件队列中读取事件，并发送给前端。"""

    while True:
        event = await queue.get()

        if event is None:
            return

        await websocket.send_json(event)


def _queue_event_sink(queue: EventQueue):
    """创建 Agent 事件接收函数，将运行事件写入发送队列。"""

    async def _sink(event: AgentEvent) -> None:
        await queue.put(event.to_dict())

    return _sink


async def _put_control_event(
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