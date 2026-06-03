"""消息格式化辅助函数模块。"""

from typing import Any


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
