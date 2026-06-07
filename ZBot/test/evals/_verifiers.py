# -*- coding: utf-8 -*-
"""ZBot 评测的任务完成判定器。

每个 verifier 会观察一次 Agent 运行的副作用（写到工作区的新文件、
实际调用过的工具、最终回复文本等），并返回 ``(passed, reason)``。
一个任务可以声明多个 verifier，按顺序判定，第一个命中即视为完成。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    """读取文本内容，文件不存在时返回空串。"""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def verify_file_exists(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定工作区中是否存在指定文件。"""
    path = workspace / spec["path"]
    return (path.exists(), f"文件 {spec['path']} 存在={path.exists()}")


def verify_file_contains(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定指定文件是否包含期望的字符串。"""
    path = workspace / spec["path"]
    text = _read_text(path)
    needle = spec.get("contains", "")
    passed = needle in text
    return (passed, f"文件 {spec['path']} 包含 {needle!r} -> {passed}")


def verify_file_count(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定指定文件的非空行数是否等于期望值。"""
    path = workspace / spec["path"]
    text = _read_text(path)
    count = len([line for line in text.splitlines() if line.strip()])
    expected = int(spec["count"])
    return (count == expected, f"{spec['path']} 行数={count} 期望={expected}")


def verify_grep(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """在工作区子目录中递归搜索是否包含指定字符串。"""
    needle = spec["contains"]
    search_root = workspace / spec.get("path", ".")
    if not search_root.exists():
        return (False, f"搜索根目录不存在: {search_root}")
    for candidate in search_root.rglob("*"):
        if not candidate.is_file():
            continue
        if needle in _read_text(candidate):
            return (True, f"在 {candidate.name} 中找到 {needle!r}")
    return (False, f"grep 失败: 在 {search_root} 下未找到 {needle!r}")


def verify_tool_called(trace: list[str], spec: dict[str, Any]) -> tuple[bool, str]:
    """判定 Agent 实际调用过的工具集合是否覆盖期望的工具集合。"""
    required = set(spec.get("tools", []))
    used = set(trace)
    missing = required - used
    return (not missing, f"工具调用 期望={required} 实际={used} 缺失={missing}")


def verify_keywords(text: str, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定最终回复中是否包含 ``any_of`` 中的任一关键词。"""
    haystack = (text or "").lower()
    options = [k.lower() for k in spec.get("any_of", [])]
    matched = next((opt for opt in options if opt in haystack), None)
    return (matched is not None, f"关键词匹配 matched={matched!r} 选项={options}")


def verify_answer_contains(text: str, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定最终回复（大小写不敏感）是否包含 ``value`` 字符串。"""
    value = str(spec["value"]).lower()
    return (value in (text or "").lower(), f"答案包含 {value!r}")


def verify_answer_regex(text: str, spec: dict[str, Any]) -> tuple[bool, str]:
    """用 ``pattern`` 正则匹配最终回复。"""
    pattern = spec["pattern"]
    return (
        re.search(pattern, text or "") is not None,
        f"答案正则 {pattern!r} -> {bool(re.search(pattern, text or ''))}",
    )


def run_verifiers(
    *,
    workspace: Path,
    tool_trace: list[str],
    final_text: str,
    verifiers: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """按顺序执行 verifier 列表，第一个命中即返回 True。"""
    reasons: list[str] = []
    for entry in verifiers or []:
        kind = entry.get("kind")
        if kind == "file_exists":
            ok, msg = verify_file_exists(workspace, entry)
        elif kind == "file_contains":
            ok, msg = verify_file_contains(workspace, entry)
        elif kind == "file_count":
            ok, msg = verify_file_count(workspace, entry)
        elif kind == "grep":
            ok, msg = verify_grep(workspace, entry)
        elif kind == "tool_called":
            ok, msg = verify_tool_called(tool_trace, entry)
        elif kind == "keywords":
            ok, msg = verify_keywords(final_text, entry)
        elif kind == "answer_contains":
            ok, msg = verify_answer_contains(final_text, entry)
        elif kind == "answer_regex":
            ok, msg = verify_answer_regex(final_text, entry)
        else:
            ok, msg = (False, f"未知 verifier 类型: {kind!r}")
        reasons.append(f"[{kind}] {msg}")
        if ok:
            return True, reasons
    return False, reasons