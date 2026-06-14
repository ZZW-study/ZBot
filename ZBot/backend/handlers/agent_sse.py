"""Agent SSE 处理器。

事件翻译(业务事件 AgentEvent.type -> OpenAI Responses SSE envelope):
  · 注册表 _MAPPINGS 里显式声明的事件 = 已设计好的映射
  · envelope_type=None = 显式忽略,不推给前端(例如 run.started / run.closed /
    turn.completed / model.completed / tool.progress)
  · 注册表里查不到的 = 未映射,自动产 unmapped_event 错误事件(兜底,
    让"漏翻译"暴露而不是静默丢失)

加新事件类型 = 在 _MAPPINGS 加一行,不要碰 translate_event。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from loguru import logger

from ZBot.backend.handlers.agent_files import file_store
from ZBot.services.agent_run.agent_factory import AgentSetupError
from ZBot.services.agent_run.agent_run_service import (
    AgentEvent,
    create_agent_run_service,
)
from ZBot.services.agent_run.run_registry import RunRegistry, RunState, RunStatus
from ZBot.services.config.config import config_cache
from ZBot.services.agent_run.agent_run_service import AgentRunService
# ---------------------------------------------------------------------------
# 事件翻译:旧 AgentEvent -> 新 RunEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventMapping:
    """一条业务事件到 SSE envelope 的映射。

    envelope_type:
      · "event_msg"     → payload 里嵌 payload.type(应用层子事件)
      · "response_item" → payload 里嵌 payload.type(模型输出子项)
      · None            → 显式忽略,不发任何 SSE 事件
    sub_type:
      · payload.type 字段的值(例如 "task_started" / "function_call" / "error")
    transform:
      · (event, payload_in) → payload dict(不含 type 字段;type 字段由
        translate_event 在最后注入 envelope_type/sub_type)。返回 {} 表示
        该事件除了 type 之外没有别的字段。
    """

    envelope_type: str | None
    sub_type: str | None
    transform: Callable[[AgentEvent, dict[str, Any]], dict[str, Any]]


def _to_task_started(_: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    return {
        "turn_id": str(uuid.uuid4()),
        "started_at": time.time(),
        "model_context_window": int(p.get("model_context_window", 0)),
    }


def _to_task_complete(status: str) -> Callable[[AgentEvent, dict[str, Any]], dict[str, Any]]:
    def _t(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "turn_id": p.get("turn_id", ""),
            "status": status,
            "ended_at": time.time(),
            "final_content": event.message or str(p.get("final_content", "")),
        }

    return _t


def _to_run_failed(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": event.message or "智能体运行失败",
        "code": str(p.get("code", "run_failed")),
    }


def _to_message_delta(delta: bool) -> Callable[[AgentEvent, dict[str, Any]], dict[str, Any]]:
    def _t(event: AgentEvent, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": event.message or "",
            "delta": delta,
        }

    return _t


def _to_function_call(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_id": str(p.get("call_id", uuid.uuid4())),
        "name": event.agent_label or p.get("tool_name", "工具"),
        "arguments": json.dumps(p.get("input", {}), ensure_ascii=False),
    }


def _to_function_call_output(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_id": str(p.get("call_id", "")),
        "output": event.message or str(p.get("output", "")),
    }


def _to_function_call_output_error(event: AgentEvent, _: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_id": "",  # 失败时无 call_id 上下文
        "output": f"[错误] {event.message or '工具调用失败'}",
    }


def _to_cron_reminder(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": event.message or "",
        "job_id": str(p.get("job_id", "")),
        "job_name": str(p.get("job_name", "")),
    }


def _to_token_count(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_tokens": int(p.get("input_tokens", 0)),
        "output_tokens": int(p.get("output_tokens", 0)),
        "cached_tokens": int(p.get("cached_tokens", 0)),
    }


# 业务事件名 → SSE envelope 映射。envelope_type=None 表示"显式忽略"。
_MAPPINGS: dict[str, EventMapping] = {
    # ── 显式忽略:这些事件 SSE 流不需要推 ─────────────────────────
    "run.started":        EventMapping(None, None, lambda e, p: {}),
    "run.closed":         EventMapping(None, None, lambda e, p: {}),
    "turn.completed":     EventMapping(None, None, lambda e, p: {}),
    "model.completed":    EventMapping(None, None, lambda e, p: {}),
    "tool.progress":      EventMapping(None, None, lambda e, p: {}),
    # ── 合并的 turn/model 开始 ────────────────────────────────────
    "turn.started":       EventMapping("event_msg", "task_started", _to_task_started),
    "model.started":      EventMapping("event_msg", "task_started", _to_task_started),
    # ── 一次 run 的结束(成功/取消/失败) ──────────────────────────
    "run.completed":      EventMapping("event_msg", "task_complete", _to_task_complete("completed")),
    "run.cancelled":      EventMapping("event_msg", "task_complete", _to_task_complete("cancelled")),
    "run.failed":         EventMapping("event_msg", "error",         _to_run_failed),
    # ── 流式 assistant 文本 ───────────────────────────────────────
    "assistant.delta":    EventMapping("response_item", "message", _to_message_delta(True)),
    "agent.progress":     EventMapping("response_item", "message", _to_message_delta(True)),
    "assistant.completed": EventMapping("response_item", "message", _to_message_delta(False)),
    # ── 工具调用三态 ─────────────────────────────────────────────
    "tool.started":       EventMapping("response_item", "function_call",         _to_function_call),
    "tool.completed":     EventMapping("response_item", "function_call_output", _to_function_call_output),
    "tool.failed":        EventMapping("response_item", "function_call_output", _to_function_call_output_error),
    # ── 杂项 ─────────────────────────────────────────────────────
    "cron.reminder":      EventMapping("event_msg", "cron_reminder", _to_cron_reminder),
    "token_count":        EventMapping("event_msg", "token_count",   _to_token_count),
}


def translate_event(event: AgentEvent, run_id: str) -> dict[str, Any] | None:
    """把一个 AgentEvent 翻译成 OpenAI Responses SSE envelope。

    返回:
      · dict:包成 SSE 事件推给前端
      · None:忽略(由注册表 envelope_type=None 触发)
    兜底:注册表里查不到的事件类型 → 自动产 unmapped_event 错误事件,
          让"漏翻译"在测试里能被发现,而不是静默丢。
    """
    mapping = _MAPPINGS.get(event.type)
    if mapping is None:
        return {
            "type": "event_msg",
            "payload": {
                "type": "error",
                "message": f"未映射事件类型: {event.type}",
                "code": "unmapped_event",
            },
        }
    if mapping.envelope_type is None:
        return None
    payload_fields = mapping.transform(event, event.payload or {})
    return {
        "type": mapping.envelope_type,
        "payload": {"type": mapping.sub_type, **payload_fields},
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
) -> AsyncIterator[str]:
    """
    SSE事件流消费者（只负责“读队列 + 转 SSE + 推前端”）

    关键结构：
    RunWorker（生产者） ---> event_queue ---> SSE（消费者）
    """

    seq = 0

    def _next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    # =========================
    # 1. 立即推 session 初始化信息
    # =========================
    yield format_sse(build_session_meta(state), _next_seq())

    # =========================
    # 2. 等待 run 从 QUEUED 进入运行状态
    #    （说明 worker 已经开始干活）
    # =========================
    while state.status == RunStatus.QUEUED:
        await asyncio.sleep(0.05)

    # =========================
    # 3. 主循环：不断从 event_queue 消费事件
    # =========================
    try:
        while True:
            try:
                # 从队列取事件（阻塞点）
                # RunWorker.put(event) → 这里 get()
                raw = await asyncio.wait_for(
                    state.event_queue.get(),
                    timeout=10.0
                )

            except asyncio.TimeoutError:
                # 没事件 → 说明“暂时无产出”
                # SSE keep-alive（防止连接断）
                yield ": heartbeat\n\n"
                continue

            # =========================
            # 4. 结束信号
            # =========================
            # RunWorker 主动 put(None) 表示结束
            if raw is None:
                break

            # =========================
            # 5. 解析事件
            # =========================
            try:
                evt = AgentEvent(**raw) if isinstance(raw, dict) else raw
            except Exception:
                evt = None

            if evt is None:
                continue

            # =========================
            # 6. 事件翻译（内部事件 -> SSE协议事件）
            # =========================
            translated = translate_event(evt, state.run_id)

            # 7. 推送给前端
            if translated is not None:
                yield format_sse(translated, _next_seq())

            # =========================
            # 8. run结束判断（关键状态控制点）
            # =========================
            if state.status in {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED
            }:
                # drain：把队列里残留事件一次性清空
                # 避免 worker 已结束但事件还堆着
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

    # =========================
    # 9. 客户端断开连接
    # =========================
    except asyncio.CancelledError:
        # 前端关闭 SSE / 网络断开
        logger.info("SSE 客户端断开, run_id={}", state.run_id)
        raise

    # =========================
    # 10. 运行异常
    # =========================
    except Exception as exc:
        logger.exception("SSE 流异常, run_id={}", state.run_id)

        yield format_sse(
            {
                "type": "event_msg",
                "payload": {
                    "type": "error",
                    "message": str(exc),
                    "code": "stream_error",
                },
            },
            _next_seq(),
        )

    # =========================
    # 11. 流结束信号
    # =========================
    finally:
        # ⚠️关键设计点说明：
        # 不在这里做 unregister
        # 因为：
        #   - SSE断开 ≠ run结束
        #   - worker可能还在写 event_queue
        #
        # 正确归属：
        #   RunWorker负责生命周期管理（结束后再 unregister）
        yield format_done(_next_seq())


# ---------------------------------------------------------------------------
# Run worker:在后台跑 AgentRunService.ask(),把事件灌到 state.event_queue
# ---------------------------------------------------------------------------

async def run_worker(
    state: RunState,
    runs: RunRegistry,
    message: str | list[dict[str, Any]],
    *,
    file_id: str | None = None,
) -> None:
    """
    后台任务：驱动agent的ask()循环，并将事件推送至服务器发送事件队列。
    """
    config = config_cache.get()
    if config is None:
        # config 未初始化，则失败，往事件队列推送失败事件
        await runs.mark_ended(state.run_id, RunStatus.FAILED, "no config")
        await state.event_queue.put(
            AgentEvent.control_event(
                "run.failed",
                "ZBot 尚未配置",
            )
        )
        return

    try:
        # 每个协程有自己的 AgentRunService,此时各自配置已经好了，然后心跳狗也开启了，之后的每个动作，都要上报给心跳狗
        service: AgentRunService = create_agent_run_service(config)
    except AgentSetupError as exc:
        await runs.mark_ended(state.run_id, RunStatus.FAILED, exc.message)
        await state.event_queue.put(
            AgentEvent.control_event(
                "run.failed",
                exc.message,
                payload={"code": exc.code},
            )
        )
        return

    await runs.mark_started(state.run_id)

    # 进度回调函数，传入事件类，然后就是1.不断的把状态放入到事件队列，2.给心跳狗更新
    async def sink(event: AgentEvent) -> None:
        try:
            await state.event_queue.put(event.to_dict())
            service.bundle.activitytracker.touch(description=event.message)
        except Exception:
            logger.exception("运行工作推送数据至接收端失败")



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
        """执行单次 ask 调用。正常完成返回 True,被取消或抛异常则返回 False。"""
        try:
            # 最终如果是由心跳狗取消的话，会从await那里一直往上层抛出CancelError,其他的设计都是一直向上层raise，只要是取消错误，都会回到这里来
            # 进行最后的归档处理
            # 在 Python async / try-except 里：
            #✔ 如果下层 return（不 raise）
            # 上层 不会再收到异常
            # 因为：
            # 异常 = 已被处理掉
            # 控制流 = 正常返回
            # ✔ 如果下层 raise
            # 上层才能继续 catch 或传播
            await service.ask(
                prompt,
                state.session_name,
                event_sink=sink,   # 进度回调
            )
            return True
        except asyncio.CancelledError:
            await runs.mark_ended(state.run_id, RunStatus.CANCELLED, None)
            await sink(
                AgentEvent(
                    type="run.cancelled",
                    message="运行已取消",
                )
            )
            await _finalize()
            return False
        except Exception as exc:
            logger.exception("run_worker error")
            await runs.mark_ended(state.run_id, RunStatus.FAILED, str(exc))
            await sink(
                AgentEvent(
                    type="run.failed",
                    message=f"运行失败: {exc}",
                )
            )
            await _finalize()
            return False

    # 解析 file_id → 放入完整多模态消息
    if file_id:
        if file_id not in file_store:
            await runs.mark_ended(state.run_id, RunStatus.FAILED, "文件未找到")
            await state.event_queue.put(
                AgentEvent.control_event(
                    "run.failed",
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

    # 这里开始调用，因为有await到这里就卡住，执行里面的。
    if not await _ask_once(message_blocks):
        # 不管 _ask_once 成功与否,unregister 都要发生,否则 run 状态会永久驻留。
        # 走 _finalize 之前先 mark_ended(若 _ask_once 内部没成功标记过)。
        # 关闭 event_queue 让 SSE generator 的 await get() 拿到 None 并退出。
        try:
            state.event_queue.put_nowait(None)
        except Exception:
            pass
        await runs.unregister(state.run_id)
        return

    await runs.mark_ended(state.run_id, RunStatus.COMPLETED, None)
    await _finalize()
    # worker 收尾,关闭事件队列并 unregister,让 SSE generator 退出。
    try:
        state.event_queue.put_nowait(None)
    except Exception:
        pass
    await runs.unregister(state.run_id)
