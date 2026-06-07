# -*- coding: utf-8 -*-
"""构造一个真实可用的 ``ToolRegistry`` 供评测脚本使用。

这里注册的工具全部来自 ZBot 的真实源码（``ZBot.agent.tools.*``），
与生产环境保持一致，保证 Agent 调用时的行为真实可信。
"""

from __future__ import annotations

from pathlib import Path

from ZBot.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from ZBot.agent.tools.registry import ToolRegistry
from ZBot.agent.tools.search import glob_search, grep_search
from ZBot.agent.tools.shell import ExecTool


# 评测白名单：Agent 只能使用这一组工具，便于做"工具是否被调用"的判定
EVAL_TOOL_NAMES: tuple[str, ...] = (
    "read_file",
    "list_dir",
    "glob_search",
    "grep_search",
    "exec",
    "write_file",
    "edit_file",
)


def build_registry(workspace: Path) -> ToolRegistry:
    """返回一个绑定到 ``workspace`` 的真实 ``ToolRegistry``。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool(workspace=workspace, allowed_dir=workspace))
    registry.register(ListDirTool(workspace=workspace, allowed_dir=workspace))
    registry.register(
        ExecTool(working_dir=str(workspace), restrict_to_workspace=True)
    )
    registry.register(glob_search(workspace=workspace, allowed_dir=workspace))
    registry.register(grep_search(workspace=workspace, allowed_dir=workspace))
    registry.register(WriteFileTool(workspace=workspace, allowed_dir=workspace))
    registry.register(EditFileTool(workspace=workspace, allowed_dir=workspace))
    return registry