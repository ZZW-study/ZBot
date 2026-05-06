"""通用辅助函数模块。"""
import re
from pathlib import Path
from typing import Any
import json
# 文件名中不允许出现的不安全字符（Windows/Unix 系统保留字符）
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def ensure_dir(path: Path) -> Path:
    """确保目录存在，如果不存在则递归创建。"""
    # parents=True 递归创建所有缺失的父目录
    # exist_ok=True 目录已存在时不报错
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """将文件名中的不安全字符替换为下划线。"""
    # 用正则将所有不安全字符替换为下划线，并去除首尾空白
    return _UNSAFE_CHARS.sub("_", name).strip()


def ensure_workspace_dirs(workspace: Path) ->None:
    """创建工作区所需的必要目录。"""
    dirs = [
        workspace / "memory",
        workspace / "sessions",
        workspace / "skills",
    ]
    for d in dirs:
        if not d.exists():
            ensure_dir(d)

def format_messages(messages: list[dict[str, Any]]) -> list[str]:
    """把消息列表格式化成适合归档模型阅读的转录文本。每条消息的格式：[timestamp] ROLE[tools_used]: content"""
    lines: list[str] = []
    for message in messages:
        content = message.get("content")
        if not content:
            continue  # 跳过空内容消息
        # 获取使用的工具列表（如果有）
        tools = message.get("tools_used") or []
        tool_suffix = f" [使用工具: {','.join(tools)}]" if tools else ""
        # 截取时间戳的前 16 个字符（YYYY-MM-DD HH:MM）
        timestamp = str(message.get("timestamp", "?"))[:16]
        # 构造格式化行：[2024-01-15 14:30] USER [使用工具: web_search]: 用户消息内容
        lines.append(f"[{timestamp}] {message.get('role', 'unknown').upper()}{tool_suffix}: {content}")
    return lines


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