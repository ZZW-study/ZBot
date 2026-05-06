"""定时任务工具：让 AI 能创建、查看、删除定时任务。

防嵌套机制：
    定时任务回调执行期间，_in_cron_context 为 True。
    此时 AI 调用 add 会被拒绝，防止在任务里创建任务导致死循环。
    commands.py 的回调负责设置/重置这个标记。
"""

from contextvars import ContextVar
from datetime import datetime
from typing import Any

from ZBot.agent.tools.base import Tool
from ZBot.cron.service import BEIJING_TZ, CronService
from ZBot.cron.types import CronSchedule

# 回调执行期间为 True，阻止在回调内创建新任务
_in_cron_context: ContextVar[bool] = ContextVar("cron_in_context", default=False)


def set_cron_context(active: bool):
    """设置防嵌套标记，返回令牌（用于后续 reset）。"""
    return _in_cron_context.set(active)


def reset_cron_context(token) -> None:
    """重置防嵌套标记。"""
    _in_cron_context.reset(token)


class CronTool(Tool):
    """AI 可调用的定时任务工具，支持 add / list / remove 三个动作。"""

    def __init__(self, cron_service: CronService):
        self._cron = cron_service

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return "创建、查看和删除定时提醒或循环任务。支持 add、list、remove 三种动作。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],
                    "description": "要执行的动作：add、list 或 remove。",
                },
                "message": {"type": "string", "description": "提醒内容（action=add 时必填）。"},
                "every_seconds": {"type": "integer", "description": "循环任务的间隔秒数。"},
                "cron_expr": {"type": "string", "description": "北京时间的 Cron 表达式，例如 '0 9 * * *'。"},
                "at": {"type": "string", "description": "北京时间的 ISO 时间，例如 '2026-02-12T10:30:00'。"},
                "job_id": {"type": "string", "description": "任务 ID（action=remove 时必填）。"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")

        if action == "add":
            # 防嵌套：定时任务执行期间禁止创建新任务
            if _in_cron_context.get():
                return "错误：不能在定时任务执行过程中再次创建新的定时任务。"
            return self._add_job(
                message=kwargs.get("message", ""),
                every_seconds=kwargs.get("every_seconds"),
                cron_expr=kwargs.get("cron_expr"),
                at=kwargs.get("at"),
            )

        if action == "list":
            return self._list_jobs()

        if action == "remove":
            return self._remove_job(kwargs.get("job_id"))

        return f"错误：未知动作 {action}"

    def _add_job(self, message: str, every_seconds: int | None, cron_expr: str | None, at: str | None) -> str:
        """根据参数构造调度规则，调用 CronService 创建任务。"""
        if not message:
            return "错误：创建任务时必须提供提醒内容。"

        # 三种调度方式互斥，优先级：every > cron > at
        if every_seconds:
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr)
        elif at:
            try:
                dt = datetime.fromisoformat(at)
            except ValueError:
                return f"错误：时间格式无效：{at}。正确格式示例：YYYY-MM-DDTHH:MM:SS"
            # 没有时区信息默认当北京时间处理
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BEIJING_TZ)
            else:
                dt = dt.astimezone(BEIJING_TZ)
            schedule = CronSchedule(kind="at", at_ms=int(dt.timestamp() * 1000))
        else:
            return "错误：必须提供 every_seconds、cron_expr 或 at 其中之一。"

        job = self._cron.add_job(name=message[:30], schedule=schedule, message=message)
        return f"已创建任务 {job.name}（ID：{job.id}）"

    def _list_jobs(self) -> str:
        jobs = self._cron.list_jobs()
        if not jobs:
            return "当前没有已安排的定时任务。"
        lines = [f"- {j.name}（ID：{j.id}，调度：{j.schedule.kind}）" for j in jobs]
        return "当前定时任务列表：\n" + "\n".join(lines)

    def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return "错误：删除任务时必须提供 job_id。"
        if self._cron.remove_job(job_id):
            return f"已删除任务：{job_id}"
        return f"错误：未找到任务 {job_id}"
