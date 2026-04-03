"""python不能 import 文件夹 ，只能import 文件夹.文件（包），当文件夹里面有__init__时候，Python 才会把它识别为一个可导入的包，
   其他模块才能用 import nanobot.config 或 from nanobot.config import ... 来引用里面的功能。
"""

from nanobot.config.loader import get_path_config, load_config
from nanobot.config.paths import (
    get_bridge_install_dir,
    get_cli_history_path,
    get_cron_dir,
    get_data_dir,
    get_legacy_sessions_dir,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_workspace_path,
)
from nanobot.config.schema import Config

__all__ = [ # __all__ 是 Python 的模块导出白名单，作用是：当其他代码用 from 模块名 import * 导入时，只会导入 __all__ 里列出的名称；
    "Config",
    "load_config",
    "get_config_path",
    "get_data_dir",
    "get_runtime_subdir",
    "get_media_dir",
    "get_cron_dir",
    "get_logs_dir",
    "get_workspace_path",
    "get_cli_history_path",
    "get_bridge_install_dir",
    "get_legacy_sessions_dir",
]



