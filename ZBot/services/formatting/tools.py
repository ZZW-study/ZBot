"""工具参数格式化辅助函数模块。"""

import json
from typing import Any


def normalize_tool_args(arguments: Any) -> dict[str, Any] | None:
    """把模型返回的工具参数统一规整成字典。"""
    # 如果是字符串，尝试 JSON 解析
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None

    # 如果是列表，取第一个字典元素
    if isinstance(arguments, list):
        arguments = arguments[0] if arguments and isinstance(arguments[0], dict) else None

    # 确保返回字典类型
    return arguments if isinstance(arguments, dict) else None
