"""子 Agent 执行单元池。

第一版先复用内存里的 SubAgent 实例;后续如果要替换成多进程池,
只需要保持 acquire/release/close 这一层接口稳定。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from loguru import logger

from ZBot.agent.base_agent import BaseAgent
from ZBot.agent.subagent.subagent import SubAgent


@dataclass(frozen=True, slots=True)
class SubAgentPolicy:
    """子 Agent 的系统级运行边界。"""

    # 主 Agent 一次最多能同时借出的子 Agent 执行单元数量。
    max_count: int = 5
    # 单个子任务的默认最大执行时间;运行时配置未传入时使用,默认 10 分钟。
    timeout_seconds: int = 600


# 全局唯一的内部策略对象,和 SubAgentPool 放在一起,避免额外拆一个策略文件。
SUBAGENT_POLICY = SubAgentPolicy()


# H23: Sentinel 哨兵对象,用于唤醒可能在 _available.get() 上挂死的 acquire(),
# 让它在 close 后能立刻抛 RuntimeError 而不是无限等待。
_CLOSE_SENTINEL: "SubAgentLease" = None  # type: ignore[assignment]


class SubAgentLease:
    """一次从池里借出的子 Agent 执行单元。"""

    def __init__(self, agent_id: str, agent: SubAgent) -> None:
        self.agent_id: str = agent_id
        self.agent: SubAgent = agent


class SubAgentPool:
    """预创建并复用子 Agent 实例。

    当前实现是同进程内的实例池;设计上刻意像执行单元池,
    方便后面把 SubAgent 替换成独立进程代理而不改 create_sub_agent 工具。
    """

    def __init__(self, parent: BaseAgent, max_count: int = SUBAGENT_POLICY.max_count) -> None:
        """Agent 的子 Agent 执行单元池"""
        self._leases = [
            SubAgentLease(agent_id=f"subagent_{index}", agent=SubAgent.from_parent(parent))
            for index in range(1, max_count + 1)
        ]
        self._available: asyncio.Queue["SubAgentLease"] = asyncio.Queue(maxsize=max_count)
        for lease in self._leases:
            self._available.put_nowait(lease)
        self._closed = False

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[SubAgentLease]:
        """借出一个子 Agent;任务结束后自动归还池中。

        H23 修复:如果 close() 在 await get() 期间被调用,队列里会是哨兵 None,
        这里直接抛 RuntimeError 而不是继续 yield 一个不存在的 lease。
        """
        if self._closed:
            raise RuntimeError("子 Agent 池已经关闭")

        lease = await self._available.get()
        if lease is _CLOSE_SENTINEL:
            raise RuntimeError("子 Agent 池已经关闭")
        try:
            yield lease
        finally:
            if not self._closed:
                self._available.put_nowait(lease)

    async def close(self) -> None:
        """关闭池。后续替换为多进程实现时,在这里终止所有子进程。

        H23 修复:
          1. 先翻 _closed 标志,后续 acquire() 入口直接拒绝。
          2. 排空队列 + push 哨兵唤醒所有挂死的 acquire waiter。
          3. 关闭每个 SubAgent 持有的资源(MCP 连接、embedding 等)。
        """
        if self._closed:
            return
        self._closed = True
        # 先排空已有 lease,避免哨兵和 lease 在队列里混杂
        while not self._available.empty():
            self._available.get_nowait()
        # 对每个 max_size 推一个哨兵,确保所有 waiter 都被唤醒。
        # put_nowait 在 queue 已满(maxsize)时抛 QueueFull,这是预期的。
        for _ in range(self._available.maxsize):
            try:
                self._available.put_nowait(_CLOSE_SENTINEL)
            except asyncio.QueueFull:
                break
        # 关闭所有 SubAgent 持有的资源(close 可能是 async 或 sync)
        for lease in self._leases:
            try:
                agent = lease.agent
                close_attr = getattr(agent, "close", None)
                if not callable(close_attr):
                    continue
                result = close_attr()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("关闭子 Agent {} 失败", lease.agent_id)
