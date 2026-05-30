"""Agent WebSocket harness 路由。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from loguru import logger
from ZBot.config.schema import Config
from ZBot.service.agent_run.agent_factory import AgentSetupError
from ZBot.service.agent_run.agent_run_service import AgentEvent, AgentRunService
from ZBot.service.agent_run.agent_runner import create_agent_run_service
from ZBot.service.config_service import config_cache
from ZBot.session.manager import Session, SessionManager

router = APIRouter(tags=["agent"])


class SessionCreateRequest(BaseModel):
    name: str


class SessionRenameRequest(BaseModel):
    name: str


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


@router.get("/api/sessions")
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
@router.get("/api/sessions/{session_name}")
async def get_session_detail(session_name: str):
    config = config_cache.get()
    if config is None:
        return {"ok": False, "error": "not configured"}

    manager = SessionManager(config.workspace_path)
    session, _ = await manager.get_or_create(session_name)
    return _session_detail(session)


@router.post("/api/sessions")
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


@router.put("/api/sessions/{session_name}")
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


@router.delete("/api/sessions/{session_name}")
async def delete_session(session_name: str):
    """删除指定会话。"""
    config = config_cache.get()
    if config is None:
        return {"ok": False, "error": "未配置"}

    workspace = config.workspace_path
    manager = SessionManager(workspace)
    deleted = await manager.delete(session_name)
    return {"ok": deleted}



@router.websocket("/api/agent/ws")
async def agent_websocket(websocket: WebSocket) -> None:
    """Agent WebSocket 通道：接收控制命令，推送结构化运行事件。"""
    await websocket.accept()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    active_task: asyncio.Task[None] | None = None
    service: AgentRunService | None = None
    current_session_name = "default"
    writer_task = asyncio.create_task(_websocket_writer(websocket, queue))

    try:
        while True:
            command = await websocket.receive_json()
            command_type = command.get("type")

            if command_type == "run.start":
                if active_task and not active_task.done():
                    await queue.put(AgentEvent.control_event("run.failed", "default", "已有任务正在运行，请先停止当前任务。"))
                    continue

                message = str(command.get("message") or "").strip()
                session_name = str(command.get("session_name") or "default")
                current_session_name = session_name
                if not message:
                    await queue.put(AgentEvent.control_event("run.failed", session_name, "消息不能为空。"))
                    continue

                if service is None:
                    config = config_cache.get()
                    if config is None:
                        await queue.put(AgentEvent.control_event("run.failed", session_name, "无法加载配置文件，请先完成 ZBot 配置。"))
                        continue
                    try:
                        service = create_agent_run_service(config)
                    except AgentSetupError as exc:
                        await queue.put(AgentEvent.control_event("run.failed", session_name, exc.message, payload={"code": exc.code}))
                        continue
                    await service.start(session_name, event_sink=_queue_event_sink(queue))

                active_task = asyncio.create_task(_run_agent(service, message, session_name, queue))
                continue

            if command_type == "run.cancel":
                if active_task and not active_task.done():
                    active_task.cancel()
                    await asyncio.gather(active_task, return_exceptions=True)
                    active_task = None
                if service is not None:
                    await service.close(current_session_name)
                    service = None
                continue

            await queue.put(AgentEvent.control_event("run.failed", "default", f"不支持的命令类型：{command_type}"))
    except WebSocketDisconnect:
        if active_task and not active_task.done():
            active_task.cancel()
    finally:
        if active_task and not active_task.done():
            active_task.cancel()
            await asyncio.gather(active_task, return_exceptions=True)
        if service is not None:
            await service.close(current_session_name)
        await queue.put(None)
        await asyncio.gather(writer_task, return_exceptions=True)


async def _run_agent(
    service: AgentRunService,
    message: str,
    session_name: str,
    queue: asyncio.Queue[dict[str, Any] | None],
) -> None:
    """在当前 WebSocket 会话级 service 中执行一轮 Agent 对话。"""
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
        await queue.put(AgentEvent.control_event("run.failed", session_name, f"任务失败：{exc}"))


async def _websocket_writer(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any] | None],
) -> None:
    """把事件队列写入 WebSocket。"""
    while True:
        event = await queue.get()
        if event is None:
            return
        await websocket.send_json(event)


def _queue_event_sink(queue: asyncio.Queue[dict[str, Any] | None]):
    """创建 service event sink，把 AgentEvent 写入队列。"""

    async def _sink(event: AgentEvent) -> None:
        """接收 AgentEvent 并入队。"""
        await queue.put(event.to_dict())

    return _sink
