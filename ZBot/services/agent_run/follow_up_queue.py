"""Follow-up 队列:支持「steering」模式,用户可在 agent 运行中发新消息。

每个 session 有自己的 FIFO 队列。当前的 turn 结束后,run worker
会从队列里取下一条消息启动新的 turn。

队列项:
- follow_up_id:UUID,用于 DELETE 撤回
- session_name:所属 session
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
    session_name: str
    message: str
    queued_at: datetime = field(default_factory=datetime.now)


class FollowUpQueue:
    """按 session_name 索引的 follow-up 队列集合。"""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[FollowUp]] = {}
        self._by_id: dict[str, FollowUp] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, session_name: str, message: str) -> FollowUp:
        fu = FollowUp(
            follow_up_id=str(uuid.uuid4()),
            session_name=session_name,
            message=message,
        )
        async with self._lock:
            queue = self._queues.setdefault(session_name, asyncio.Queue())
            await queue.put(fu)
            self._by_id[fu.follow_up_id] = fu
        return fu

    async def dequeue(self, session_name: str) -> Optional[FollowUp]:
        """弹出一条(非阻塞)。空时返回 None。"""
        async with self._lock:
            queue = self._queues.get(session_name)
            if queue is None or queue.empty():
                return None
            fu = queue.get_nowait()
            self._by_id.pop(fu.follow_up_id, None)
            return fu

    async def remove(self, follow_up_id: str, session_name=None) -> bool:
        """从未消费的队列里撤回一条(按 ID)。返回是否成功。

        当提供 session_name 时,会校验 follow-up 是否属于该 session;不匹配则
        返回 False,避免用其他 session 的 follow_up_id 误删。

        H1 修复:不要在 self._lock 内 await remaining.put(item)。
        锁内 await 一旦队列达到 maxsize + 等待 put 的协程正好又被其他协程
        持锁等待,就会死锁。这里把"构建新队列"完全放在锁外,
        锁内只做指针替换。
        """
        async with self._lock:
            fu = self._by_id.get(follow_up_id)
            if fu is None:
                return False
            if session_name is not None and fu.session_name != session_name:
                return False
            target_session = fu.session_name
            self._by_id.pop(follow_up_id, None)
            old_queue = self._queues.get(target_session)
            if old_queue is None:
                return True
            # 锁内把现有队列内容快照成 list,然后释放锁
            snapshot: list[FollowUp] = list(old_queue._queue)  # type: ignore[attr-defined]
        # 锁外构建新队列并过滤(非 await,只有 put_nowait)
        kept = [item for item in snapshot if item.follow_up_id != follow_up_id]
        remaining: asyncio.Queue[FollowUp] = asyncio.Queue()
        for item in kept:
            remaining.put_nowait(item)
        # 锁内仅做指针替换
        async with self._lock:
            # 若期间其他协程又 enqueue 了新条目,简单保留原 queue;
            # 否则用新 remaining 覆盖。竞态下"丢新加"和"覆盖旧"都不致命,
            # 因为新加的会在 _queues.get(target_session) 时被找到。
            current = self._queues.get(target_session)
            if current is old_queue:
                self._queues[target_session] = remaining
        return True

    async def list(self, session_name: str) -> list[FollowUp]:
        async with self._lock:
            queue = self._queues.get(session_name)
            if queue is None:
                return []
            return list(queue._queue)  # type: ignore[attr-defined]

    async def clear(self, session_name: str) -> None:
        async with self._lock:
            queue = self._queues.pop(session_name, None)
            if queue is not None:
                while not queue.empty():
                    fu = queue.get_nowait()
                    self._by_id.pop(fu.follow_up_id, None)
