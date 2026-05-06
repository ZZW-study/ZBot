from celery import Celery
from celery.schedules import crontab

# Celery核心实例
app = Celery(
    "agent",
    broker="amqp://guest:guest@localhost:5672//",
    backend="db+sqlite:///celery_results.db"  # 任务执行结果存储
)

# 定时任务配置
app.conf.beat_schedule = {
    "weekly-memory-task": {
        "task": "ZBot.tasks.task.weekly_daily_memory_operate",
        "schedule": crontab(hour=22, minute=0, day_of_week="friday"),
    },
}

# 全局配置（生产环境标准配置）
app.conf.update(
    timezone="Asia/Shanghai",  # 时区设为上海（北京时间）
    task_serializer="json",    # 任务参数用 JSON 序列化（通用、可读性好）
    task_acks_late=True,       # 任务执行完再确认，worker 挂了任务会重跑，防丢失
    worker_prefetch_multiplier=1,  # 每个 worker 一次只拿 1 个任务，公平分配、防堆积
    task_track_started=True,  # 记录任务 STARTED 状态（能看到任务正在执行）
    result_expires=3600,      # 任务执行结果只保留 1 小时，过期自动清理
    worker_cancel_long_running_tasks_on_connection_loss=True
                               # 连接断开时，自动取消正在跑的长任务，避免僵死
)

# 自动发现任务（确保能找到task.py里的任务）
app.autodiscover_tasks(["ZBot.tasks"])

