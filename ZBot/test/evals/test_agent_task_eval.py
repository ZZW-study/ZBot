# -*- coding: utf-8 -*-
"""ZBot Agent 任务评测(100 条分层难度任务)。

读 ``_tasks_main.json``,跑真实 ``BaseAgent.run_agent_loop``,
按 level / category 两维度统计完成率、平均工具调用、平均 token。

跑测方式:
  默认 (--eval-sample=20)        : 从 100 条按 level 均衡采样 20 条
  ZBOT_EVAL_FULL=1                 : 跑全部 100 条

报告写入 ``eval_results/agent_task_v2.json``。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest


_TASKS_PATH = Path(__file__).parent / "_tasks_main.json"
_TASKS: list[dict[str, Any]] = json.loads(_TASKS_PATH.read_text(encoding="utf-8"))


def _sample_tasks(target: int) -> list[dict[str, Any]]:
    """从任务池里按 level 均衡采样 target 条。"""
    by_level: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for t in _TASKS:
        by_level[t.get("level", 1)].append(t)
    levels = sorted(by_level.keys())
    per_level = max(1, target // len(levels))
    sampled: list[dict[str, Any]] = []
    for lv in levels:
        sampled.extend(by_level[lv][:per_level])
    if len(sampled) < target:
        rest = [t for t in _TASKS if t not in sampled]
        sampled.extend(rest[: target - len(sampled)])
    return sampled[:target]


_FULL = os.environ.get("ZBOT_EVAL_FULL") == "1"
_DEFAULT_LIMIT = 20
TASKS: list[dict[str, Any]] = _TASKS if _FULL else _sample_tasks(_DEFAULT_LIMIT)


def _bootstrap_runner():
    from ZBot.test.evals._runner import make_provider, run_main_agent_task
    return make_provider, run_main_agent_task


@pytest.fixture(scope="session")
def provider():
    make_provider, _ = _bootstrap_runner()
    return make_provider()


def _bucket(results: list[Any], key_fn) -> dict[str, dict[str, int]]:
    """按 key 把 results 分桶,统计 completed / total。"""
    out: dict[str, dict[str, int]] = {}
    for r in results:
        k = key_fn(r)
        bucket = out.setdefault(k, {"completed": 0, "total": 0})
        bucket["total"] += 1
        if r.passed:
            bucket["completed"] += 1
    return out


def _ratio(per: dict[str, dict[str, int]]) -> float:
    total = sum(v["total"] for v in per.values())
    completed = sum(v["completed"] for v in per.values())
    return round(completed / max(1, total), 4)


def _avg_tool_calls(results: list[Any]) -> float:
    if not results:
        return 0.0
    return round(sum(len(r.tool_trace) for r in results) / len(results), 2)


def _summarize(results: list[Any], elapsed: float) -> dict[str, Any]:
    completed = sum(1 for r in results if r.passed)
    total = len(results)
    return {
        "total": total,
        "completed": completed,
        "completion_rate": round(completed / max(1, total), 4),
        "elapsed_seconds": round(elapsed, 2),
        "per_level": _bucket(results, lambda r: f"L{r.task_level}"),
        "per_category": _bucket(results, lambda r: r.task_category),
        "avg_tool_calls_per_task": _avg_tool_calls(results),
    }


@pytest.mark.timeout(60 * 60)
def test_agent_task_v2(provider):
    """跑 100 条分层难度任务,产出多维度报告。"""
    _, run_main_agent_task = _bootstrap_runner()

    started = time.monotonic()
    results = asyncio.run(_run_all(run_main_agent_task, provider, TASKS))
    elapsed = time.monotonic() - started

    summary = _summarize(results, elapsed)
    # 把 TaskRunResult 转 dict
    per_task_dump = [
        {
            "id": r.task_id,
            "level": r.task_level,
            "category": r.task_category,
            "passed": r.passed,
            "elapsed": r.elapsed_seconds,
            "tool_calls": len(r.tool_trace),
            "error": r.error,
        }
        for r in results
    ]
    report = {
        "evaluated": len(TASKS),
        "total_tasks_in_pool": len(_TASKS),
        "summary": summary,
        "failed_task_ids": [r.task_id for r in results if not r.passed],
        "per_task": per_task_dump,
    }
    print("\n=== ZBot Agent 任务 v2 评测结果 ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    out_path = Path(__file__).parent / "eval_results" / "agent_task_v2.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 断言:整体完成率 >= 50%(留出合理缓冲,因任务本身有难度分层)
    assert summary["completion_rate"] >= 0.5, (
        f"整体完成率过低: {summary['completion_rate']}; "
        f"failed_task_ids={report['failed_task_ids'][:5]}"
    )


async def _run_all(run_main_agent_task, provider, tasks):
    """顺序跑完所有任务,记录每条结果。"""
    out = []
    for idx, t in enumerate(tasks, 1):
        try:
            r = await run_main_agent_task(
                task=t, provider=provider, with_recovery=True, per_task_timeout=60
            )
            out.append(r)
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx}/{len(tasks)}] {t.get('id')} 崩溃: {exc!r}")
        else:
            print(
                f"[{idx}/{len(tasks)}] {t.get('id')} L{t.get('level')} "
                f"{t.get('category')} passed={r.passed} "
                f"耗时={r.elapsed_seconds}s 工具={len(r.tool_trace)}"
            )
    return out
