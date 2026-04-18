"""路径工具模块。
本模块封装了 ZBot 中常用的路径计算逻辑，
统一管理工作区、配置和数据子目录的位置，
避免各模块重复硬编码路径。
"""
from pathlib import Path 

def get_path_config() -> Path:
    """
    返回当前生效的配置文件路径。
    """
    # 默认配置文件路径：用户主目录下的 .ZBot/config.json
    return Path.home() / ".ZBot" / "config.json"

def get_runtime_subdir(name: str) -> Path:
    """返回根数据文件夹下的指定子文件夹路径。"""

    return get_path_config().parent / name


def get_workspace_path(workspace: str | None = None) -> Path:
    """返回 AI 工作空间路径。

    工作空间是 ZBot 存放所有数据（会话、记忆、技能等）的根目录。
    """
    # 如果用户指定了路径，展开 ~ 后直接返回
    if workspace:
        return Path(workspace).expanduser()
    # 否则返回默认工作区路径：家目录/.ZBot/workspace
    return Path.home() / ".ZBot" / "workspace"


def get_cli_history_path() -> Path:
    """返回命令行历史记录文件路径。

    该文件用于存储用户在 CLI 交互模式下输入过的命令历史，
    方便使用上下键快速翻阅之前的输入内容。
    """
    return Path.home() / ".ZBot" / "history" / "cli_history.txt"
