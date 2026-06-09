"""
会话过期看门狗，用于多连接 / 多平台场景下释放长期不活跃的 AgentRunService。

学习自 hermes-agent gateway/run.py:2434 _session_expiry_watcher：
- 每 60 秒扫描一次会话注册表
- idle 超过阈值（默认 30 分钟）的会话被释放
- 仅记录 + 调用 close()，不做硬杀（与看门狗一致）
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

if TYPE_CHECKING:
    from ZBot.services.agent_run.agent_run_service import AgentRunService


@dataclass
class SessionEntry:
    """会话注册表中的一条记录。"""

    session_name: str
    service: "AgentRunService"
    last_activity_at: float = field(default_factory=time.monotonic)
    # 记录创建时间，便于调试
    created_at: float = field(default_factory=time.monotonic)


class SessionRegistry:
    """会话注册表（进程内全局，多个 WS 连接共享）。

    主要责任：
    - 跟踪每个 session_name 对应的 AgentRunService 实例
    - 跟踪每个会话的最后活动时间
    - 提供线程安全的 register / unregister / touch 接口

    设计要点：
    - 使用 asyncio.Lock 保护内部状态，与你现有代码中的 async 风格一致
    - 不依赖任何现有模块，你可以独立使用这个注册表
    """

    def __init__(self) -> None:
        """初始化空的会话注册表。"""
        self._entries: dict[str, SessionEntry] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        session_name: str,
        service: "AgentRunService",
        *,
        last_activity: float | None = None,
    ) -> None:
        """注册一个会话。如果 session_name 已存在，覆盖原有记录。

        Args:
            session_name: 会话名称。
            service: AgentRunService 实例。
            last_activity: 初始最后活动时间，默认现在。
        """
        async with self._lock:
            self._entries[session_name] = SessionEntry(
                session_name=session_name,
                service=service,
                last_activity_at=last_activity if last_activity is not None else time.monotonic(),
            )

    async def unregister(self, session_name: str) -> None:
        """取消注册一个会话。不存在则为 no-op。

        Args:
            session_name: 会话名称。
        """
        async with self._lock:
            self._entries.pop(session_name, None)

    async def touch(self, session_name: str) -> bool:
        """刷新伀个会话的最后活动时间。
        """
        async with self._lock:
            entry = self._entries.get(session_name)
            if entry is None:
                return False
            entry.last_activity_at = time.monotonic()
            return True

    async def snapshot(self) -> list[SessionEntry]:
        """返回当前所有会话记录的副本（不含锁，只读）。
        """
        async with self._lock:
            return list(self._entries.values())

    async def size(self) -> int:
        """返回当前注册的会话数。"""
        async with self._lock:
            return len(self._entries)


class SessionExpiryWatcher:
    """会话过期看门狗，定期扫描并释放 idle 的会话。

    与 hb.py 中的 ActivityWatchdog 差别：
    - hb.py 是针对“单个 agent 是否占用了太久”，输出告警
    - 本类是针对“多个会话是否长期不活跃”，主动释放资源
    """

    def __init__(
        self,
        registry: SessionRegistry,
        *,
        idle_seconds: float = 1800.0,
        scan_interval: float = 60.0,
        on_expire: Callable[[SessionEntry], Awaitable[None]] | None = None,
    ) -> None:
        """初始化会话过期看门狗。

        Args:
            registry: 会话注册表。
            idle_seconds: idle 超过该值被认为过期。默认 1800 秒（30 分钟）。
            scan_interval: 扫描频率。默认 60 秒。
            on_expire: 自定义过期回调，默认调用 service.close(session_name)。
        """
        self.registry = registry
        self.idle_seconds = idle_seconds
        self.scan_interval = scan_interval
        self._on_expire = on_expire
        self._running = False

    async def _default_on_expire(self, entry: SessionEntry) -> None:
        """默认过期处理：调用 service.close()。

        与看门狗一致，不做硬杀，只是提示 close，\n        实际是否关闭由 service.close 自己决定。
        """
        try:
            await entry.service.close(entry.session_name)
            logger.info(
                f"会话过期已释放: session={entry.session_name} idle={time.monotonic() - entry.last_activity_at:.1f}s"
            )
        except Exception as exc:
            logger.exception(
                f"会话过期释放失败: session={entry.session_name} error={exc}"
            )

    async def scan_once(self) -> int:
        """扫描一次，返回被过期的会话数。

        Returns:
            被标记为过期的会话数。
        """
        entries = await self.registry.snapshot()
        now = time.monotonic()
        expired: list[SessionEntry] = []
        for entry in entries:
            idle = now - entry.last_activity_at
            if idle >= self.idle_seconds:
                expired.append(entry)
                logger.debug(
                    f"会话达到 idle 阈值: session={entry.session_name} idle={idle:.1f}s"
                )
        for entry in expired:
            await self.registry.unregister(entry.session_name)
            handler = self._on_expire or self._default_on_expire
            await handler(entry)
        return len(expired)

    async def run(self) -> None:
        """后台任务主循环。适合作为 asyncio.create_task() 的目标。

        可以通过 task.cancel() 打断（会抛 CancelledError）。
        """
        self._running = True
        try:
            while self._running:
                try:
                    await self.scan_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # 扫描出现异常不能让 watcher 死，记录后继续
                    logger.exception(f"SessionExpiryWatcher.scan_once 异常: {exc}")
                await asyncio.sleep(self.scan_interval)
        finally:
            self._running = False

    def stop(self) -> None:
        """设置停止标志。run() 下一次循环检查后退出。"""
        self._running = False


async def start_session_expiry_watcher(
    watcher: SessionExpiryWatcher,
) -> asyncio.Task[None]:
    """便捷启动函数：在事件循环里创建一个后台任务。

    例子（在 backend/app.py 的 lifespan 里）：

        @asynccontextmanager
        async def lifespan(app):
            registry = SessionRegistry()
            watcher = SessionExpiryWatcher(registry)
            task = await start_session_expiry_watcher(watcher)
            try:
                yield
            finally:
                watcher.stop()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    Args:
        watcher: 已配置好的 SessionExpiryWatcher。

    Returns:
        asyncio.Task，可以保存到 app.state 以便 lifespan 关闭时 cancel。
    """
    return asyncio.create_task(watcher.run())


__all__ = [
    "SessionEntry",
    "SessionRegistry",
    "SessionExpiryWatcher",
    "session_registry",
    "session_watcher",
    "start_session_expiry_watcher",
]


# =====================================================================
# 模块级单例 + 默认 watcher（与 config_cache 同风格）
# =====================================================================
# 使用方式：
#   - backend/app.py 的 lifespan 调用 session_watcher.start() / stop()
#   - SSE 路径通过 run_registry 维护 run 生命周期(见 backend/handlers/agent_sse.py)
# 不想用默认实例可自己 new SessionRegistry()。

# 进程级注册表，所有 WS 连接 / 平台桥接共享
session_registry: SessionRegistry = SessionRegistry()

# 默认 watcher（超1800s idle 就释放，每 60s 扫描）
session_watcher: SessionExpiryWatcher = SessionExpiryWatcher(
    session_registry,
    idle_seconds=1800.0,
    scan_interval=60.0,
)
