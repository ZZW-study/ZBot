"""定时任务的数据类型定义。只有两个类：调度规则 + 完整任务。"""

from dataclasses import dataclass


@dataclass
class CronSchedule:
    """
    调度规则：定义"什么时候执行"。

    三种类型通过 kind 区分：
    - "at"   : 指定时间执行一次，用 at_ms（毫秒时间戳）
    - "every": 固定间隔重复执行，用 every_ms（间隔毫秒）
    - "cron" : 标准 cron 表达式，用 expr（如 "0 9 * * *" = 每天 9 点）
    """

    kind: str
    at_ms: int | None = None
    every_ms: int | None = None
    expr: str | None = None


@dataclass
class CronJob:
    """
    一条完整的定时任务。

    生命周期：
    - at 类型：执行一次后自动删除
    - every/cron 类型：持续运行，手动删除才停止
    """

    id: str                            # 短 ID（UUID 前 8 位）
    name: str                          # 任务名称（截取消息前 30 字符）
    message: str                       # 触发时的提醒内容
    schedule: CronSchedule             # 调度规则
    next_run_at_ms: int | None = None  # 下次执行的毫秒时间戳，None = 未安排
