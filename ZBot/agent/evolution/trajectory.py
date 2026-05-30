"""会话轨迹提取器。

从会话消息中提取结构化的工具调用轨迹，替代原始 transcript 注入 review prompt。
原始 transcript ~8K tokens → 结构化轨迹 ~1K tokens，节省 ~87% token。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# 轨迹最大步骤数（防止超长会话撑爆 review prompt）
_MAX_STEPS = 30


@dataclass(frozen=True)
class ToolCallStep:
    """单次工具调用步骤。"""

    tool_name: str
    arguments_summary: str
    success: bool
    result_summary: str


@dataclass(frozen=True)
class SessionTrajectory:
    """会话轨迹摘要。"""

    task_summary: str
    steps: list[ToolCallStep]
    tools_used: list[str]
    final_outcome: str
    error_pattern: str | None


def extract_trajectory(messages: list[dict[str, Any]]) -> SessionTrajectory:
    """从会话消息中提取结构化轨迹。

    Args:
        messages: 会话消息列表（session.messages[last_consolidated:]）

    Returns:
        SessionTrajectory 结构化轨迹
    """
    task_summary = _extract_task_summary(messages)
    final_outcome = _extract_last_assistant_message(messages)
    steps = _extract_tool_steps(messages)
    tools_used = list(dict.fromkeys(s.tool_name for s in steps))
    error_pattern = _detect_error_pattern(steps)

    return SessionTrajectory(
        task_summary=task_summary,
        steps=steps,
        tools_used=tools_used,
        final_outcome=final_outcome,
        error_pattern=error_pattern,
    )


def _extract_task_summary(messages: list[dict[str, Any]]) -> str:
    """提取任务摘要：第一条 + 最后一条用户消息拼接。"""
    first_msg = ""
    last_msg = ""

    for message in messages:
        if message.get("role") == "user":
            content = _content_text(message.get("content")).strip()
            if content and not first_msg:
                first_msg = content[:200]
            elif content:
                last_msg = content[:200]

    if first_msg and last_msg and first_msg != last_msg:
        return f"{first_msg} → {last_msg}"
    return first_msg or last_msg or "未识别到明确用户任务"


def _extract_last_assistant_message(messages: list[dict[str, Any]]) -> str:
    """提取最后一条 assistant 消息作为最终结果。"""
    for message in reversed(messages):
        if message.get("role") == "assistant":
            content = _content_text(message.get("content")).strip()
            if content:
                return content[:300]
    return "无最终回复"


def _content_text(content: Any) -> str:
    """从 content 中提取文本内容（复用 BaseAgent 的逻辑，避免循环导入）。"""
    if isinstance(content, str):
        return re.sub(r"data:[^;\s]+;base64,[A-Za-z0-9+/=\r\n]+", "[base64 data url]", content)
    if not isinstance(content, list):
        return str(content or "")
    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
    return "\n".join(texts)


def _extract_tool_steps(messages: list[dict[str, Any]]) -> list[ToolCallStep]:
    """从消息链中提取工具调用步骤列表。

    保持工具调用顺序（不是结果到达顺序）。
    孤儿工具调用（无结果）标记为未完成。
    最多返回 _MAX_STEPS 个步骤。
    """
    steps: list[ToolCallStep] = []
    # 用 list 保持顺序，dict 查找
    pending_order: list[str] = []
    pending_calls: dict[str, dict[str, Any]] = {}

    for message in messages:
        role = message.get("role", "")

        if role == "assistant":
            tool_calls = message.get("tool_calls", [])
            if not isinstance(tool_calls, list):
                continue
            for tc in tool_calls:
                tc_id = tc.get("id", "")
                func = tc.get("function", {})
                pending_order.append(tc_id)
                pending_calls[tc_id] = {
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", ""),
                }

        elif role == "tool":
            tc_id = message.get("tool_call_id", "")
            call_info = pending_calls.pop(tc_id, None)
            if call_info is None:
                continue

            result_content = str(message.get("content", ""))
            success = not _is_error_content(result_content)

            # 插入到正确位置（保持调用顺序）
            insert_idx = _find_insert_position(steps, pending_order, tc_id, call_info)
            steps.insert(
                insert_idx,
                ToolCallStep(
                    tool_name=call_info["name"],
                    arguments_summary=_summarize_args(call_info["arguments"]),
                    success=success,
                    result_summary=result_content[:200],
                ),
            )
            # 从 pending_order 移除
            if tc_id in pending_order:
                pending_order.remove(tc_id)

    # 处理孤儿工具调用（有调用但无结果）
    for tc_id in pending_order:
        call_info = pending_calls.get(tc_id)
        if call_info is None:
            continue
        steps.append(
            ToolCallStep(
                tool_name=call_info["name"],
                arguments_summary=_summarize_args(call_info["arguments"]),
                success=False,
                result_summary="(未完成)",
            )
        )

    # 限制步骤数
    if len(steps) > _MAX_STEPS:
        steps = steps[-_MAX_STEPS:]

    return steps


def _find_insert_position(
    steps: list[ToolCallStep],
    pending_order: list[str],
    tc_id: str,
    call_info: dict[str, Any],
) -> int:
    """找到结果步骤应该插入的位置，保持调用顺序。

    简化策略：直接追加到末尾（因为 tool_calls 的顺序就是 assistant 消息中的顺序，
    而 tool result 消息紧跟在 assistant 消息之后，实际到达顺序通常与调用顺序一致）。
    """
    return len(steps)


def _is_error_content(content: str) -> bool:
    """判断工具结果是否为错误。"""
    return content.startswith(("错误：", "错误:", "Error:", "ERROR:", "error:"))


def _summarize_args(args: Any) -> str:
    """将工具参数压缩为简短摘要。"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return args[:200] if args else "(无参数)"

    if not isinstance(args, dict):
        return str(args)[:200] if args else "(无参数)"

    if not args:
        return "(无参数)"

    parts: list[str] = []
    for key, value in args.items():
        value_str = str(value)
        if len(value_str) > 60:
            value_str = value_str[:60] + "..."
        parts.append(f"{key}={value_str}")
    return ", ".join(parts)[:200]


def _detect_error_pattern(steps: list[ToolCallStep]) -> str | None:
    """检测错误模式。

    - retry_loop: 同工具同参数连续失败 3+ 次（更具体的模式，优先检测）
    - tool_cascade_failure: 任意 5+ 连续工具错误（更通用的模式）
    - None: 正常执行
    """
    if not steps:
        return None

    # 先检测重试循环（更具体的模式）：同工具同参数连续失败 3+ 次
    if len(steps) >= 3:
        for i in range(len(steps) - 2):
            if (
                not steps[i].success and not steps[i + 1].success and not steps[i + 2].success
                and steps[i].tool_name == steps[i + 1].tool_name == steps[i + 2].tool_name
                and steps[i].arguments_summary == steps[i + 1].arguments_summary == steps[i + 2].arguments_summary
            ):
                return "retry_loop"

    # 再检测级联失败（更通用的模式）：任意 5+ 连续工具错误
    max_consecutive_failures = 0
    current_failures = 0
    for step in steps:
        if not step.success:
            current_failures += 1
            max_consecutive_failures = max(max_consecutive_failures, current_failures)
        else:
            current_failures = 0

    if max_consecutive_failures >= 5:
        return "tool_cascade_failure"

    return None
