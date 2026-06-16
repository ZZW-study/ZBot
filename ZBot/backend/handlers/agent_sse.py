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
    # ZBot 改: 优先使用 agent_run_service 分配的稳定 turn_id, 否则回退到本地 uuid。
    # 之前每次都生成新 uuid, 导致 task_started 的 turnId 与 task_complete 的 turnId
    # 不一致, 前端 setTurns 的 t.turnId !== turnId 永远为 true, 消息项写不进去,
    # 最终结果不显示。
    return {
        "turn_id": str(p.get("turn_id") or uuid.uuid4()),
        "started_at": time.time(),
        "model_context_window": int(p.get("model_context_window", 0)),
    }


def _to_task_complete(status: str) -> Callable[[AgentEvent, dict[str, Any]], dict[str, Any]]:
    def _t(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "turn_id": p.get("turn_id", ""),
            "status": status,
            "ended_at": time.time(),
            # H33 fix: prefer the real final_content from the agent over the
            # business label "task complete" / "task cancelled". When the agent
            # returns a real LLM response, it is in payload.final_content;
            # event.message is just a short status string used for run.completed
            # UX logs.
            "final_content": p.get("final_content") or event.message,
        }

    return _t


def _to_run_failed(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    # ZBot 改: 透传 turn_id, 前端用它在 setTurns 里找到对应的 turn 来 mark failed。
    # 之前 turn_id 字段缺失, run.failed 事件流到前端时, 任务列表更新不到对应 turn。
    return {
        "turn_id": p.get("turn_id", ""),
        "message": event.message or "智能体运行失败",
        "code": str(p.get("code", "run_failed")),
    }


def _to_message_delta(delta: bool) -> Callable[[AgentEvent, dict[str, Any]], dict[str, Any]]:
    def _t(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
        # ZBot 改: 透传 turn_id, 前端按它路由 deltas 到正确的 turn, 避免依赖
        # turnsRef.current[len-1]?.turnId 兜底导致的跨 turn 错位。
        return {
            "turn_id": p.get("turn_id", ""),
            "role": "assistant",
            "content": event.message or "",
            "delta": delta,
        }

    return _t


def _to_function_call(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    # ZBot 改: 工具名优先取 p["tool_name"] / p["name"] (真实工具名), 不要再 fallback
    # 到 event.agent_label —— agent_label 是 agent 自己的名字 (主agent / 子agent<id>),
    # 把它当工具名会导致前端 4 个工具都显示成 "主agent" / "子agent<id>"。
    tool_name = (
        p.get("tool_name")
        or p.get("name")
        or (event.agent_label if event.agent_label and not str(event.agent_label).startswith(("主", "子")) else None)
        or "工具"
    )
    return {
        "turn_id": p.get("turn_id", ""),
        "call_id": str(p.get("call_id") or p.get("tool_call_id") or uuid.uuid4()),
        "name": tool_name,
        "arguments": p.get("arguments") or json.dumps(p.get("input", {}), ensure_ascii=False),
    }


def _to_function_call_output(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    # ZBot 改: call_id 兼容两种 key: 后端 base_agent 写的是 tool_call_id (来自 LLM
    # provider 的 tool_call.id), 而 _to_function_call 写入的也是同一个 tool_call_id。
    # 之前 _to_function_call_output 只读 p["call_id"], 永远拿到空字符串, 匹配不上
    # 前端 open tool_call 的 callId, 导致 4 个工具永远卡在 "运行中"。
    return {
        "turn_id": p.get("turn_id", ""),
        "call_id": str(p.get("call_id") or p.get("tool_call_id") or ""),
        "status": "done",  # ZBot 改: 与 _to_function_call_output_error 对齐, 方便前端判断
        "output": event.message or str(p.get("output", "")),
    }


def _to_function_call_output_error(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    # ZBot 改: 之前 call_id 永远是空字符串, 前端 upsertItem 匹配不到, 失败的
    # 工具永远卡在 "运行中"。现在透传 call_id / tool_call_id, 并加 status='failed'
    # 让前端能区分 done vs failed。
    return {
        "turn_id": p.get("turn_id", ""),
        "call_id": str(p.get("call_id") or p.get("tool_call_id") or ""),
        "status": "failed",
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


def _to_status(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    """ZBot 改:LiveStatus 用的"思考/整理结果"状态事件。"""
    return {
        "text": event.message or "",
        "phase": str(p.get("phase", "thinking")),
    }


def _to_tool_hint(event: AgentEvent, p: dict[str, Any]) -> dict[str, Any]:
    """ZBot 改:LiveStatus 用的"调用工具"状态事件。"""
    return {
        "text": event.message or "",
        "tool_name": str(p.get("tool_name") or event.agent_label or ""),
    }




# 业务事件名 → SSE envelope 映射。envelope_type=None 表示"显式忽略"。
_MAPPINGS: dict[str, EventMapping] = {
    # ── 显式忽略:这些事件 SSE 流不需要推 ─────────────────────────
    "run.started":        EventMapping(None, None, lambda e, p: {}),
    "run.closed":         EventMapping(None, None, lambda e, p: {}),
    "turn.completed":     EventMapping(None, None, lambda e, p: {}),
    "model.completed":    EventMapping(None, None, lambda e, p: {}),
    # ZBot 改:LiveStatus 状态事件 — agent_run_service._on_progress 会同时推 status /
    # tool_hint 与原本的 model.started / tool.progress,这里给前者加映射。
    "status":             EventMapping("event_msg", "status",    _to_status),
    "tool_hint":          EventMapping("event_msg", "tool_hint", _to_tool_hint),

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
            # 从队列取事件（阻塞点）
            # RunWorker.put(event) → 这里 get()
            # 软超时:取消与硬截断解耦。
            # 这里改成纯 await,不再用 wait_for 做 10s 硬截断。
            # - 慢思考(LLM 思考 30s+)不再被错误地当成"心跳帧";
            # - 真卡死时由 ActivityWatchdog(默认 30 min)取消 run_worker,
            #   worker 在 _ask_once 捕获 CancelledError 后会 mark_ended + sink("run.cancelled")
            #   并由外层 put_nowait(None) 让这里自然拿到 None 后 break。
            raw = await state.event_queue.get()

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
    service: AgentRunService | None = None,
) -> None:
    # ZBot 改: 接受外部传入的 service (从 app.state 共享), 否则走兼容路径 (新建)
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

    if service is None:
        # ZBot 改: 兼容路径 - 不传 service 时仍按 per-run 创建 (主要用于测试)
        try:
            service = create_agent_run_service(config)
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
