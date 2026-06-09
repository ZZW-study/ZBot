"""
心跳模块，一个活动跟踪器，看看是否有活动。
看看主 agent 是否有活动。
一个看门狗，接受一个心跳，看看是否有活动，设置阈值，发出警告、杀死卡死的 agent。
"""
import asyncio
import threading
import time

from loguru import logger


class ActivityTracker:
    """心跳——是否活动跟踪器。"""

    def __init__(self) -> None:
        """初始化：记录最近一次活动的时间戳和描述。"""
        # 以单调时钟记录最后一次活动的时间，避免系统时间调整导致的问题
        self.last_activity_at: float = time.monotonic()
        # 上次活动的描述
        self.last_activity_desc: str = "初始化"
        # 多线程安全，后续可能会用到，现在没有多线程
        self._lock = threading.Lock()

    def touch(self, description: str) -> None:
        """每次有意义的操作前调用，标记为活动点。"""
        with self._lock:
            self.last_activity_at = time.monotonic()
            self.last_activity_desc = description

    def get_summary(self) -> dict[str, float | str]:
        """返回当前空闲状态。"""
        with self._lock:
            idle_seconds = time.monotonic() - self.last_activity_at
            return {
                "idle_seconds": idle_seconds,
                "last_activity": self.last_activity_desc,
            }


class ActivityWatchdog:
    """活动监控，检查是否有活动。

    设计要点（学习自 hermes-agent）：
    - 默认走 asyncio.sleep，吞吐、适配低频场景
    - 调用 watchdog.bind_task(task) 后切换为 asyncio.wait(task, timeout)，
      task 完成时 wait 立即返回，不用等满 heartbeat_interval
    - 阈值逻辑保持原有行为（警告/记录），不做硬杀
    """

    def __init__(
        self,
        activity_tracker: ActivityTracker,
        heartbeat_interval: float = 5.0,
        agent_warning: float = 900.0,
        agent_kill: float = 1800.0,
    ) -> None:
        """初始化看门狗。

        Args:
            activity_tracker: 活动跟踪器。
            heartbeat_interval: 检查频率（秒）。默认 5 秒。
            agent_warning: idle 超过该值输出 warning。默认 900 秒（15 分钟）。
            agent_kill: idle 超过该值输出 error。默认 1800 秒（30 分钟）。
        """
        self.activity_tracker = activity_tracker
        self.heartbeat_interval = heartbeat_interval
        self.agent_warning = agent_warning
        self.agent_kill = agent_kill
        # 可选：绑定的 agent task 引用；绑定后 task 完成时 watchdog 立即退出
        self._agent_task: asyncio.Task | None = None

    def bind_task(self, task: asyncio.Task | None) -> None:
        """绑定 agent 协程 task，使 watchdog 能在 task 完成时立即退出（学习自 hermes-agent）。

        不传 / 传 None 退化为原 asyncio.sleep 行为，向后兼容。
        """
        self._agent_task = task

    async def _check_idle(self) -> None:
        """检查空闲状态，输出 warning / kill 日志（沉用原阈值逻辑）。"""
        summary = self.activity_tracker.get_summary()
        if summary["idle_seconds"] > self.agent_warning:
            # 不是给用户看的，是我根据这个日志来判断是否需要调整心跳监控的阈值，或者检查 agent 是否进入死循环了
            logger.warning(
                f"Agent 已经 {summary['idle_seconds']:.1f} 秒没有活动了，最后一次活动是：{summary['last_activity']}"
            )
            logger.warning(
                f"如果超过 {self.agent_kill} 秒没有活动，系统将自动杀死 Agent 以释放资源。"
            )
            logger.warning(
                f"请检查 Agent 是否进入死循环，或者是否需要调整心跳监控的阈值。"
            )

        if summary["idle_seconds"] > self.agent_kill:
            # 记录告警，实际是否杀由上层 task 控制（学习 hermes：通过 inactivity 触发 interrupt）
            logger.error(
                f"Agent 已经 {summary['idle_seconds']:.1f} 秒没有活动了，系统将自动杀死 Agent 的这个活动以释放资源。"
            )

    async def run(self) -> None:
        """主循环：每 heartbeat_interval 秒检查一次，绑定的 task 完成时立即退出。

        - 未绑定 task：退化为 asyncio.sleep 行为（向后兼容）
        - 绑定 task：用 asyncio.wait 替代 asyncio.sleep，
          task 完成时 wait 立即返回，不用等满 heartbeat_interval
        """
        while True:
            if self._agent_task is not None:
                # task 完成时 wait 立即返回，不用等满 heartbeat_interval
                done, _ = await asyncio.wait(
                    {self._agent_task}, timeout=self.heartbeat_interval
                )
                if done:
                    # task 完成了，watchdog 同步退出
                    logger.debug("ActivityWatchdog: agent task 完成，退出监控")
                    return
            else:
                # 没绑定 task，退化路径（向后兼容）
                await asyncio.sleep(self.heartbeat_interval)
            await self._check_idle()
