"""任务复杂度评分器。

从会话消息中提取信号，计算任务复杂度分数，决定是否值得触发技能进化审查。
纯数学计算，无 ML 依赖。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 默认阈值：低于此分数的会话不触发技能审查
DEFAULT_COMPLEXITY_THRESHOLD = 0.50

# 至少调用这么多次工具，才允许触发技能审查
_MIN_TOOL_CALLS_FOR_REVIEW = 12

# 评分权重
_WEIGHT_TOOL_CALLS = 0.50
_WEIGHT_UNIQUE_TOOLS = 0.30
_WEIGHT_ERROR_RATE = 0.20

# 归一化上限
_CAP_TOOL_CALLS = 12.0
_CAP_UNIQUE_TOOLS = 4.0


@dataclass(frozen=True)
class TaskComplexity:
    """任务复杂度评估结果。"""

    score: float
    tool_call_count: int
    unique_tools: int
    error_count: int
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

    for message in messages:
        role = message.get("role", "")

        if role == "assistant":
            tool_calls = message.get("tool_calls", [])
            if not isinstance(tool_calls, list):
                continue

            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue

                tool_call_count += 1

                func = tc.get("function", {})
                if not isinstance(func, dict):
                    continue

                name = func.get("name", "")
                if name:
                    unique_tools.add(str(name))

        elif role == "tool":
            content = str(message.get("content", ""))
            if content.startswith(("错误：", "错误:", "Error:", "ERROR:", "error:")):
                error_count += 1

    tool_call_score = min(tool_call_count / _CAP_TOOL_CALLS, 1.0)
    unique_tool_score = min(len(unique_tools) / _CAP_UNIQUE_TOOLS, 1.0)
    error_rate_score = min(error_count / max(tool_call_count, 1), 1.0)

    score = (
        tool_call_score * _WEIGHT_TOOL_CALLS
        + unique_tool_score * _WEIGHT_UNIQUE_TOOLS
        + error_rate_score * _WEIGHT_ERROR_RATE
    )

    should_review = tool_call_count >= _MIN_TOOL_CALLS_FOR_REVIEW and score >= threshold

    return TaskComplexity(
        score=round(score, 4),
        tool_call_count=tool_call_count,
        unique_tools=len(unique_tools),
        error_count=error_count,
        should_review=should_review,
    )
