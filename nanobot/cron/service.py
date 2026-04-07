"""异步定时任务调度器（CronService）。

此模块负责：
- 任务的增删查（管理接口）
- 将任务持久化到磁盘上的 JSON 文件
- 在后台按计划唤醒并执行到期任务

实现细节：调度器本身不负责任务的业务逻辑。业务逻辑通过 `on_job` 回调注入，
因此 `CronService` 更像是一个纯粹的调度层。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine
from zoneinfo import ZoneInfo

from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


# 使用北京时间时区进行 cron 表达式计算与时间展示
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _now_ms() -> int:
    """返回当前时间的毫秒级时间戳（整数）。

    说明：系统内部使用毫秒时间戳来统一比较和存储时间。
    """
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """根据任务的 `schedule` 规则计算下一次应触发的毫秒时间戳。

    返回值：下一次触发的毫秒时间戳，若规则当前不可执行则返回 `None`。

    支持的规则：
    - `at`：在指定的毫秒时间点执行（过期则返回 None）
    - `every`：从 now_ms 起按间隔 every_ms 计算下一次执行
    - `cron`：使用 croniter 解析 cron 表达式，计算下一个时间点
    """
    # --- at 类型：直接返回 at_ms（如果在未来） ---
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    # --- every 类型：固定间隔任务 ---
    if schedule.kind == "every":
        return now_ms + schedule.every_ms if schedule.every_ms and schedule.every_ms > 0 else None

    # --- cron 类型：使用 croniter 计算下一个匹配时间 ---
    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter

            # 把基准时间转换为具有时区信息的 datetime（使用北京时间）
            base = datetime.fromtimestamp(now_ms / 1000, tz=BEIJING_TZ)
            # croniter 返回下一个 datetime，转换为毫秒整数返回
            return int(croniter(schedule.expr, base).get_next(datetime).timestamp() * 1000)
        except Exception:
            # 如果解析或计算失败，视为当前不可用（返回 None）
            return None

    # 其它不支持或参数不完整的情况
    return None


def _validate_schedule(schedule: CronSchedule) -> None:
    """在创建任务前，校验 schedule 字段的合法性并在错误时抛出异常。

    规则：
    - at 类型必须提供 at_ms
    - every 类型的 every_ms 必须为正数
    - cron 类型需要安装 croniter 并且 expr 合法
    """
    if schedule.kind == "at":
        if schedule.at_ms is None:
            raise ValueError("at 类型任务必须提供 at_ms。")
        return

    if schedule.kind == "every":
        if schedule.every_ms is None or schedule.every_ms <= 0:
            raise ValueError("every 类型任务的 every_ms 必须大于 0。")
        return

    if schedule.kind == "cron":
        if not schedule.expr:
            raise ValueError("cron 类型任务必须提供 expr。")
        try:
            from croniter import croniter
        except Exception as exc:
            # 如果没有安装 croniter，提示用户安装依赖
            raise ValueError("cron 类型任务依赖 croniter，请先安装该依赖。") from exc
        if not croniter.is_valid(schedule.expr):
            raise ValueError(f"Cron 表达式无效：'{schedule.expr}'")
        return

    # 其它未知的 kind
    raise ValueError(f"不支持的任务调度类型：'{schedule.kind}'")


class CronService:
    """任务调度服务：负责任务的增删查、持久化与定时调度执行。

    参数：
    - store_path: 持久化 JSON 存储路径
    - on_job: 当任务触发时的回调，回调会被 await（可为空）
    """

    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None,
    ):
        # 存储路径（JSON 文件）
        self.store_path = store_path
        # 触发任务时的回调（业务侧实现），可以是 async 函数
        self.on_job = on_job
        # 内存中的 store 缓存（CronStore），懒加载
        self._store: CronStore | None = None
        # 记录上次加载文件的 mtime，用于检测文件变化
        self._last_mtime = 0.0
        # 内部计时器的 asyncio.Task（用于定时唤醒）
        self._timer_task: asyncio.Task | None = None
        # 服务是否正在运行的标志
        self._running = False

    async def start(self) -> None:
        """启动调度器：加载存储、计算每个任务的下一次执行时间并启动计时器。"""
        self._running = True
        store = self._load_store()
        now = _now_ms()
        # 为每个已存任务计算 next_run_at_ms（防止服务重启导致丢失计算）
        for job in store.jobs:
            self._schedule_job(job, now)
        # 把可能更新过的任务写回磁盘并 arm 计时器
        self._save_store()
        self._arm_timer()
        logger.info("定时任务服务已启动，当前共加载 {} 个任务", len(store.jobs))

    def stop(self) -> None:
        """停止调度器并取消挂起的计时器任务（同步方法）。"""
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """返回任务列表；默认仅返回启用的任务，按下次运行时间排序。"""
        jobs = self._load_store().jobs
        if not include_disabled:
            jobs = [job for job in jobs if job.enabled]
        # 把没有 next_run_at_ms 的任务放到最后（使用 inf 作为排序占位）
        return sorted(jobs, key=lambda job: job.state.next_run_at_ms or float("inf"))

    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        deliver: bool = False,
        delete_after_run: bool = False,
    ) -> CronJob:
        """创建并持久化一条新任务，返回 CronJob 实例。

        步骤：校验规则 -> 构造 CronJob -> 写入内存 store -> 持久化 -> 重置计时器
        """
        _validate_schedule(schedule)

        now = _now_ms()
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(
                kind="agent_turn",
                message=message,
                deliver=deliver,
            ),
            # 计算下一次触发时间并记录到 state
            state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now)),
            created_at_ms=now,
            updated_at_ms=now,
            delete_after_run=delete_after_run,
        )

        store = self._load_store()
        store.jobs.append(job)
        self._save_store()
        self._arm_timer()
        logger.info("定时任务已添加：'{}'（ID：{}）", job.name, job.id)
        return job

    def remove_job(self, job_id: str) -> bool:
        """按 id 删除任务；若删除成功则持久化并重置计时器。"""
        store = self._load_store()
        before = len(store.jobs)
        store.jobs = [job for job in store.jobs if job.id != job_id]
        removed = len(store.jobs) != before
        if removed:
            self._save_store()
            self._arm_timer()
            logger.info("定时任务已删除：{}", job_id)
        return removed

    def status(self) -> dict[str, Any]:
        """返回简要的运行状态供外部查询。"""
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._next_wake_ms(),
        }

    def _load_store(self) -> CronStore:
        """从磁盘读取任务存储并缓存到内存。

        行为说明：
        - 如果内存中已有缓存且磁盘文件未变化，直接返回缓存。
        - 如果磁盘文件不存在或解析失败，返回一个空的 CronStore。
        """
        # 如果已加载且文件未变化，直接复用内存中的 store
        if self._store is not None and not self._store_changed():
            return self._store

        # 文件不存在时返回空的 store（首次运行场景）
        if not self.store_path.exists():
            self._store = CronStore()
            self._last_mtime = 0.0
            return self._store

        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            # 把每个 JSON 项转为 CronJob 对象
            jobs = [self._job_from_dict(item) for item in data.get("jobs", [])]
            self._store = CronStore(version=data.get("version", 1), jobs=jobs)
        except Exception as exc:
            # 读取或解析失败时记录警告，返回空 store 以保证服务可用性
            logger.warning("读取定时任务存储失败：{}", exc)
            self._store = CronStore()

        # 记录文件的最后修改时间，用于后续变动检测
        self._last_mtime = self.store_path.stat().st_mtime
        return self._store

    def _save_store(self) -> None:
        """把当前内存中的 store 序列化为 JSON 写回磁盘（覆盖写入）。"""
        if self._store is None:
            return

        # 确保父目录存在，再写文件
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._store.version,
            "jobs": [self._job_to_dict(job) for job in self._store.jobs],
        }
        self.store_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        # 更新缓存的文件 mtime
        self._last_mtime = self.store_path.stat().st_mtime

    def _store_changed(self) -> bool:
        """判断磁盘上的存储文件是否相对于缓存发生变化。"""
        if not self.store_path.exists():
            return self._last_mtime != 0.0
        return self.store_path.stat().st_mtime != self._last_mtime

    def _next_wake_ms(self) -> int | None:
        """计算当前所有启用任务中最早的 next_run_at_ms（返回毫秒时间戳或 None）。"""
        if self._store is None:
            return None
        next_runs = [
            job.state.next_run_at_ms
            for job in self._store.jobs
            if job.enabled and job.state.next_run_at_ms is not None
        ]
        return min(next_runs) if next_runs else None

    def _schedule_job(self, job: CronJob, now_ms: int | None = None) -> None:
        """为单个 job 刷新它的 next_run_at_ms 字段。

        - 如果任务被禁用（enabled=False），将 next_run_at_ms 设为 None。
        - 否则调用 `_compute_next_run` 计算下一次执行时间。
        """
        if not job.enabled:
            job.state.next_run_at_ms = None
            return
        job.state.next_run_at_ms = _compute_next_run(job.schedule, now_ms or _now_ms())

    def _arm_timer(self) -> None:
        """根据下次最近唤醒时间挂起一个异步定时任务（只保留一个计时器）。"""
        # 先取消已有计时器，保证内存中只存在一个待唤醒任务
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

        next_wake = self._next_wake_ms()
        # 如果服务未启动或没有待唤醒任务，则无需设置计时器
        if not self._running or next_wake is None:
            return

        # 计算延迟秒数（防止负值导致异常）
        delay = max(0.0, (next_wake - _now_ms()) / 1000)

        async def tick() -> None:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                # 如果计时器在等待期间被取消，则直接返回
                return
            if self._running:
                # 唤醒后执行到期任务处理
                await self._on_timer()

        # 使用 create_task 启动后台计时器，不阻塞当前协程
        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        """计时器触发：执行所有已到期的任务并重置持久化与计时器。"""
        store = self._load_store()
        now = _now_ms()
        # 筛选出所有启用且到期的任务
        due_jobs = [
            job
            for job in store.jobs
            if job.enabled and job.state.next_run_at_ms is not None and job.state.next_run_at_ms <= now
        ]

        # 顺序执行所有到期任务
        for job in due_jobs:
            await self._execute_job(job)

        # 执行完后持久化并为下一次待执行任务重新挂起计时器
        self._save_store()
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        """执行单条任务并根据规则更新其后续状态。

        行为：
        - 记录开始时间并调用 on_job 回调（如果存在）
        - 根据执行结果更新 state.last_status/last_error
        - 若为一次性任务（at），则根据 delete_after_run 决定是否删除或禁用
        - 若为循环任务，重新计算下一次触发时间
        """
        started_at = _now_ms()
        logger.info("开始执行定时任务：'{}'（ID：{}）", job.name, job.id)

        try:
            if self.on_job:
                # 将任务交给业务回调处理（回调可为 async 函数）
                await self.on_job(job)
            job.state.last_status = "ok"
            job.state.last_error = None
        except Exception as exc:
            # 记录错误信息并继续，避免单个任务失败导致整个调度器崩溃
            job.state.last_status = "error"
            job.state.last_error = str(exc)
            logger.error("定时任务 '{}' 执行失败：{}", job.name, exc)

        # 记录本次实际运行时间并更新时间戳
        job.state.last_run_at_ms = started_at
        job.updated_at_ms = _now_ms()

        # 对于一次性 at 类型任务，执行后根据 delete_after_run 决定是否删除
        if job.schedule.kind == "at":
            if job.delete_after_run and self._store is not None:
                # 从 store 中移除该任务
                self._store.jobs = [current for current in self._store.jobs if current.id != job.id]
            else:
                # 不删除则禁用并清除 next_run
                job.enabled = False
                job.state.next_run_at_ms = None
            return

        # 对于循环任务，刷新下一次触发时间
        self._schedule_job(job)

    @staticmethod
    def _job_from_dict(data: dict[str, Any]) -> CronJob:
        """将从磁盘读取的字典恢复为 CronJob 对象。

        注意：此处为向后兼容解析，字段采用 `get` 以防某些老数据缺少字段。
        """
        return CronJob(
            id=data["id"],
            name=data["name"],
            enabled=data.get("enabled", True),
            schedule=CronSchedule(
                kind=data["schedule"]["kind"],
                at_ms=data["schedule"].get("atMs"),
                every_ms=data["schedule"].get("everyMs"),
                expr=data["schedule"].get("expr"),
            ),
            payload=CronPayload(
                kind=data["payload"].get("kind", "agent_turn"),
                message=data["payload"].get("message", ""),
                deliver=data["payload"].get("deliver", False),
            ),
            state=CronJobState(
                next_run_at_ms=data.get("state", {}).get("nextRunAtMs"),
                last_run_at_ms=data.get("state", {}).get("lastRunAtMs"),
                last_status=data.get("state", {}).get("lastStatus"),
                last_error=data.get("state", {}).get("lastError"),
            ),
            created_at_ms=data.get("createdAtMs", 0),
            updated_at_ms=data.get("updatedAtMs", 0),
            delete_after_run=data.get("deleteAfterRun", False),
        )

    @staticmethod
    def _job_to_dict(job: CronJob) -> dict[str, Any]:
        """把 `CronJob` 序列化为字典，供写入 JSON 存储使用。"""
        return {
            "id": job.id,
            "name": job.name,
            "enabled": job.enabled,
            "schedule": {
                "kind": job.schedule.kind,
                "atMs": job.schedule.at_ms,
                "everyMs": job.schedule.every_ms,
                "expr": job.schedule.expr,
            },
            "payload": {
                "kind": job.payload.kind,
                "message": job.payload.message,
                "deliver": job.payload.deliver,
            },
            "state": {
                "nextRunAtMs": job.state.next_run_at_ms,
                "lastRunAtMs": job.state.last_run_at_ms,
                "lastStatus": job.state.last_status,
                "lastError": job.state.last_error,
            },
            "createdAtMs": job.created_at_ms,
            "updatedAtMs": job.updated_at_ms,
            "deleteAfterRun": job.delete_after_run,
        }
