"""
定时任务工具 (CronTool)
功能：为AI智能体提供 定时提醒、循环任务、一次性定时任务 的调度能力
支持三种调度模式：秒级循环、Cron表达式、指定ISO时间执行
"""
# 上下文变量：用于异步编程中安全管理执行状态，避免并发冲突
from contextvars import ContextVar
# 类型注解：任意类型
from typing import Any

# 继承AI工具基类，遵循框架统一的工具规范
from nanobot.agent.tools.base import Tool
# 定时任务核心服务：负责任务的存储、调度、触发、管理
from nanobot.cron.service import CronService
# 定时任务调度规则的数据结构：定义任务的执行方式
from nanobot.cron.types import CronSchedule


class CronTool(Tool):
    """
    AI智能体专用定时任务工具
    继承自Tool基类，符合框架工具标准，可被大模型直接调用
    核心功能：添加定时任务、查看任务列表、删除指定任务
    """

    def __init__(self, cron_service: CronService):
        """
        构造函数：初始化定时任务工具
        :param cron_service: 注入底层定时任务服务实例（依赖注入，解耦业务逻辑）
        """
        # 底层定时任务服务实例，真正执行任务调度的核心对象
        self._cron = cron_service
        # 消息推送的渠道（如：cli终端、web页面、discord等）
        self._channel = ""
        # 消息推送的目标会话ID（区分不同用户/聊天窗口）
        self._chat_id = ""
        # 异步安全的上下文变量：标记当前是否正在执行定时任务回调
        # 作用：禁止在定时任务内部创建新任务，防止嵌套死循环
        self._in_cron_context: ContextVar[bool] = ContextVar("cron_in_context", default=False)

    def set_context(self, channel: str, chat_id: str) -> None:
        """
        设置会话上下文（关键方法）
        作用：定时任务触发后，将提醒消息推送到正确的用户/渠道
        :param channel: 消息渠道标识
        :param chat_id: 用户会话唯一标识
        """
        self._channel = channel
        self._chat_id = chat_id

    def set_cron_context(self, active: bool):
        """
        设置定时任务执行状态标记
        :param active: True=当前正在执行定时任务回调 | False=未执行
        :return: 上下文令牌，用于后续恢复状态
        """
        return self._in_cron_context.set(active)

    def reset_cron_context(self, token) -> None:
        """
        重置定时任务上下文状态
        执行完任务后调用，恢复初始状态，避免影响后续操作
        :param token: set_cron_context 返回的上下文令牌
        """
        self._in_cron_context.reset(token)

    # ==================== 框架强制要求的工具元数据（供大模型识别和调用） ====================
    @property
    def name(self) -> str:
        """工具唯一名称，大模型通过该名称调用此工具"""
        return "cron"

    @property
    def description(self) -> str:
        """工具功能描述，让大模型理解工具的用途"""
        return "Schedule reminders and recurring tasks. Actions: add, list, remove."

    @property
    def parameters(self) -> dict[str, Any]:
        """
        工具调用参数规范（JSON Schema格式）
        作用：告诉大模型调用该工具需要传入哪些参数、参数类型、使用场景
        """
        return {
            "type": "object",
            "properties": {
                # 必选参数：执行动作（添加/列表/删除）
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],  # 限定仅支持这三个动作
                    "description": "Action to perform",
                },
                # 可选参数：提醒消息（添加任务时必填）
                "message": {"type": "string", "description": "Reminder message (for add)"},
                # 可选参数：循环间隔（秒），用于循环执行任务
                "every_seconds": {
                    "type": "integer",
                    "description": "Interval in seconds (for recurring tasks)",
                },
                # 可选参数：Cron表达式（如 0 9 * * * = 每天早上9点）
                "cron_expr": {
                    "type": "string",
                    "description": "Cron expression like '0 9 * * *' (for scheduled tasks)",
                },
                # 可选参数：IANA标准时区（仅配合Cron表达式使用）
                "tz": {
                    "type": "string",
                    "description": "IANA timezone for cron expressions (e.g. 'America/Vancouver')",
                },
                # 可选参数：ISO格式时间，用于一次性定时任务
                "at": {
                    "type": "string",
                    "description": "ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00')",
                },
                # 可选参数：任务ID（删除任务时必填）
                "job_id": {"type": "string", "description": "Job ID (for remove)"},
            },
            "required": ["action"],  # 仅action为必填参数，其余根据动作动态必填
        }

    # ==================== 工具执行入口（大模型调用后，实际执行业务逻辑） ====================
    async def execute(
        self,
        action: str,                # 执行动作：add(添加)/list(列表)/remove(删除)
        message: str = "",          # 提醒消息内容
        every_seconds: int | None = None,  # 循环秒数
        cron_expr: str | None = None,      # Cron表达式
        tz: str | None = None,             # 时区
        at: str | None = None,             # 一次性任务执行时间
        job_id: str | None = None,         # 任务ID
        **kwargs: Any,                     # 兼容额外参数，保证扩展性
    ) -> str:
        """
        异步执行工具逻辑（适配AI框架异步架构）
        根据action参数分发到对应的业务处理方法
        :return: 执行结果文本，返回给大模型/用户
        """
        # 动作1：添加定时任务
        if action == "add":
            # 安全校验：禁止在定时任务内部创建新任务，防止嵌套死循环
            if self._in_cron_context.get():
                return "Error: cannot schedule new jobs from within a cron job execution"
            # 调用私有方法创建任务
            return self._add_job(message, every_seconds, cron_expr, tz, at)
        
        # 动作2：列出所有定时任务
        elif action == "list":
            return self._list_jobs()
        
        # 动作3：删除定时任务
        elif action == "remove":
            return self._remove_job(job_id)
        
        # 未知动作，返回错误提示
        return f"Unknown action: {action}"

    # ==================== 私有方法：添加定时任务（核心业务逻辑） ====================
    def _add_job(
        self,
        message: str,               # 提醒消息
        every_seconds: int | None,  # 循环秒数
        cron_expr: str | None,      # Cron表达式
        tz: str | None,             # 时区
        at: str | None,             # 执行时间
    ) -> str:
        """
        内部方法：创建并保存定时任务
        包含完整的参数校验、调度类型判断、任务创建逻辑
        """
        # 校验1：添加任务必须填写提醒消息
        if not message:
            return "Error: message is required for add"
        
        # 校验2：必须设置会话上下文，否则无法推送消息
        if not self._channel or not self._chat_id:
            return "Error: no session context (channel/chat_id)"
        
        # 校验3：时区只能配合Cron表达式使用
        if tz and not cron_expr:
            return "Error: tz can only be used with cron_expr"
        
        # 校验4：验证时区是否为合法的IANA时区
        if tz:
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(tz)
            except (KeyError, Exception):
                return f"Error: unknown timezone '{tz}'"

        # ==================== 构建任务调度规则 ====================
        # 标记：一次性任务执行后是否自动删除（循环任务为False）
        delete_after = False
        
        # 类型1：循环任务（按秒执行，如每30秒执行一次）
        if every_seconds:
            # 转换为毫秒（底层服务使用毫秒单位）
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        
        # 类型2：Cron表达式定时任务（如每天、每周、每月）
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
        
        # 类型3：一次性定时任务（指定ISO时间执行）
        elif at:
            from datetime import datetime
            try:
                # 解析ISO格式时间字符串
                dt = datetime.fromisoformat(at)
            except ValueError:
                return f"Error: invalid ISO datetime format '{at}'. Expected format: YYYY-MM-DDTHH:MM:SS"
            # 转换为毫秒时间戳
            at_ms = int(dt.timestamp() * 1000)
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            # 一次性任务执行完成后自动删除
            delete_after = True
        
        # 校验5：必须指定一种调度方式（循环/cron/一次性）
        else:
            return "Error: either every_seconds, cron_expr, or at is required"

        # 调用底层服务，创建定时任务
        job = self._cron.add_job(
            name=message[:30],          # 任务名称：截取消息前30字符，避免过长
            schedule=schedule,           # 调度规则
            message=message,             # 完整提醒消息
            deliver=True,                # 自动推送消息给用户
            channel=self._channel,       # 推送渠道
            to=self._chat_id,            # 推送目标用户
            delete_after_run=delete_after,  # 执行后是否自动删除
        )
        
        # 返回创建成功提示，包含任务ID（用于后续删除）
        return f"Created job '{job.name}' (id: {job.id})"

    # ==================== 私有方法：查询所有定时任务 ====================
    def _list_jobs(self) -> str:
        """获取并格式化输出所有已创建的定时任务"""
        # 从底层服务获取所有任务
        jobs = self._cron.list_jobs()
        # 无任务时返回空提示
        if not jobs:
            return "No scheduled jobs."
        # 格式化任务列表：名称 + ID + 调度类型
        lines = [f"- {j.name} (id: {j.id}, {j.schedule.kind})" for j in jobs]
        return "Scheduled jobs:\n" + "\n".join(lines)

    # ==================== 私有方法：删除指定定时任务 ====================
    def _remove_job(self, job_id: str | None) -> str:
        """根据任务ID删除定时任务"""
        # 校验：删除任务必须传入任务ID
        if not job_id:
            return "Error: job_id is required for remove"
        # 执行删除操作
        if self._cron.remove_job(job_id):
            return f"Removed job {job_id}"
        # 任务ID不存在，返回错误
        return f"Job {job_id} not found"