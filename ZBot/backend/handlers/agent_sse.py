"""Agent SSE 处理器。

事件类型映射(旧 -> 新):
  run.started           -> (忽略,session_meta 已经覆盖)
  turn.started          -> event_msg / task_started
  turn.completed        -> (忽略,task_complete 覆盖)
  run.completed         -> event_msg / task_complete {status: completed}
  run.cancelled         -> event_msg / task_complete {status: cancelled}
  run.failed            -> event_msg / task_complete {status: failed}
  run.closed            -> (忽略,清理事件)
  model.started         -> event_msg / task_started
  model.completed       -> (忽略)
  assistant.delta       -> response_item / message {delta: true}
  assistant.completed   -> response_item / message {delta: false}
  tool.started          -> response_item / function_call
  tool.completed        -> response_item / function_call_output
  tool.failed           -> response_item / function_call_output (error)
  tool.progress         -> (暂不映射)
  agent.progress        -> response_item / message {delta: true}
  cron.reminder         -> event_msg / cron_reminder
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator

from loguru import logger

from ZBot.backend.handlers.agent_files import file_store
from ZBot.services.agent_run.agent_factory import AgentSetupError
from ZBot.services.agent_run.agent_run_service import (
    AgentEvent,
    create_agent_run_service,
)
from ZBot.services.agent_run.follow_up_queue import FollowUpQueue
from ZBot.services.agent_run.run_registry import RunRegistry, RunState, RunStatus
from ZBot.services.config.config import config_cache

# ---------------------------------------------------------------------------
# 事件翻译:旧 AgentEvent -> 新 RunEvent
# ---------------------------------------------------------------------------

def translate_event(event: AgentEvent, run_id: str) -> dict[str, Any] | None:
    et = event.type
    payload_in = event.payload or {}

    if et == "run.started":
        return None
    if et == "run.closed":
        return None
    if et == "turn.completed":
        return None

    if et in ("turn.started", "model.started"):
        return {
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": str(uuid.uuid4()),
                "started_at": time.time(),
                "model_context_window": int(payload_in.get("model_context_window", 0)),
                "collaboration_mode_kind": "default",
            },
        }

    if et == "run.completed":
        return {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": payload_in.get("turn_id", ""),
                "status": "completed",
                "ended_at": time.time(),
                "final_content": event.message or str(payload_in.get("final_content", "")),
            },
        }
    if et == "run.cancelled":
        return {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": payload_in.get("turn_id", ""),
                "status": "cancelled",
                "ended_at": time.time(),
                "final_content": "",
            },
        }
    if et == "run.failed":
        return {
            "type": "event_msg",
            "payload": {
                "type": "error",
                "message": event.message or "agent run failed",
                "code": str(payload_in.get("code", "run_failed")),
            },
        }

    if et in ("assistant.delta", "agent.progress"):
        return {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": event.message or "",
                "delta": True,
            },
        }
    if et == "assistant.completed":
        return {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": event.message or "",
                "delta": False,
            },
        }

    if et == "tool.started":
        return {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": str(payload_in.get("call_id", uuid.uuid4())),
                "name": event.agent_label or payload_in.get("tool_name", "tool"),
                "arguments": json.dumps(payload_in.get("input", {}), ensure_ascii=False),
            },
        }
    if et == "tool.completed":
        return {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": str(payload_in.get("call_id", "")),
                "output": event.message or str(payload_in.get("output", "")),
            },
        }
    if et == "tool.failed":
        return {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": str(payload_in.get("call_id", "")),
                "output": f"[error] {event.message or 'tool failed'}",
            },
        }

    if et == "cron.reminder":
        return {
            "type": "event_msg",
            "payload": {
                "type": "cron_reminder",
                "message": event.message or "",
                "job_id": str(payload_in.get("job_id", "")),
                "job_name": str(payload_in.get("job_name", "")),
            },
        }

    if et == "token_count":
        return {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "input_tokens": int(payload_in.get("input_tokens", 0)),
                "output_tokens": int(payload_in.get("output_tokens", 0)),
                "cached_tokens": int(payload_in.get("cached_tokens", 0)),
            },
        }

    return {
        "type": "event_msg",
        "payload": {
            "type": "error",
            "message": f"\u672a\u6620\u5c04\u4e8b\u4ef6\u7c7b\u578b: {et}",
            "code": "unmapped_event",
        },
    }


# ---------------------------------------------------------------------------
# Session meta(流的第一个事件)
# ---------------------------------------------------------------------------

def build_session_meta(state: RunState) -> dict[str, Any]:
    return {
        "type": "session_meta",
        "payload": {
            "id": state.run_id,
            "session_name": state.session_name,
            "cwd": "",
            "model_provider": "",
            "cli_version": "0.1.0",
            "source": "zbot-web",
        },
    }


# ---------------------------------------------------------------------------
# SSE 格式化
# ---------------------------------------------------------------------------

_DONE_PAYLOAD = json.dumps({"type": "done", "payload": {}}, ensure_ascii=False)


def format_sse(event: dict[str, Any], seq: int) -> str:
    event_type = event.get("type", "message")
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"id: {seq}\nevent: {event_type}\ndata: {data}\n\n"


def format_done(seq: int) -> str:
    return f"id: {seq}\nevent: done\ndata: {_DONE_PAYLOAD}\n\n"


# ---------------------------------------------------------------------------
# 主 SSE 流生成器
# ---------------------------------------------------------------------------

async def stream_run_events(
    state: RunState,
    registry: RunRegistry,
    follow_up_queue: FollowUpQueue | None = None,
) -> AsyncIterator[str]:
    """从 state.event_queue 取事件,SSE 推送给客户端。

    流的生命周期:
    1. 立即推 session_meta
    2. 循环读队列,翻译事件,格式化输出
    3. run 状态变为 completed/failed/cancelled 时推 done,然后退出
    """
    seq = 0

    def _next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    yield format_sse(build_session_meta(state), _next_seq())

    while state.status == RunStatus.QUEUED:
        await asyncio.sleep(0.05)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(state.event_queue.get(), timeout=10.0)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue

            if raw is None:
                break

            try:
                evt = AgentEvent(**raw) if isinstance(raw, dict) else raw
            except Exception:
                evt = None

            if evt is None:
                continue

            translated = translate_event(evt, state.run_id)
            if translated is not None:
                yield format_sse(translated, _next_seq())

            if state.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                # drain 剩余事件
                while not state.event_queue.empty():
                    extra = state.event_queue.get_nowait()
                    if extra is None:
                        continue
                    try:
                        e = AgentEvent(**extra) if isinstance(extra, dict) else extra
                    except Exception:
                        continue
                    t = translate_event(e, state.run_id)
                    if t is not None:
                        yield format_sse(t, _next_seq())
                break
    except asyncio.CancelledError:
        logger.info("SSE 客户端断开, run_id={}", state.run_id)
        raise
    except Exception as exc:
        logger.exception("SSE 流异常, run_id={}", state.run_id)
        yield format_sse(
            {
                "type": "event_msg",
                "payload": {"type": "error", "message": str(exc), "code": "stream_error"},
            },
            _next_seq(),
        )
    finally:
        # H8 修复:不再在 SSE generator 的 finally 里 unregister(run worker 也可能
        # 还在写 event_queue,而且 SSE 客户端断连不等于 run 结束)。
        # 改由 run_worker 自己在所有 _ask_once 跑完后调 registry.unregister,
        # 这样 registry 的生命周期严格跟随 run,而不是跟 SSE 客户端。
        yield format_done(_next_seq())


# ---------------------------------------------------------------------------
# Run worker:在后台跑 AgentRunService.ask(),把事件灌到 state.event_queue
# ---------------------------------------------------------------------------

async def run_worker(
    state: RunState,
    registry: RunRegistry,
    message: str | list[dict[str, Any]],
    follow_up_queue: FollowUpQueue | None = None,
    *,
    file_id: str | None = None,
) -> None:
    """
    Background task: drive the agent.ask() loop and feed events into
    the SSE queue. After the first turn completes, drain any queued
    follow-ups (each becomes another turn on the same run).
    """
    config = config_cache.get()
    if config is None:
        await registry.mark_ended(state.run_id, RunStatus.FAILED, "no config")
        await state.event_queue.put(
            AgentEvent.control_event(
                "run.failed",
                state.session_name,
                "ZBot not configured",
            )
        )
        return

    try:
        service = create_agent_run_service(config)
    except AgentSetupError as exc:
        await registry.mark_ended(state.run_id, RunStatus.FAILED, exc.message)
        await state.event_queue.put(
            AgentEvent.control_event(
                "run.failed",
                state.session_name,
                exc.message,
                payload={"code": exc.code},
            )
        )
        return

    await registry.mark_started(state.run_id)

    async def sink(event: AgentEvent) -> None:
        try:
            await state.event_queue.put(event.to_dict())
        except Exception:
            logger.exception("run_worker sink push failed")

    async def _finalize() -> None:
        """关闭 service,触发 cron.stop / close_mcp / 记忆刷盘等副作用。

        必须在 run 真正结束(正常 / 取消 / 失败)的每个出口都调一次,
        否则 memory 永远不落盘、cron timer 泄漏、MCP 子进程句柄残留。
        """
        try:
            await service.close(state.session_name)
        except Exception:
            logger.exception("service.close failed, run_id={}", state.run_id)

    async def _ask_once(prompt) -> bool:
        """Run a single ask. Returns True if it completed normally,
        False if cancelled or raised."""
        try:
            await service.ask(
                prompt,
                state.session_name,
                event_sink=sink,
            )
            return True
        except asyncio.CancelledError:
            await registry.mark_ended(state.run_id, RunStatus.CANCELLED, None)
            await sink(
                AgentEvent(
                    type="run.cancelled",
                    session_name=state.session_name,
                    message="run cancelled",
                )
            )
            await _finalize()
            return False
        except Exception as exc:
            logger.exception("run_worker error")
            await registry.mark_ended(state.run_id, RunStatus.FAILED, str(exc))
            await sink(
                AgentEvent(
                    type="run.failed",
                    session_name=state.session_name,
                    message=f"run failed: {exc}",
                )
            )
            await _finalize()
            return False

    # 解析 file_id → message content blocks
    if file_id:
        if file_id not in file_store:
            await registry.mark_ended(state.run_id, RunStatus.FAILED, "file_not_found")
            await state.event_queue.put(
                AgentEvent.control_event(
                    "run.failed",
                    state.session_name,
                    "文件不存在，请重新上传文件。",
                )
            )
            return
        message_blocks: str | list[dict[str, Any]] = [
            {"type": "text", "text": message},
            *file_store[file_id],
        ]
    else:
        message_blocks = message

    if not await _ask_once(message_blocks):
        # H8: 不管 _ask_once 成功与否,unregister 都要发生,否则 run 状态会永久驻留。
        # 走 _finalize 之前先 mark_ended(若 _ask_once 内部没成功标记过)。
        # 关闭 event_queue 让 SSE generator 的 await get() 拿到 None 并退出。
        try:
            state.event_queue.put_nowait(None)
        except Exception:
            pass
        await registry.unregister(state.run_id)
        return

    # 排空已排队的 follow-up:每条入队消息成为同一 run 的下一 turn
    # 在 cancel/failure/队列空时停止。
    if follow_up_queue is not None:
        while True:
            fu = await follow_up_queue.dequeue(state.session_name)
            if fu is None:
                break
            if not await _ask_once(fu.message):
                try:
                    state.event_queue.put_nowait(None)
                except Exception:
                    pass
                await registry.unregister(state.run_id)
                return

    await registry.mark_ended(state.run_id, RunStatus.COMPLETED, None)
    await _finalize()
    # H8: worker 收尾,关闭事件队列并 unregister,让 SSE generator 退出。
    try:
        state.event_queue.put_nowait(None)
    except Exception:
        pass
    await registry.unregister(state.run_id)


