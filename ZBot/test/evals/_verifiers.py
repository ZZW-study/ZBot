# -*- coding: utf-8 -*-
"""ZBot 评测的任务完成判定器。

每个 verifier 会观察一次 Agent 运行的副作用（写到工作区的新文件、
实际调用过的工具、最终回复文本等），并返回 ``(passed, reason)``。
一个任务可以声明多个 verifier，按顺序判定，第一个命中即视为完成。
"""

from __future__ import annotations

import csv
import json
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


def verify_file_size(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定指定文件字节数在期望范围内(>min_bytes, <=max_bytes)。"""
    path = workspace / spec["path"]
    if not path.exists():
        return (False, f"文件 {spec['path']} 不存在")
    size = path.stat().st_size
    min_bytes = int(spec.get("min_bytes", 0))
    max_bytes = int(spec.get("max_bytes", float("inf")))
    passed = min_bytes < size <= max_bytes
    return (passed, f"{spec['path']} 字节={size} 范围=({min_bytes}, {max_bytes}]")


def verify_json_valid(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定文件能被 json.loads 解析(且为对象/数组)。"""
    path = workspace / spec["path"]
    if not path.exists():
        return (False, f"文件 {spec['path']} 不存在")
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        return (False, f"{spec['path']} 不是合法 JSON: {e}")
    want_type = spec.get("type", "any")
    if want_type == "object" and not isinstance(data, dict):
        return (False, f"{spec['path']} 期望 object,得到 {type(data).__name__}")
    if want_type == "array" and not isinstance(data, list):
        return (False, f"{spec['path']} 期望 array,得到 {type(data).__name__}")
    return (True, f"{spec['path']} 是合法 JSON {type(data).__name__}")


def verify_json_field(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定 JSON 文件中指定路径字段存在且为期望值/类型。"""
    path = workspace / spec["path"]
    if not path.exists():
        return (False, f"文件 {spec['path']} 不存在")
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        return (False, f"{spec['path']} JSON 解析失败: {e}")
    # 字段路径:点分路径,如 'app.port'
    parts = str(spec.get("field", "")).split(".")
    cur = data
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return (False, f"{spec['path']} 缺少字段 {'.'.join(parts)}")
        cur = cur[p]
    if "equals" in spec:
        return (cur == spec["equals"], f"{spec['field']}={cur!r} 期望={spec['equals']!r}")
    if "min" in spec:
        try:
            return (cur >= spec["min"], f"{spec['field']}={cur} 期望>={spec['min']}")
        except TypeError:
            return (False, f"{spec['field']}={cur} 不可比较")
    if "in" in spec:
        return (cur in spec["in"], f"{spec['field']}={cur!r} 期望 in {spec['in']!r}")
    return (cur is not None, f"{spec['field']}={cur!r} 存在")


def verify_csv_header(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定 CSV 第一行(表头)包含全部期望列名,顺序可乱。"""
    path = workspace / spec["path"]
    if not path.exists():
        return (False, f"文件 {spec['path']} 不存在")
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return (False, f"{spec['path']} 是空文件")
    expected = list(spec.get("columns", []))
    missing = [c for c in expected if c not in header]
    return (not missing, f"{spec['path']} header={header} 缺少={missing}")


def verify_all_files_exist(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定多个文件全部存在(用于多步任务最后一步的"全链路产物"检查)。"""
    paths = spec.get("paths", [])
    missing = [p for p in paths if not (workspace / p).exists()]
    return (not missing, f"missing={missing}")


def verify_file_line_count(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定指定文件的总行数(含空行)是否等于期望值。"""
    path = workspace / spec["path"]
    if not path.exists():
        return (False, f"文件 {spec['path']} 不存在")
    text = _read_text(path)
    count = len(text.splitlines())
    expected = int(spec["count"])
    return (count == expected, f"{spec['path']} 行数={count} 期望={expected}")


def verify_directory_exists(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定指定目录是否存在。"""
    path = workspace / spec["path"]
    passed = path.is_dir()
    return (passed, f"目录 {spec['path']} 存在={passed}")


def verify_directory_file_count(workspace: Path, spec: dict[str, Any]) -> tuple[bool, str]:
    """判定指定目录下(非递归)文件数是否等于期望值。"""
    path = workspace / spec["path"]
    if not path.is_dir():
        return (False, f"目录 {spec['path']} 不存在")
    files = [p for p in path.iterdir() if p.is_file()]
    expected = int(spec["count"])
    return (len(files) == expected, f"{spec['path']} 文件数={len(files)} 期望={expected}")


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
    required = set(spec.get("tools", []))
    used_set = set(trace)
    missing = required - used_set
    if missing:
        return (False, f"tool_called 缺失={sorted(missing)} 实际={sorted(used_set)}")
    min_invocations = spec.get("min_invocations", {}) or {}
    if min_invocations:
        counts = Counter(trace)
        insufficient = {t: (min_invocations[t], counts.get(t, 0)) for t in min_invocations if counts.get(t, 0) < min_invocations[t]}
        if insufficient:
            return (False, f"tool_called 调用次数不足 {insufficient}")
    return (True, f"tool_called 期望={sorted(required)} 实际={sorted(used_set)} 调用次数 ok")


def verify_trace_not_empty(trace: list[str], spec: dict[str, Any]) -> tuple[bool, str]:
    if not trace:
        return (False, "trace_not_empty: 工具调用为空 (agent 没有调用任何工具)")
    return (True, f"trace_not_empty: 共 {len(trace)} 次工具调用")


def verify_exec_output_contains(exec_outputs: list[str], spec: dict[str, Any]) -> tuple[bool, str]:
    needle = spec.get("contains", "")
    min_outputs = int(spec.get("min_outputs", 1))
    if len(exec_outputs) < min_outputs:
        return (False, f"exec_output_contains: 需要至少 {min_outputs} 次 exec 调用, 实际 {len(exec_outputs)}")
    for idx, out in enumerate(exec_outputs):
        if needle in out:
            return (True, f"exec_output_contains: 第 {idx + 1} 次 exec 输出含 {needle!r}")
    return (False, f"exec_output_contains: 全部 {len(exec_outputs)} 次 exec 输出都未含 {needle!r}")


def run_verifiers(
    *,
    workspace: Path,
    tool_trace: list[str],
    final_text: str,
    verifiers: list[dict[str, Any]],
    exec_outputs: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """AND semantics: task passes only when EVERY verifier passes.

    Hardened against the original OR-anti-pattern where the first pass
    short-circuited the rest. Each verifier contributes one (ok, msg)
    result; only all-True means the task is complete.

    New verifier kinds:
      - trace_not_empty: assert tool_trace has >= 1 entry
      - exec_output_contains: assert a substring appears in real exec() output
        (not in any file the agent wrote by hand to fake a test result)

    exec_outputs is the list of strings the agent\'s exec() invocations
    produced. The runner captures these from the ToolRegistry.
    """
    exec_outputs = exec_outputs or []
    results: list[tuple[bool, str]] = []
    for entry in verifiers or []:
        kind = entry.get("kind")
        if kind == "file_exists":
            ok, msg = verify_file_exists(workspace, entry)
        elif kind == "file_contains":
            ok, msg = verify_file_contains(workspace, entry)
        elif kind == "file_count":
            ok, msg = verify_file_count(workspace, entry)
        elif kind == "file_size":
            ok, msg = verify_file_size(workspace, entry)
        elif kind == "file_line_count":
            ok, msg = verify_file_line_count(workspace, entry)
        elif kind == "json_valid":
            ok, msg = verify_json_valid(workspace, entry)
        elif kind == "json_field":
            ok, msg = verify_json_field(workspace, entry)
        elif kind == "csv_header":
            ok, msg = verify_csv_header(workspace, entry)
        elif kind == "all_files_exist":
            ok, msg = verify_all_files_exist(workspace, entry)
        elif kind == "directory_exists":
            ok, msg = verify_directory_exists(workspace, entry)
        elif kind == "directory_file_count":
            ok, msg = verify_directory_file_count(workspace, entry)
        elif kind == "grep":
            ok, msg = verify_grep(workspace, entry)
        elif kind == "tool_called":
            ok, msg = verify_tool_called(tool_trace, entry)
        elif kind == "trace_not_empty":
            ok, msg = verify_trace_not_empty(tool_trace, entry)
        elif kind == "exec_output_contains":
            ok, msg = verify_exec_output_contains(exec_outputs, entry)
        elif kind == "keywords":
            ok, msg = verify_keywords(final_text, entry)
        elif kind == "answer_contains":
            ok, msg = verify_answer_contains(final_text, entry)
        elif kind == "answer_regex":
            ok, msg = verify_answer_regex(final_text, entry)
        else:
            ok, msg = (False, f"未知 verifier 类型: {kind!r}")
        results.append((ok, f"[{kind}] {msg}"))
    all_ok = all(ok for ok, _ in results)
    reasons = [msg for _, msg in results]
    return all_ok, reasons
