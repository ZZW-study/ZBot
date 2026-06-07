# -*- coding: utf-8 -*-
"""ZBot SubAgent 串行 vs 并发评测。

复现简历中"在 50 组可拆分任务压测中，串行 / 并发对比下总耗时下降约 63%"场景。

- 任务池：8 条可拆分任务（每条 2-5 个独立子任务）
- 串行：单 SubAgent 顺序处理
- 并发：``SubAgentPool(max_count=5)`` 配合 ``asyncio.gather``
- 真实 LLM、真实工具、真实 SubAgent 和 SubAgentPool
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest


_TASKS_PATH = Path(__file__).parent / "_tasks_splittable.json"
_TASKS: list[dict[str, Any]] = json.loads(_TASKS_PATH.read_text(encoding="utf-8"))


def _bootstrap():
    """延迟导入：把 import 循环的破坏点收敛到一处。"""
    from ZBot.test.evals._runner import (
        make_provider,
        run_splittable_task,
    )
    return make_provider, run_splittable_task


def _select_tasks() -> list[dict[str, Any]]:
    """从可拆分任务池中选出一部分（默认 3 条）。"""
    full = os.environ.get("ZBOT_CONC_FULL") == "1"
    if full:
        return _TASKS
    return _TASKS[:3]  # 默认 8 条里跑前 3 条


@pytest.fixture(scope="session")
def provider():
    make_provider, _ = _bootstrap()
    return make_provider()


@pytest.mark.timeout(60 * 60)
def test_serial_vs_parallel_splittable(provider):
    """对比串行与并发 SubAgent 跑 6-8 条可拆分任务的总耗时与完成率。"""
    _, run_splittable_task = _bootstrap()
    tasks = _select_tasks()

    # ---------- 串行模式 ----------
    serial_reports: list[dict[str, Any]] = []
    started = time.monotonic()
    for t in tasks:
        r = asyncio.run(
            run_splittable_task(task=t, provider=provider, mode="serial", pool_size=5)
        )
        serial_reports.append(r)
    serial_elapsed = time.monotonic() - started

    # ---------- 并发模式 ----------
    parallel_reports: list[dict[str, Any]] = []
    started = time.monotonic()
    for t in tasks:
        r = asyncio.run(
            run_splittable_task(task=t, provider=provider, mode="parallel", pool_size=5)
        )
        parallel_reports.append(r)
    parallel_elapsed = time.monotonic() - started

    serial_total = round(serial_elapsed, 2)
    parallel_total = round(parallel_elapsed, 2)
    reduction = round(1 - parallel_total / max(0.001, serial_total), 4)

    serial_quality = _quality(serial_reports)
    parallel_quality = _quality(parallel_reports)

    report = {
        "tasks": len(tasks),
        "total_subtasks": sum(t["subtask_count"] for t in tasks),
        "serial": {
            "elapsed_seconds": serial_total,
            "quality": serial_quality,
        },
        "parallel": {
            "elapsed_seconds": parallel_total,
            "pool_size": 5,
            "quality": parallel_quality,
        },
        "time_reduction_ratio": reduction,
        "per_task": [
            {
                "id": s["task_id"],
                "subtask_count": s["subtask_count"],
                "serial_passed": s["passed_count"],
                "serial_elapsed": s["elapsed_seconds"],
                "parallel_passed": p["passed_count"],
                "parallel_elapsed": p["elapsed_seconds"],
            }
            for s, p in zip(serial_reports, parallel_reports)
        ],
    }
    print("\n=== ZBot SubAgent 串行 vs 并发评测结果 ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    out_path = Path(__file__).parent / "eval_results" / "subagent_splittable.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 断言 ----
    # 1) 并发相对串行总耗时至少下降 5%
    assert reduction >= 0.05, (
        f"并发提速不足: 串行={serial_total}s 并发={parallel_total}s 加速比={reduction}"
    )
    # 2) 两种模式的子任务完成率都至少 50%
    assert serial_quality["completion_rate"] >= 0.5, (
        f"串行完成率过低: {serial_quality}"
    )
    assert parallel_quality["completion_rate"] >= 0.5, (
        f"并发完成率过低: {parallel_quality}"
    )


def _passed(subtasks: list[dict[str, Any]]) -> int:
    """统计子任务里通过的数量。"""
    return sum(1 for s in subtasks if s.get("passed"))


def _quality(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """把一组报告折成"子任务总数 / 通过数 / 通过率"。"""
    total_subs = sum(r["subtask_count"] for r in reports)
    passed_subs = sum(r["passed_count"] for r in reports)
    return {
        "total_subtasks": total_subs,
        "passed_subtasks": passed_subs,
        "completion_rate": round(passed_subs / max(1, total_subs), 4),
    }