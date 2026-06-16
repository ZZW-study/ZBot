"""Agent run 生命周期服务。

CLI、SSE 后端等入口都通过这里驱动一次 Agent 运行；展示层只消费
结构化事件，不直接耦合 Agent 内部进度回调。

────────────────────────────────────────────────────────────────────────
职责边界(本文件 vs run_registry.py)
────────────────────────────────────────────────────────────────────────
本文件管的是"执行和事件载荷":
  · AgentEvent      — 一次 agent 内部动作的结构化描述(@dataclass 载荷)
  · EventSink       — 任何能消费 AgentEvent 的回调签名
  · AgentRunService — start / ask / close 三个生命周期方法,以及
                      turn_id 注入、cron 回调、进度转事件等内部组装

run_registry.py 管的是"容器和句柄":
  · RunState        — 一次 run 的 task + event_queue + 状态
  · RunRegistry     — run_id → RunState 的多路复用路由表


所以"两个文件都跟事件沾边"不是重复:
  · AgentEvent = 事件本身(数据)
  · event_queue = 事件流过的通道(管道)
"""

from __future__ import annotations

import asyncio
import uuid   # 生成一个唯一的id字符串，可以用来标识，每次使用都不一样
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from ZBot.cron.types import CronJob

if TYPE_CHECKING:
    from ZBot.services.agent_run.agent_factory import AgentBundle

@dataclass(slots=True)
class AgentEvent:
    """发送给 CLI/前端的结构化 Agent 事件。

    这是"事件本身"(载荷),不是"事件流过的通道"(那是 RunState.event_queue)。
    任何 EventSink 都可以消费它,自己决定怎么渲染:
      · HTTP/SSE 模式:run_worker 的 sink 把它灌进 state.event_queue
        (to_dict() 后),stream_run_events 再 translate 成 OpenAI Responses
        协议推给前端。
      · CLI 模式:_cli_event_sink 直接按 type 分支渲染到终端。
    """
    type: str
    message: str = ""
    agent_label: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        return {
            "type": self.type,
            "message": self.message,
            "agent_label": self.agent_label,
            "payload": self.payload,
        }

    @classmethod
    def control_event(
        cls,
        event_type: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造控制事件 dict（不依赖 service 实例）。"""
        return cls(
            type=event_type,
            message=message,
            payload=payload or {},
        ).to_dict()



from ZBot.services.config.schema import Config
from ZBot.services.agent_run.agent_factory import create_agent_bundle
def create_agent_run_service(config: Config) -> AgentRunService:
    """从 Config 创建 AgentRunService。

    调用 create_agent_bundle + 包装为 AgentRunService。
    失败时抛出 AgentSetupError，由调用方决定如何上报错误。
    """
    return AgentRunService(create_agent_bundle(config))

# 类型别名声明, 可调用类型，它接收一个 AgentEvent，调用后返回一个可以被 await 的东西
#   List[int]          → 一个装 int 的列表
#   Dict[str, int]     → key 是 str、value 是 int 的字典
# 这是本文件与"事件流过的通道"(RunState.event_queue)之间的桥:
#   本文件只看见 EventSink,不知道下游是 queue 还是 CLI 终端还是别的。
EventSink = Callable[[AgentEvent], Awaitable[None]]


class AgentRunService:
    """
    也是每个一个协程都有一个 AgentRunService 的实例，批次互相独立
    统一管理一次 Agent 会话的启动、单轮对话、取消和清理。
    """

    def __init__(
        self,
        bundle: "AgentBundle",
    ) -> None:
        """初始化 run service。"""
        self.bundle = bundle
        self._started = False
        self._event_sink: EventSink | None = None
        self._session_name = "default"

    async def start(
        self,
        session_name: str,
        *,
        event_sink: EventSink,
    ) -> None:
        """启动会话级资源；交互会话/SSE 连接期间只调用一次，并没有调用大模型接口，而且没有真正启动 Agent，
        只是准备好了环境，真正的 Agent 启动是在 ask() 里调用的，并不要求强制调用 start()，如果直接调用 ask()，它会在内部调用 start() 来确保环境准备就绪。"""
        if self._started:
            self._event_sink = event_sink
            self._session_name = session_name
            self.bundle.cron.on_job = self.cron_event_handler(event_sink)
            return

        self._event_sink = event_sink
        self._session_name = session_name
        self.bundle.cron.on_job = self.cron_event_handler(event_sink)
        await self.bundle.cron.start()
        self._started = True
        await event_sink(self._event("run.started", "会话已启动"))


    async def ask(
        self,
        message: Any,
        session_name: str,
        *,
        event_sink: EventSink,  # 进度回调函数
    ) -> str:
        """执行一轮用户消息；资源清理由 close() 在会话结束时负责。"""
        if not self._started:
            await self.start(session_name, event_sink=event_sink)

        self._event_sink = event_sink
        self._session_name = session_name
        # H2: 给本轮分配一个稳定 turn_id,塞到 turn.started / turn.completed / run.completed
        # 的 payload 中。前端 useAgentStream 拿这个 turn_id 正确把 deltas 路由到对应 turn。
        turn_id = str(uuid.uuid4())
        # 不断的把事件塞入队列,给前端消费的，把事件塞入队列的同时，给心跳狗更新东西。
        await event_sink(
            self._event(
                "turn.started",
                "开始处理本轮消息",
                payload={"turn_id": turn_id},
            )
        )
        try:
            final_content = await self.bundle.agent.process_message(
                message,
                session_name,
                on_progress=self._progress_sink(event_sink, turn_id=turn_id),
            )
            await event_sink(
                self._event(
                    "turn.completed",
                    "本轮消息处理完成",
                    payload={"final_content": final_content, "turn_id": turn_id},
                )
            )
            await event_sink(
                self._event(
                    "run.completed",
                    "任务完成",
                    payload={"final_content": final_content, "turn_id": turn_id},
                )
            )
            return final_content
        except asyncio.CancelledError:
            # 捕获到 CancelledError 后，先做一点收尾动作，然后把同一个 CancelledError 继续往上抛。
            # ZBot 改: 透传 turn_id, 前端用它在 setTurns 里把对应 turn 标 cancelled。
            await event_sink(
                self._event(
                    "run.cancelled",
                    "任务已取消",
                    payload={"turn_id": turn_id},
                )
            )
            raise
        except Exception as exc:
            logger.exception("Agent run 执行失败")
            # ZBot 改: 透传 turn_id, 前端用它在 setTurns 里把对应 turn 标 failed。
            await event_sink(
                self._event(
                    "run.failed",
                    f"任务失败：{exc}",
                    payload={"error": str(exc), "turn_id": turn_id},
                )
            )
            raise

    async def close(self, session_name: str) -> None:
        """关闭会话级资源并执行会话收尾；该方法可重复调用。"""
        # cron/service.py:CronService.stop 是 sync 函数(只 cancel _timer_task),
        # 不是 coroutine,所以不需要 await。这里显式调用,见 cron/service.py:122-127。
        self.bundle.cron.stop()
        try:
            await self.bundle.agent.close_mcp()
            await self.bundle.agent.consolidate_all_session_memory(session_name=session_name)
            await self.bundle.agent.consolidate_daily_memory(session_name=session_name)
            try:
                await asyncio.wait_for(
                    self.bundle.agent.review_skills(session_name=session_name),
                    timeout=300,
                )
            except asyncio.TimeoutError:
                logger.warning("技能进化回顾超时（300秒），跳过")
            except Exception:
                logger.exception("技能进化回顾失败")
            try:
                await self.bundle.agent.run_curator()
            except Exception:
                logger.exception("技能 Curator 维护失败")
        except Exception:
            logger.exception("Agent 会话清理失败")
        finally:
            self._started = False
            if self._event_sink is not None:
                await self._event_sink(self._event("run.closed", "会话资源已清理"))

    def cron_event_handler(self, event_sink: EventSink):
        """创建 cron 到期回调，把提醒转换为 AgentEvent。"""

        async def _on_cron_job(job: CronJob) -> None:
            """把定时任务提醒转发为事件。"""
            await event_sink(
                self._event(
                    "cron.reminder",
                    job.message,
                    payload={"job_id": job.id, "job_name": job.name},
                )
            )

        return _on_cron_job

    def _progress_sink(
        self,
        event_sink: EventSink,
        *,
        turn_id: str = "",
    ) -> Callable[..., Awaitable[None]]:
        """把 BaseAgent 的字符串进度回调转换为结构化事件。"""

        async def _on_progress(
            content: str,   # 就是进度回调的内容
            *,
            tool_hint: bool = False,
            agent_label: str | None = None,
            **kwargs: Any,
        ) -> None:
            """接收 Agent 内部进度并发送事件。"""
            event_type = str(kwargs.pop("event_type", "") or ("tool.progress" if tool_hint else "agent.progress"))
            # H2: 把 turn_id 注入到所有 progress 事件的 payload,前端按它路由 deltas。
            payload = dict(kwargs)
            if turn_id:
                payload.setdefault("turn_id", turn_id)
            # ZBot 改:给状态类事件加 phase + tool_name 字段,前端 LiveStatus 组件按它显示
            # "ZBot 正在思考 / 正在调用工具 / 正在整理结果"。
            extra_events: list = []
            if event_type == "model.started":
                payload["phase"] = "thinking"
                # 同时推一条 status 事件,给前端 LiveStatus 显示"正在思考"
                extra_events.append("status")
            elif event_type in ("tool.started", "tool.progress"):
                payload["phase"] = "tool"
                # ZBot 改: 不再 fallback 到 agent_label —— agent_label 是 agent
                # 自己的名字 ("主agent" / "子agent<id>"), 不是工具名。如果 payload
                # 里没有 tool_name 字段, 就保持缺失, 让 SSE translator 走默认 "工具"。
                extra_events.append("tool_hint")
            elif event_type == "model.completed":
                # ZBot 改: 仅当模型响应**不包含 tool_calls** (即最终答案) 时才进入
                # finalizing 阶段。中间迭代 (model 决定继续调用工具) 不发 finalizing,
                # 避免多工具场景下「正在整理结果」闪烁多次。
                has_tool_calls = bool(kwargs.pop("has_tool_calls", False))
                if not has_tool_calls:
                    payload["phase"] = "finalizing"
                    extra_events.append("status")
            await event_sink(
                self._event(
                    event_type,
                    content,
                    agent_label=agent_label,
                    payload=payload,
                )
            )
            for extra_type in extra_events:
                await event_sink(
                    self._event(
                        extra_type,
                        content,
                        agent_label=agent_label,
                        payload=payload,
                    )
                )

        return _on_progress

    def _event(
        self,
        event_type: str,
        message: str = "",
        *,
        agent_label: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        """构造统一事件对象。"""
        return AgentEvent(
            type=event_type,
            message=message,
            agent_label=agent_label,
            payload=payload or {},
        )

