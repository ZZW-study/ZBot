"""Run registry:跟踪进行中和已结束的 agent run。

每个 run 由一个唯一 run_id 标识,关联:
- asyncio.Task:跑 AgentRunService.ask() 的后台任务
- asyncio.Queue:SSE 处理器从队列取事件发给前端
- status:queued | running | completed | failed | cancelled
- 元数据:thread_name, created_at, started_at, ended_at, error
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
    run_id: str
    thread_name: str
    status: RunStatus = RunStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancelled: bool = False


class RunRegistry:
    """run_id -> RunState 的内存注册表,协程安全。"""

    def __init__(self) -> None:
        self._states: dict[str, RunState] = {}
        self._lock = asyncio.Lock()

    async def create(self, thread_name: str) -> RunState:
        """创建并注册一个新 run,返回 RunState。"""
        run_id = str(uuid.uuid4())
        state = RunState(run_id=run_id, thread_name=thread_name)
        async with self._lock:
            self._states[run_id] = state
        return state

    async def get(self, run_id: str) -> Optional[RunState]:
        async with self._lock:
            return self._states.get(run_id)

    async def attach_task(self, run_id: str, task: asyncio.Task) -> None:
        async with self._lock:
            state = self._states.get(run_id)
            if state is not None:
                state.task = task

    async def mark_started(self, run_id: str) -> None:
        async with self._lock:
            state = self._states.get(run_id)
            if state is not None:
                state.status = RunStatus.RUNNING
                state.started_at = datetime.now()

    async def mark_ended(self, run_id: str, status: RunStatus, error: Optional[str] = None) -> None:
        async with self._lock:
            state = self._states.get(run_id)
            if state is not None:
                state.status = status
                state.ended_at = datetime.now()
                if error is not None:
                    state.error = error

    async def request_cancel(self, run_id: str) -> bool:
        """请求取消一个 run:标 cancelled,取消 task。返回是否成功触发。"""
        async with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return False
            if state.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                return False
            state.cancelled = True
            task = state.task
        # 锁外 cancel,避免长任务阻塞
        if task is not None and not task.done():
            task.cancel()
        return True

    async def unregister(self, run_id: str) -> None:
        async with self._lock:
            self._states.pop(run_id, None)

    async def cleanup_ended(self, older_than_seconds: int = 3600) -> int:
        """Remove RunState entries that ended more than N seconds ago. Returns count removed."""
        cutoff = datetime.now().timestamp() - older_than_seconds
        async with self._lock:
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
