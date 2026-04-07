"""定时任务的数据类型定义（带中文注释，帮助初学者理解各字段含义）。"""

from dataclasses import dataclass, field


@dataclass
class CronSchedule:
    """定时任务的调度规则结构：

    - `kind`：调度类型，三种可选值："at"（在某个时间点执行）、
      "every"（按固定间隔循环执行）、"cron"（支持 cron 表达式）。
    - `at_ms`：当 `kind=="at"` 时，指定的毫秒时间戳（UTC 毫秒）。
    - `every_ms`：当 `kind=="every"` 时，指定循环的间隔（毫秒）。
    - `expr`：当 `kind=="cron"` 时，使用的 cron 表达式字符串。
    """
    kind: str  # "at" / "every" / "cron"
    at_ms: int | None = None
    every_ms: int | None = None
    expr: str | None = None


@dataclass
class CronPayload:
    """任务要执行的负载内容（业务侧定义的执行语义）。

    当前系统默认把任务 payload 封装成简单的消息（`message`）和
    是否要把结果直接投递给用户（`deliver`）。未来可扩展为更复杂的结构。
    """
    message: str = ""       # 任务执行时传递的文本消息
    deliver: bool = False    # 是否在任务触发时把消息直接推送给用户/渠道


@dataclass
class CronJobState:
    """记录任务的运行状态信息：下次运行时间、上次运行时间与错误状态等。"""
    next_run_at_ms: int | None = None  # 下次计划运行的毫秒时间戳（None 表示未安排）
    last_run_at_ms: int | None = None  # 上次实际执行时间（毫秒）
    last_status: str | None = None     # 上次执行状态，常见值："ok"、"error"
    last_error: str | None = None      # 上次执行的错误信息（若有）


@dataclass
class CronJob:
    """表示一条完整的定时任务。

    包含：任务 ID、名称、是否启用、调度规则（schedule）、执行负载（payload）、
    当前运行状态（state）以及创建/更新时间戳和是否在执行后删除的标志。
    """
    id: str
    name: str
    enabled: bool = True
    # 调度规则，默认使用一个 every 类型的 schedule（间隔任务）
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind="every"))
    payload: CronPayload = field(default_factory=CronPayload)
    state: CronJobState = field(default_factory=CronJobState)
    created_at_ms: int = 0
    updated_at_ms: int = 0
    delete_after_run: bool = False


@dataclass
class CronStore:
    """任务存储结构：用于持久化到磁盘的顶层容器。

    - `version`：用于兼容将来的存储格式升级。
    - `jobs`：当前存储的所有 `CronJob` 列表。
    """
    version: int = 1
    jobs: list[CronJob] = field(default_factory=list)
