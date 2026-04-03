"""基于 Python 异步框架 (asyncio) 实现的定时任务调度服务，
专门用于调度 Agent 智能体的任务。支持指定时间执行、固定间隔循环、Cron 表达式三种定时模式，
任务数据持久化到 JSON 文件，提供任务增删改查、手动执行、启用禁用等完整管理能力。"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine
from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore


# -------------------------- 工具函数 --------------------------
def _now_ms() ->int:
    """
    获取当前时间的【毫秒级时间戳】
    """
    return int(time.time()*1000)


def _compute_next_run(schedule: CronSchedule,now_ms: int) ->int | None:
    """
    核心函数：计算任务【下一次执行的时间（毫秒）】
    :param schedule: 任务调度规则
    :param now_ms: 当前时间（毫秒）
    :return: 下次执行时间戳 | None（无下次执行）
    """

    # 模式1：指定时间执行（一次性任务，比如2025-01-01 12:00执行）
    if schedule.kind == "at":
        # 只有指定时间 > 当前时间，才有效
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    # 模式2：固定间隔循环执行（比如每5秒执行一次）
    if schedule.kind == "every":
        # 间隔时间无效（<=0），返回None
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # 下次执行时间 = 当前时间 + 间隔毫秒
        return now_ms + schedule.every_ms

    # 模式3：Cron表达式执行（比如 0 0 * * * 每天凌晨执行）
    if schedule.kind == "cron" and schedule.expr:
        try:
            from zoneinfo import ZoneInfo   # 时区处理库
            from croniter import croniter   # Cron表达式解析库
            base_time = now_ms / 1000       # 毫秒转秒（时间戳基准）
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo   # 设置时区：优先用任务指定的时区，否则用系统本地时区
            base_dt = datetime.fromtimestamp(base_time, tz=tz)  # 转换为带时区的时间对象
            cron = croniter(schedule.expr, base_dt)    # 解析Cron表达式
            next_dt = cron.get_next(datetime)          # 计算下一次执行时间
            return int(next_dt.timestamp() * 1000)     # 转回毫秒级时间戳
        except Exception:
            return None

    return None


def _validate_schedule_for_add(schedule: CronSchedule) -> None:
    """
    添加任务前的【调度规则校验】
    避免创建无法执行的无效任务
    """
    # 校验1：时区(tz)只能用于Cron表达式模式
    if schedule.tz and schedule.kind != "cron":
        raise ValueError("tz can only be used with cron schedules")

    # 校验2：如果是Cron模式+指定时区，校验时区是否合法
    if schedule.kind == "cron" and schedule.tz:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(schedule.tz)
        except Exception:
            raise ValueError(f"unknown timezone '{schedule.tz}'") from None

class CronService:
    """定时任务服务类：管理所有任务的创建、执行、存储、调度"""

    def __init__(
        self,
        store_path: Path,                                                            # 任务持久化的JSON文件路径
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None   # 任务执行回调函数
    ):                              
        self.store_path = store_path                       # 任务存储文件路径
        self.on_job = on_job                               # 任务执行时的回调（任务触发后执行的业务逻辑）
        self._store: CronStore | None = None               # 内存中的任务存储对象
        self._last_mtime: float = 0.0                      # 任务文件的最后修改时间（用于检测外部修改自动重载）
        self._timer_task: asyncio.Task | None = None       # 异步定时器任务（核心：非阻塞的定时触发器）
        self._running = False                              # 服务运行状态标记

    def _load_store(self) -> CronStore:
        """
        从磁盘【加载任务数据】到内存
        支持：外部修改JSON文件后，自动重新加载
        """
        # 如果内存已有任务，且文件被外部修改，则清空内存，重新加载
        if self._store and self.store_path.exists():
            mtime = self.store_path.stat().st_mtime
            if mtime != self._last_mtime:
                logger.info("Cron: jobs.json modified externally, reloading")
                self._store = None
        # 内存已有有效数据，直接返回
        if self._store:
            return self._store

        # 从JSON文件读取并解析任务
        if self.store_path.exists():
            try:
                # 读取文件内容
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                jobs = []
                # 遍历JSON数据，转换为CronJob对象
                for j in data.get("jobs", []):
                    jobs.append(CronJob(
                        id=j["id"],  # 任务ID
                        name=j["name"],  # 任务名称
                        enabled=j.get("enabled", True),  # 是否启用
                        schedule=CronSchedule(  # 调度规则
                            kind=j["schedule"]["kind"],
                            at_ms=j["schedule"].get("atMs"),
                            every_ms=j["schedule"].get("everyMs"),
                            expr=j["schedule"].get("expr"),
                            tz=j["schedule"].get("tz"),
                        ),
                        payload=CronPayload(  # 任务执行的内容（给Agent的指令）
                            kind=j["payload"].get("kind", "agent_turn"),
                            message=j["payload"].get("message", ""),
                            deliver=j["payload"].get("deliver", False),
                            channel=j["payload"].get("channel"),
                            to=j["payload"].get("to"),
                        ),
                        state=CronJobState(  # 任务状态
                            next_run_at_ms=j.get("state", {}).get("nextRunAtMs"),
                            last_run_at_ms=j.get("state", {}).get("lastRunAtMs"),
                            last_status=j.get("state", {}).get("lastStatus"),
                            last_error=j.get("state", {}).get("lastError"),
                        ),
                        created_at_ms=j.get("createdAtMs", 0),  # 创建时间
                        updated_at_ms=j.get("updatedAtMs", 0),  # 更新时间
                        delete_after_run=j.get("deleteAfterRun", False),  # 执行后是否删除
                    ))
                self._store = CronStore(jobs=jobs)
            except Exception as e:
                # 加载失败（文件损坏），创建空存储
                logger.warning("Failed to load cron store: {}", e)
                self._store = CronStore()
        else:
            # 文件不存在，创建空存储
            self._store = CronStore()

        return self._store

    def _save_store(self) -> None:
        """
        将内存中的任务【保存到磁盘JSON文件】
        实现任务持久化，重启服务后任务不丢失
        """
        if not self._store:
            return

        # 自动创建文件所在的目录（不存在则创建）
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        # 序列化任务数据为JSON格式
        data = {
            "version": self._store.version,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule": {
                        "kind": j.schedule.kind,
                        "atMs": j.schedule.at_ms,
                        "everyMs": j.schedule.every_ms,
                        "expr": j.schedule.expr,
                        "tz": j.schedule.tz,
                    },
                    "payload": {
                        "kind": j.payload.kind,
                        "message": j.payload.message,
                        "deliver": j.payload.deliver,
                        "channel": j.payload.channel,
                        "to": j.payload.to,
                    },
                    "state": {
                        "nextRunAtMs": j.state.next_run_at_ms,
                        "lastRunAtMs": j.state.last_run_at_ms,
                        "lastStatus": j.state.last_status,
                        "lastError": j.state.last_error,
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in self._store.jobs
            ]
        }

        # 写入文件（格式化JSON，支持中文）
        self.store_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # 更新文件最后修改时间
        self._last_mtime = self.store_path.stat().st_mtime
    
    async def start(self) -> None:
        """
        启动定时任务服务（异步方法）
        1. 标记服务运行中
        2. 加载任务
        3. 重新计算所有任务的下次执行时间
        4. 保存状态
        5. 启动定时器
        """
        self._running = True
        self._load_store()
        self._recompute_next_runs()
        self._save_store()
        self._arm_timer()
        logger.info("Cron service started with {} jobs", len(self._store.jobs if self._store else []))

    def stop(self) -> None:
        """
        停止定时任务服务
        1. 标记服务停止
        2. 取消异步定时器
        """
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    def _recompute_next_runs(self) -> None:
        """
        重新计算【所有启用任务】的下次执行时间
        服务启动/任务修改时调用
        """
        if not self._store:
            return
        now = _now_ms()
        for job in self._store.jobs:
            if job.enabled:
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)

    def _get_next_wake_ms(self) -> int | None:
        """
        获取【最早的任务执行时间】
        定时器根据这个时间决定何时唤醒
        """
        if not self._store:
            return None
        # 筛选所有启用任务的下次执行时间
        times = [j.state.next_run_at_ms for j in self._store.jobs
                 if j.enabled and j.state.next_run_at_ms]
        # 返回最小值（最早执行时间）
        return min(times) if times else None

    def _arm_timer(self) -> None:
        """
        【核心】设置异步定时器
        1. 取消旧定时器
        2. 计算距离最早任务的延迟时间
        3. 创建新的异步定时器任务
        """
        # 取消已存在的定时器（避免重复触发）
        if self._timer_task:
            self._timer_task.cancel()

        # 获取最早执行时间
        next_wake = self._get_next_wake_ms()
        if not next_wake or not self._running:
            return

        # 计算延迟时间（秒），最小为0（避免负延迟）
        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000

        # 定义定时器触发后的执行逻辑
        async def tick():
            await asyncio.sleep(delay_s)  # 异步等待（非阻塞）
            if self._running:
                await self._on_timer()  # 执行到期任务

        # 创建异步任务
        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        """
        定时器触发：执行所有【到期的任务】
        1. 重新加载任务（防止外部修改）
        2. 筛选到期任务
        3. 逐个执行任务
        4. 保存状态
        5. 重新设置定时器
        """
        self._load_store()
        if not self._store:
            return

        now = _now_ms()
        # 筛选：启用 + 下次执行时间 <= 当前时间 = 到期任务
        due_jobs = [
            j for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]

        # 执行所有到期任务
        for job in due_jobs:
            await self._execute_job(job)

        # 保存任务状态
        self._save_store()
        # 重新设置定时器（下一轮调度）
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        """
        执行【单个任务】的核心逻辑
        1. 记录执行日志
        2. 调用业务回调函数
        3. 更新任务执行状态（成功/失败）
        4. 处理一次性/循环任务
        """
        start_ms = _now_ms()
        logger.info("Cron: executing job '{}' ({})", job.name, job.id)

        try:
            response = None
            # 如果设置了回调函数，执行业务逻辑
            if self.on_job:
                response = await self.on_job(job)

            # 任务执行成功：更新状态
            job.state.last_status = "ok"
            job.state.last_error = None
            logger.info("Cron: job '{}' completed", job.name)

        except Exception as e:
            # 任务执行失败：记录错误
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error("Cron: job '{}' failed: {}", job.name, e)

        # 更新任务最后执行时间、更新时间
        job.state.last_run_at_ms = start_ms
        job.updated_at_ms = _now_ms()

        # 处理【一次性任务】（at模式）
        if job.schedule.kind == "at":
            if job.delete_after_run:
                # 执行后删除任务
                self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
            else:
                # 执行后禁用任务
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            # 循环任务（every/cron）：重新计算下次执行时间
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())

    # ========================== 公共API（给外部调用的接口） ==========================
    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """列出所有任务（默认只显示启用的，可选择包含禁用的）"""
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        # 按下次执行时间排序
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))

    def add_job(
        self,
        name: str,  # 任务名称
        schedule: CronSchedule,  # 调度规则
        message: str,  # 任务执行消息
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,  # 执行后是否删除
    ) -> CronJob:
        """添加新任务"""
        store = self._load_store()
        # 校验调度规则
        _validate_schedule_for_add(schedule)
        now = _now_ms()

        # 创建任务对象（生成8位唯一ID）
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(
                kind="agent_turn",
                message=message,
                deliver=deliver,
                channel=channel,
                to=to,
            ),
            state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now)),
            created_at_ms=now,
            updated_at_ms=now,
            delete_after_run=delete_after_run,
        )

        # 添加到内存、保存文件、重启定时器
        store.jobs.append(job)
        self._save_store()
        self._arm_timer()

        logger.info("Cron: added job '{}' ({})", name, job.id)
        return job

    def remove_job(self, job_id: str) -> bool:
        """根据ID删除任务"""
        store = self._load_store()
        before = len(store.jobs)
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before

        if removed:
            self._save_store()
            self._arm_timer()
            logger.info("Cron: removed job {}", job_id)

        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """启用/禁用任务"""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                job.enabled = enabled
                job.updated_at_ms = _now_ms()
                # 启用：重新计算下次执行时间；禁用：清空下次执行时间
                if enabled:
                    job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                else:
                    job.state.next_run_at_ms = None
                self._save_store()
                self._arm_timer()
                return job
        return None

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """手动执行任务（force=True可强制执行禁用的任务）"""
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                if not force and not job.enabled:
                    return False
                await self._execute_job(job)
                self._save_store()
                self._arm_timer()
                return True
        return False

    def status(self) -> dict:
        """获取服务状态（是否运行、任务数量、下次唤醒时间）"""
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }