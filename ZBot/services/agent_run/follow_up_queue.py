"""Follow-up 队列:支持「steering」模式,用户可在 agent 运行中发新消息。

每个 thread 有自己的 FIFO 队列。当前的 turn 结束后,run worker
会从队列里取下一条消息启动新的 turn。

队列项:
- follow_up_id:UUID,用于 DELETE 撤回
- thread_name:所属 thread
- message:用户消息内容
- queued_at:入队时间
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class FollowUp:
    follow_up_id: str
    thread_name: str
    message: str
    queued_at: datetime = field(default_factory=datetime.now)


class FollowUpQueue:
    """按 thread_name 索引的 follow-up 队列集合。"""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[FollowUp]] = {}
        self._by_id: dict[str, FollowUp] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, thread_name: str, message: str) -> FollowUp:
        fu = FollowUp(
            follow_up_id=str(uuid.uuid4()),
            thread_name=thread_name,
            message=message,
        )
        async with self._lock:
            queue = self._queues.setdefault(thread_name, asyncio.Queue())
            await queue.put(fu)
            self._by_id[fu.follow_up_id] = fu
        return fu

    async def dequeue(self, thread_name: str) -> Optional[FollowUp]:
        """弹出一条(非阻塞)。空时返回 None。"""
        async with self._lock:
            queue = self._queues.get(thread_name)
            if queue is None or queue.empty():
                return None
            fu = queue.get_nowait()
            self._by_id.pop(fu.follow_up_id, None)
            return fu

    async def remove(self, follow_up_id: str, thread_name=None) -> bool:
        """从未消费的队列里撤回一条(按 ID)。返回是否成功。

        当提供 thread_name 时,会校验 follow-up 是否属于该 thread;不匹配则
        返回 False,避免用其他 thread 的 follow_up_id 误删。
        """
        async with self._lock:
            fu = self._by_id.get(follow_up_id)
            if fu is None:
                return False
            if thread_name is not None and fu.thread_name != thread_name:
                return False
            self._by_id.pop(follow_up_id, None)
            queue = self._queues.get(fu.thread_name)
            if queue is None:
                return True
            # 重建队列(过滤掉这一条)
            remaining: asyncio.Queue[FollowUp] = asyncio.Queue()
            drained: list[FollowUp] = []
            while not queue.empty():
                item = queue.get_nowait()
                if item.follow_up_id != follow_up_id:
                    drained.append(item)
            for item in drained:
                await remaining.put(item)
            self._queues[fu.thread_name] = remaining
            return True

    async def list(self, thread_name: str) -> list[FollowUp]:
        async with self._lock:
            queue = self._queues.get(thread_name)
            if queue is None:
                return []
            return list(queue._queue)  # type: ignore[attr-defined]

    async def clear(self, thread_name: str) -> None:
        async with self._lock:
            queue = self._queues.pop(thread_name, None)
            if queue is not None:
                while not queue.empty():
                    fu = queue.get_nowait()
                    self._by_id.pop(fu.follow_up_id, None)
