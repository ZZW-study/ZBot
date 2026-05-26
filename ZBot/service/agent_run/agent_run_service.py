"""Agent run 生命周期服务。

CLI、WebSocket 后端等入口都通过这里驱动一次 Agent 运行；展示层只消费
结构化事件，不直接耦合 Agent 内部进度回调。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from loguru import logger

from ZBot.cron.types import CronJob

if TYPE_CHECKING:
    from ZBot.service.agent_run.agent_factory import AgentBundle

BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class AgentEvent:
    """发送给 CLI/前端的结构化 Agent 事件。"""

    type: str
    run_id: str
    session_name: str
    message: str = ""
    agent_label: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(BEIJING_TZ).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "type": self.type,
            "run_id": self.run_id,
            "session_name": self.session_name,
            "message": self.message,
            "agent_label": self.agent_label,
            "payload": self.payload,
            "created_at": self.created_at,
        }

    @classmethod
    def control_event(
        cls,
        event_type: str,
        session_name: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造控制事件 dict（不依赖 service 实例）。"""
        return cls(
            type=event_type,
            run_id="control",
            session_name=session_name,
            message=message,
            payload=payload or {},
        ).to_dict()


EventSink = Callable[[AgentEvent], Awaitable[None]]


class AgentRunService:
    """统一管理一次 Agent 会话的启动、单轮对话、取消和清理。"""

    def __init__(
        self,
        bundle: "AgentBundle",
        *,
        run_id: str | None = None,
    ) -> None:
        """初始化 run service。"""
        self.bundle = bundle
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._started = False
        self._closed = False
        self._event_sink: EventSink | None = None
        self._session_name = "default"

    async def start(
        self,
        session_name: str,
        *,
        event_sink: EventSink,
    ) -> None:
        """启动会话级资源；交互会话/WebSocket 连接期间只调用一次。"""
        if self._closed:
            raise RuntimeError("AgentRunService 已关闭，不能再次启动")
        if self._started:
            self._event_sink = event_sink
            self._session_name = session_name
            self.bundle.cron.on_job = self.cron_event_handler(event_sink, session_name)
            return

        self._event_sink = event_sink
        self._session_name = session_name
        self.bundle.cron.on_job = self.cron_event_handler(event_sink, session_name)
        await self.bundle.cron.start()
        self._started = True
        await event_sink(self._event("run.started", session_name, "会话已启动"))

    async def ask(
        self,
        message: Any,
        session_name: str,
        *,
        event_sink: EventSink,
    ) -> str:
        """执行一轮用户消息；资源清理由 close() 在会话结束时负责。"""
        if not self._started:
            await self.start(session_name, event_sink=event_sink)

        self._event_sink = event_sink
        self._session_name = session_name
        await event_sink(self._event("turn.started", session_name, "开始处理本轮消息"))
        try:
            final_content = await self.bundle.agent.process_message(
                message,
                session_name,
                on_progress=self._progress_sink(session_name, event_sink),
            )
            await event_sink(
                self._event(
                    "turn.completed",
                    session_name,
                    "本轮消息处理完成",
                    payload={"final_content": final_content},
                )
            )
            await event_sink(
                self._event(
                    "run.completed",
                    session_name,
                    "任务完成",
                    payload={"final_content": final_content},
                )
            )
            return final_content
        except asyncio.CancelledError:
            await event_sink(self._event("run.cancelled", session_name, "任务已取消"))
            raise
        except Exception as exc:
            logger.exception("Agent run 执行失败")
            await event_sink(
                self._event(
                    "run.failed",
                    session_name,
                    f"任务失败：{exc}",
                    payload={"error": str(exc)},
                )
            )
            return f"任务失败：{exc}"

    async def close(self, session_name: str) -> None:
        """关闭会话级资源并执行会话收尾；该方法可重复调用。"""
        if self._closed:
            return

        self._closed = True
        self.bundle.cron.stop()
        try:
            await self.bundle.agent.close_mcp()
            await self.bundle.agent.consolidate_all_session_memory(session_name=session_name)
            await self.bundle.agent.consolidate_daily_memory(session_name=session_name)
            try:
                await self.bundle.agent.review_skills(session_name=session_name)
            except Exception:
                logger.exception("技能进化回顾失败")
        except Exception:
            logger.exception("Agent 会话清理失败")
        finally:
            self._started = False
            if self._event_sink is not None:
                await self._event_sink(self._event("run.closed", session_name, "会话资源已清理"))

    def cron_event_handler(self, event_sink: EventSink, session_name: str = "default"):
        """创建 cron 到期回调，把提醒转换为 AgentEvent。"""

        async def _on_cron_job(job: CronJob) -> None:
            """把定时任务提醒转发为事件。"""
            await event_sink(
                self._event(
                    "cron.reminder",
                    session_name,
                    job.message,
                    payload={"job_id": job.id, "job_name": job.name},
                )
            )

        return _on_cron_job

    def _progress_sink(
        self,
        session_name: str,
        event_sink: EventSink,
    ) -> Callable[..., Awaitable[None]]:
        """把 BaseAgent 的字符串进度回调转换为结构化事件。"""

        async def _on_progress(
            content: str,
            *,
            tool_hint: bool = False,
            agent_label: str | None = None,
            **kwargs: Any,
        ) -> None:
            """接收 Agent 内部进度并发送事件。"""
            event_type = str(kwargs.pop("event_type", "") or ("tool.progress" if tool_hint else "agent.progress"))
            await event_sink(
                self._event(
                    event_type,
                    session_name,
                    content,
                    agent_label=agent_label,
                    payload=kwargs,
                )
            )

        return _on_progress

    def _event(
        self,
        event_type: str,
        session_name: str,
        message: str = "",
        *,
        agent_label: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        """构造统一事件对象。"""
        return AgentEvent(
            type=event_type,
            run_id=self.run_id,
            session_name=session_name,
            message=message,
            agent_label=agent_label,
            payload=payload or {},
        )
