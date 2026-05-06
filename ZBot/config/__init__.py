"""配置模块"""

from ZBot.config.loader import load_config
from ZBot.config.paths import (
    get_cli_history_path,
    get_config_path,
    get_runtime_subdir,
)
from ZBot.config.schema import Config

__all__ = [
    "Config",
    "load_config",
    "get_config_path",
    "get_runtime_subdir",
    "get_cli_history_path",
]
