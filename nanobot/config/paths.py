"""【路径工具包】,专门帮 nanobot 程序 找到/创建 你电脑上的各种文件夹、文件路径,所有函数返回的都是 你电脑本地的 文件夹/文件 位置"""

from __future__ import annotations     # 让类型注解（Type Hints）变成「延迟求值的字符串」，解决提前定义的类型报错问题
from pathlib import Path
from nanobot.config.loader import get_path_config



def get_runtime_subdir(name: str) ->Path:
    """
    函数作用：通用工具函数 → 在【根数据文件夹】下，返回一个指定名字的子文件夹路径
    参数name：子文件夹的名字（比如 media、logs、cron）
    """
    
    return get_path_config().parent / name


def get_media_dir(channel: str | None = None) ->Path:
    """
    函数作用：返回【媒体文件文件夹】路径
    用途：存放聊天的图片、视频、文件、语音等媒体资源
    参数channel：可选，按渠道分文件夹（比如 WhatsApp、Telegram 各存各的）
    """
    base = get_runtime_subdir("media")
    return base / channel if channel else base


def get_cron_dir() ->Path:
    """
    函数作用：返回【定时任务文件夹】路径
    用途：存放定时任务的配置、记录（比如每天定时发消息、定时执行任务）
    """
    return get_runtime_subdir("cron")


def get_logs_dir() ->Path:
    """
    函数作用：返回【日志文件夹】路径
    用途：存放程序运行日志、报错记录（出问题时看日志找原因）
    """
    return get_runtime_subdir("logs")


def get_workspace_path(workspace: str | None = None) ->Path:
    """
    函数作用：返回【AI工作空间文件夹】路径
    用途：存放AI助手的临时文件、任务文件、工作数据
    默认位置：你电脑用户目录下的 .nanobot/workspace
    """
    path = Path(workspace).expanduser() if workspace else Path.home() / ".nanobot" / "workspace"  # expanduser--展开路径中的用户目录简写 ~
    return path


def get_cli_history_path() ->Path:
    """
    函数作用：返回【命令行历史记录文件】路径
    用途：保存你在命令行里输过的所有命令（下次按上下键能翻出来）
    位置：.nanobot/history/cli_history
    """
    return Path.home() / ".nanobot" / "history" / "cli_history"



def get_legacy_sessions_dir() -> Path:
    """
    函数作用：返回【旧版本会话文件夹】
    用途：兼容老版本nanobot的会话数据，仅用于版本迁移
    """
    return Path.home() / ".nanobot" / "sessions"


