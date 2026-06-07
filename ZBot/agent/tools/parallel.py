# 工具智能并发辅助模块。
# 部分工具可安全并行（只读、独立路径），部分必须保持顺序（有副作用、依赖上下文）。

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ZBot.providers.base import ToolCallRequest


# 可安全并行的只读工具白名单。
# 这些工具不会修改任何状态，可以并行调用。
_PARALLEL_SAFE_TOOLS: frozenset[str] = frozenset({
    # 文件系统（只读）
    "read_file",
    "list_dir",
    # 搜索
    "search_files",
    "grep_search",
    "glob_search",
    # 网络（只读）
    "web_search",
    "web_fetch",
    # 技能管理（只读）
    "skill_view",
    "skills_list",
    "skill_read",
    # 会话查询
    "session_search",
    # 内存查询
    "memory_search",
    # 任务/对话进度查看
    "todo_read",
    # 日志查看
    "log_read",
})

# 永远不平行的工具黑名单。
# 这些工具要么需要与用户交互，要么会产生不可预期的副作用。
_NEVER_PARALLEL_TOOLS: frozenset[str] = frozenset({
    "create_sub_agent",  # 启动子代理，本身就是并行调度，不应该和其他工具混着
    "shell",  # 终端命令，可能有副作用
    "exec",  # 同上（别名）
    "write_file",  # 写文件
    "edit_file",  # 编辑文件
    "patch_file",  # patch 文件
    "create_skill",  # 创建技能
    "patch_skill",  # 修改技能
    "delete_skill",  # 删除技能
    "cron",  # 定时任务
})


@dataclass(frozen=True, slots=True)
class PartitionedToolCalls:
    """
    划分后的工具调用。

    Attributes:
        safe: 可并行的工具调用（保留原始顺序）。
        unsafe: 需顺序执行的工具调用（保留原始顺序）。
    """

    safe: list["ToolCallRequest"]
    unsafe: list["ToolCallRequest"]

    @property
    def has_parallel_work(self) -> bool:
        """是否有可以并行的工具。"""
        return len(self.safe) >= 2

    @property
    def is_all_unsafe(self) -> bool:
        """是否全部不可并行的工具。"""
        return len(self.safe) == 0


def should_parallelize_batch(
    tool_calls: list["ToolCallRequest"],
) -> bool:
    """
    判断一批工具调用是否可以并行。

    严格条件（与 hermes-agent 一致）：
    1. 至少 2 个工具调用（1 个无需 gather，await 更快）
    2. 任何一个在黑名单中 → 不并行
    3. 所有工具都在白名单中 → 并行

    Args:
        tool_calls: LLM 一次响应中返回的全部工具调用。

    Returns:
        True 表示可以并行；False 表示应顺序执行。
    """
    if len(tool_calls) < 2:
        return False

    tool_names = [tc.name for tc in tool_calls]

    # 黑名单优先：任何一个在黑名单中就走顺序
    if any(name in _NEVER_PARALLEL_TOOLS for name in tool_names):
        return False

    # 所有工具都在白名单中才并行
    return all(name in _PARALLEL_SAFE_TOOLS for name in tool_names)


def partition_tool_calls(
    tool_calls: list["ToolCallRequest"],
) -> PartitionedToolCalls:
    """
    把工具调用划分为可并行 / 须顺序两组。

    保持原始顺序，调用者负责按原始顺序合并结果。

    Args:
        tool_calls: LLM 一次响应中返回的全部工具调用。

    Returns:
        PartitionedToolCalls，包含 safe 和 unsafe 两个子列表。
    """
    if not tool_calls:
        return PartitionedToolCalls(safe=[], unsafe=[])

    safe: list["ToolCallRequest"] = []
    unsafe: list["ToolCallRequest"] = []
    for tc in tool_calls:
        if tc.name in _NEVER_PARALLEL_TOOLS:
            unsafe.append(tc)
        elif tc.name in _PARALLEL_SAFE_TOOLS:
            safe.append(tc)
        else:
            # 未知工具为安全起见，默认顺序
            unsafe.append(tc)
    return PartitionedToolCalls(safe=safe, unsafe=unsafe)


__all__ = [
    "PartitionedToolCalls",
    "_PARALLEL_SAFE_TOOLS",
    "_NEVER_PARALLEL_TOOLS",
    "partition_tool_calls",
    "should_parallelize_batch",
]