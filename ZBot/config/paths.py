"""路径工具模块。"""
from pathlib import Path 

def get_config_path() -> Path:
    """
    返回当前生效的配置文件路径。
    """
    # 默认配置文件路径：用户主目录下的 .ZBot/config.json
    return Path.home() / ".ZBot" / "config.json"

def get_runtime_subdir(name: str) -> Path:
    """返回根数据文件夹下的指定子文件夹路径。"""

    return get_config_path().parent / name


def get_cli_history_path() -> Path:
    """返回命令行历史记录文件路径。"""
    return Path.home() / ".ZBot" / "history" / "cli_history.txt"
