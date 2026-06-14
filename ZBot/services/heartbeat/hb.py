import asyncio
import threading
import time
from threading import Thread
from typing_extensions import Self
from loguru import logger


class ActivityTracker:
    """记录 agent 最近一次心跳（活动时间 + 描述）"""
    _instance = None

    def __new__(cls) -> Self:
        """单例，给agentservice用"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    

    def __init__(self) -> None:
        # 最近一次活动时间（单调时钟，避免系统时间变化影响）
        self.last_activity_at = time.monotonic()
        # 最近一次活动描述
        self.last_activity_desc = "初始化"
        # 线程安全锁（防止多线程同时写入）
        self._lock = threading.Lock()

    def touch(self, description: str) -> None:
        """更新心跳（表示 agent 有活动）"""
        with self._lock:
            self.last_activity_at = time.monotonic()
            self.last_activity_desc = description

    def get_idle(self) -> tuple[float, str]:
        """获取当前空闲时间 + 最后一次活动描述"""
        with self._lock:
            return (
                time.monotonic() - self.last_activity_at,
                self.last_activity_desc,
            )


class ActivityWatchdog:
    """心跳狗：定期检查 agent 是否长时间无活动"""

    def __init__(
        self,
        tracker: ActivityTracker,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task,
    ) -> None:
        self.tracker = tracker          # 心跳数据来源
        self.loop = loop                # asyncio 事件循环（用于安全取消 task）
        self.task = task                # 被监控的协程任务

        # 检查间隔（秒）
        self.interval = 30

        # 分级阈值
        self.warn_t = 5 * 60           # 5分钟警告
        self.severe_t = 15 * 60        # 15分钟严重警告
        self.kill_t = 30 * 60          # 30分钟终止

        # 停止控制,线程事件对象，内部有一个布尔状态标志，默认是 False（未触发）。
        self._stop = threading.Event()

    def start(self) -> None:
        """启动心跳检测线程"""
        Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        """停止心跳检测，设置为True"""
        self._stop.set()

    def _cancel(self) -> None:
        """线程安全地取消 asyncio task
        会在那个协程正在 await 的地方
        raise asyncio.CancelledError
        """

        self.loop.call_soon_threadsafe(self.task.cancel)

    def _run(self) -> None:
        """心跳检测主循环（在独立线程中运行）"""
        # 只要内部是False
        while not self._stop.wait(self.interval):
            idle, desc = self.tracker.get_idle()

            # 终止级别
            if idle > self.kill_t:
                logger.error(
                    "心跳狗触发【终止】\n"
                    f"空闲时间：{idle:.1f} 秒\n"
                    f"终止阈值：{self.kill_t:.1f} 秒\n"
                    f"最后一次心跳：{desc}\n"
                    f"动作：取消任务（task.cancel）"
                )
                self._cancel()
                break

            # 严重警告
            if idle > self.severe_t:
                logger.error(
                    "心跳狗触发【严重警告】\n"
                    f"空闲时间：{idle:.1f} 秒\n"
                    f"严重阈值：{self.severe_t:.1f} 秒\n"
                    f"最后一次心跳：{desc}\n"
                    f"状态：长时间无响应"
                )

            # 普通警告
            elif idle > self.warn_t:
                logger.warning(
                    "心跳狗触发【警告】\n"
                    f"空闲时间：{idle:.1f} 秒\n"
                    f"警告阈值：{self.warn_t:.1f} 秒\n"
                    f"最后一次心跳：{desc}\n"
                    f"状态：空闲过长"
                )