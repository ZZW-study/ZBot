"""Run registry:跟踪进行中和已结束的 agent run。

每个 run 由一个唯一 run_id 标识,关联:
- asyncio.Task:跑 AgentRunService.ask() 的后台任务
- asyncio.Queue:SSE 处理器从队列取事件发给前端
- status:queued | running | completed | failed | cancelled
- 元数据:session_name, created_at, started_at, ended_at, error


本文件管的是"容器和句柄",不关心事件内容是什么:
  - 这次 run 在不在?            → RunRegistry 的 _states 字典
  - 这次 run 跑到哪一步了?      → RunState.status
  - 谁在跑它(task 句柄)?        → RunState.task
  - 跑出来的事件放哪儿(管道)?   → RunState.event_queue(asyncio.Queue)

agent_run_service.py 管的是"执行和事件载荷":
  - 怎么调 Agent(process_message)?
  - 每一步要发什么类型的 AgentEvent?
  - 资源怎么收尾(close → cron / mcp / 记忆 / 技能)?

二者通过 backend/handlers/agent_sse.py::run_worker 粘合:
  sink = lambda evt: state.event_queue.put(evt.to_dict())
  · AgentRunService 只看见一个 EventSink,不知道有 RunState
  · RunRegistry 只看见一个 asyncio.Queue,不知道有 AgentEvent
  · stream_run_events 只从 state.event_queue 拿 dict,自己 translate 成 SSE 协议

为什么不让 AgentRunService 自己管 event_queue?
  不同的 session 并发多个 run,事件必须按 run_id 路由到不同 SSE 连接。
  RunState.event_queue 就是天然的"按 run_id 索引"多路复用器。

事件通道的生命周期:
  create(run_id)         → event_queue 随 RunState 一起创建
  attach_task/run_worker → sink 往 event_queue 灌 dict
  mark_ended             → status 终结
  unregister             → 容器从 dict 删掉(同时由 run_worker 灌 None 哨兵
                           让 SSE 消费者 await get() 拿到 None 后退出)
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RunState:
    """一次 agent run 的运行时句柄。
    由于是在async await内部创建，所以每个协程都有一个自己的
    字段分组:
      · 标识/元数据:run_id, session_name, created_at, started_at, ended_at, error
      · 状态机:status(RunStatus.CANCELLED 才是真正的"已取消"标志)
      · 协作资源:task(后台协程), event_queue(事件管道)
    """
    run_id: str
    session_name: str
    status: RunStatus = RunStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None
    # 事件管道:run_worker 把 AgentEvent.to_dict() 灌进来,
    # stream_run_events 拿出去 translate 成 SSE 协议推给前端。
    # 谁也不直接 import 对方,只通过这个 Queue 通信。
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class RunRegistry:
    """
    多个会话的协程共享的类，所以需要加锁。
    run_id → RunState 的内存注册表,协程安全。
    每个会话就都有自己的一个协程（保证多个会话，多个协程可以同时运行），通过run_id来区分。
    是 HTTP 层与后台 worker 之间的"路由表":
      · 启动 run  → routers/runs.py::start_run 调 create()
      · 查 run    → routers/runs.py::_resolve_run 调 get()
      · 取消 run  → routers/runs.py::cancel_run 调 request_cancel()
      · 状态变更  → run_worker 调 mark_started() / mark_ended()
      · 收尾      → run_worker 调 unregister() 释放容器
    """

    def __init__(self) -> None:
        self._states: dict[str, RunState] = {}
        self._lock = asyncio.Lock()

    async def create(self, session_name: str) -> RunState:
        """创建并注册一个新 run,返回 RunState。

        在注册表里占一个槽位,并把一个全新的 event_queue 挂上去,
        供后续的 run_worker / SSE 消费者用。
        """
        async with self._lock:
            run_id = str(uuid.uuid4())
            state = RunState(run_id=run_id, session_name=session_name)
            self._states[run_id] = state
            return state



    async def get(self, run_id: str) -> Optional[RunState]:
        async with self._lock:
            return self._states.get(run_id)



    async def attach_task(self, run_id: str, task: asyncio.Task) -> None:
        async with self._lock:
            state = self._states.get(run_id)
            # 如果有state，就把task挂到state上
            if state is not None:
                state.task = task


    async def mark_started(self, run_id: str) -> None:
        """标记一个 run 开始运行。"""
        async with self._lock:
            state = self._states.get(run_id)
            if state is not None:
                state.status = RunStatus.RUNNING
                state.started_at = datetime.now()


    async def mark_ended(self, run_id: str, status: RunStatus, error: Optional[str] = None) -> None:
        """标记一个 run 结束运行。"""
        async with self._lock:
            state = self._states.get(run_id)
            if state is not None:
                state.status = status
                state.ended_at = datetime.now()
                if error is not None:
                    state.error = error



    async def request_cancel(self, run_id: str) -> bool:
        """请求取消一个 run:取消 task。返回是否成功触发。

        取消的实际状态由下游 _ask_once 在 except asyncio.CancelledError
        分支里调 mark_ended(..., CANCELLED) 写入,stream_run_events
        看到 RunStatus.CANCELLED 就退出。
        """
        async with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return False
            if state.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                return False
            task = state.task
        # 锁外 cancel,避免长任务阻塞
        if task is not None and not task.done():
            task.cancel()
        return True



    async def unregister(self, run_id: str) -> None:
        """从注册表里移除 run(run_worker 收尾时调)。

        注意:调用方(run_worker)应**先**往 state.event_queue 灌一个 None
        哨兵,让 SSE 消费者 await get() 拿到 None 后退出;然后再调本方法
        释放容器。否则可能还有 SSE 消费者在 await state.event_queue.get()。
        """
        async with self._lock:
            self._states.pop(run_id, None)



    async def cleanup_ended(self, older_than_seconds: int = 3600) -> int:
        """Remove RunState entries that ended more than N seconds ago. Returns count removed."""
        async with self._lock:
            cutoff = datetime.now().timestamp() - older_than_seconds
            to_remove = [
                run_id
                for run_id, state in self._states.items()
                if state.ended_at is not None and state.ended_at.timestamp() < cutoff
            ]
            for run_id in to_remove:
                self._states.pop(run_id, None)
            return len(to_remove)



    async def snapshot(self) -> list[RunState]:
        async with self._lock:
            return list(self._states.values())
