# -*- coding: utf-8 -*-
"""ZBot 评测任务的工作区准备工具。

把静态的 ``_workspace_spec/`` 目录树复制到一个全新的临时目录中，
然后按任务定义的 ``setup`` 字段应用一系列"用户真实会犯的错误"
注入操作（错目录、错大小写、缺后缀、错子目录、缺依赖），用来测试
恢复机制能否让 Agent 自救。
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any


_SPEC_ROOT = Path(__file__).parent / "_workspace_spec"


def _copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def prepare_workspace(seed: int | None = None) -> Path:
    """在临时目录中创建一份工作区种子文件的全新副本。"""
    del seed
    tmp_root = Path(tempfile.mkdtemp(prefix="zb_eval_ws_"))
    workspace = tmp_root / "ws"
    _copytree(_SPEC_ROOT, workspace)
    return workspace


def apply_setup(workspace: Path, setup: dict[str, Any] | None) -> None:
    """把 setup 中的动作列表依次应用到刚创建好的工作区。"""
    if not setup:
        return
    for action in setup:
        kind = action.get("action")
        if kind == "delete":
            target = workspace / action["path"]
            if target.exists():
                target.unlink()
        elif kind == "rename":
            src = workspace / action["src"]
            dst = workspace / action["dst"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.move(str(src), str(dst))
        elif kind == "create_file":
            target = workspace / action["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(action.get("content", ""), encoding="utf-8")
        elif kind == "uninstall_pip":
            continue
        else:
            raise ValueError(f"未知的 setup 动作: {kind!r}")


def file_line_count(path: Path) -> int:
    """返回文件的非空行数（不存在则返回 0）。"""
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def count_records(data_path: Path) -> int:
    """统计 JSON 列表或 CSV 文件的有效记录数（不含表头）。"""
    if not data_path.exists():
        return 0
    text = data_path.read_text(encoding="utf-8", errors="replace")
    if data_path.suffix == ".json":
        import json
        data = json.loads(text)
        return len(data) if isinstance(data, list) else 0
    if data_path.suffix == ".csv":
        return max(0, len([line for line in text.splitlines() if line.strip()]) - 1)
    return 0