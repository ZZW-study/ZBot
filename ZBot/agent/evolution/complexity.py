"""任务复杂度评分器。

从会话消息中提取信号，计算任务复杂度分数，决定是否值得触发技能进化审查。
纯数学计算，无 ML 依赖。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


# 默认阈值：低于此分数的会话不触发技能审查
DEFAULT_COMPLEXITY_THRESHOLD = 0.3

# 评分权重
_WEIGHT_TOOL_CALLS = 0.35
_WEIGHT_UNIQUE_TOOLS = 0.20
_WEIGHT_MESSAGES = 0.15
_WEIGHT_ERROR_RATE = 0.15
_WEIGHT_USER_TURNS = 0.15

# 归一化上限（针对个人 agent 的典型任务规模调整）
_CAP_TOOL_CALLS = 10.0
_CAP_UNIQUE_TOOLS = 8.0
_CAP_MESSAGES = 15.0
_CAP_USER_TURNS = 5.0


@dataclass(frozen=True)
class TaskComplexity:
    """任务复杂度评估结果。"""

    score: float
    tool_call_count: int
    unique_tools: int
    message_count: int
    error_count: int
    user_turn_count: int
    should_review: bool


def compute_complexity(
    messages: list[dict[str, Any]],
    threshold: float = DEFAULT_COMPLEXITY_THRESHOLD,
) -> TaskComplexity:
    """从会话消息列表计算任务复杂度。

    Args:
        messages: 会话消息列表（session.messages[last_consolidated:]）
        threshold: 触发审查的最低分数阈值

    Returns:
        TaskComplexity 评估结果
    """
    tool_call_count = 0
    unique_tools: set[str] = set()
    error_count = 0
    user_turn_count = 0

    for message in messages:
        role = message.get("role", "")

        if role == "user":
            user_turn_count += 1

        elif role == "assistant":
            tool_calls = message.get("tool_calls", [])
            if not isinstance(tool_calls, list):
                continue
            for tc in tool_calls:
                tool_call_count += 1
                func = tc.get("function", {})
                name = func.get("name", "")
                if name:
                    unique_tools.add(name)

        elif role == "tool":
            content = str(message.get("content", ""))
            if content.startswith(("错误：", "错误:", "Error:", "ERROR:", "error:")):
                error_count += 1

    message_count = len(messages)

    score = (
        min(tool_call_count / _CAP_TOOL_CALLS, 1.0) * _WEIGHT_TOOL_CALLS
        + min(len(unique_tools) / _CAP_UNIQUE_TOOLS, 1.0) * _WEIGHT_UNIQUE_TOOLS
        + min(message_count / _CAP_MESSAGES, 1.0) * _WEIGHT_MESSAGES
        + min(error_count / max(tool_call_count, 1), 1.0) * _WEIGHT_ERROR_RATE
        + min(user_turn_count / _CAP_USER_TURNS, 1.0) * _WEIGHT_USER_TURNS
    )

    return TaskComplexity(
        score=round(score, 4),
        tool_call_count=tool_call_count,
        unique_tools=len(unique_tools),
        message_count=message_count,
        error_count=error_count,
        user_turn_count=user_turn_count,
        should_review=score >= threshold,
    )
