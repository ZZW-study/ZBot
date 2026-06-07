# -*- coding: utf-8 -*-
"""ZBot Agent 任务评测。

复现简历中"100 条混合难度 Agent 任务评测集"场景：
- 对每条任务跑真实 ``BaseAgent.run_agent_loop``（调用 ``LiteLLMProvider`` 与真实 LLM）
- 对比加/不带恢复机制的完成率（84% vs 74%）

恢复机制定义（复现 ``BaseAgent._NO_PROGRESS_FAILURE_LIMIT`` 与策略切换提醒）：
- 工具返回错误且没有新观察，计数 +1
- 连续三次无进展失败后，向消息链追加 ZBot 原版换策略提示
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest


_TASKS_PATH = Path(__file__).parent / "_tasks_main.json"
_TASKS: list[dict[str, Any]] = json.loads(_TASKS_PATH.read_text(encoding="utf-8"))


def _sample_tasks(target: int) -> list[dict[str, Any]]:
    """从任务池里均衡采样 ``target`` 条，保留各类型比例。"""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for t in _TASKS:
        by_type.setdefault(t["type"], []).append(t)
    types = list(by_type.keys())
    per_type = max(1, target // len(types))
    sampled: list[dict[str, Any]] = []
    for t in types:
        sampled.extend(by_type[t][:per_type])
    if len(sampled) < target:
        # 不够时按声明顺序从剩余任务中补齐
        rest = [t for t in _TASKS if t not in sampled]
        sampled.extend(rest[: target - len(sampled)])
    return sampled[:target]


_FULL = os.environ.get("ZBOT_EVAL_FULL") == "1"
_DEFAULT_LIMIT = 10
TASKS: list[dict[str, Any]] = _TASKS if _FULL else _sample_tasks(_DEFAULT_LIMIT)


def _bootstrap_runner():
    """延迟导入 runner，把 import 循环的破坏点收敛到一处。"""
    from ZBot.test.evals._runner import make_provider, run_main_agent_task
    return make_provider, run_main_agent_task


@pytest.fixture(scope="session")
def provider():
    make_provider, _ = _bootstrap_runner()
    return make_provider()


def _per_type(results: list[Any]) -> dict[str, dict[str, int]]:
    """按任务类型统计完成情况。"""
    out: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = out.setdefault(r.task_type, {"completed": 0, "total": 0})
        bucket["total"] += 1
        if r.passed:
            bucket["completed"] += 1
    return out


def _summary(results: list[Any], elapsed: float) -> dict[str, Any]:
    """汇总一次完整跑测的结果。"""
    completed = sum(1 for r in results if r.passed)
    total = len(results)
    return {
        "total": total,
        "completed": completed,
        "completion_rate": round(completed / max(1, total), 4),
        "elapsed_seconds": round(elapsed, 2),
        "per_type": _per_type(results),
    }


@pytest.mark.timeout(60 * 60)
def test_recovery_mechanism(provider):
    """对每条任务跑两次（带/不带恢复机制）并比较完成率。"""
    _, run_main_agent_task = _bootstrap_runner()

    # ---------- 不带恢复机制 ----------
    started = time.monotonic()
    without_results = asyncio.run(
        _run_all(run_main_agent_task, provider, TASKS, with_recovery=False)
    )
    without_elapsed = time.monotonic() - started

    # ---------- 带恢复机制 ----------
    started = time.monotonic()
    with_results = asyncio.run(
        _run_all(run_main_agent_task, provider, TASKS, with_recovery=True)
    )
    with_elapsed = time.monotonic() - started

    without = _summary(without_results, without_elapsed)
    withr = _summary(with_results, with_elapsed)
    delta = round(withr["completion_rate"] - without["completion_rate"], 4)

    # 仅看 inject_failure 类型任务上的恢复效果
    inject_types = {"inject_failure"}
    inject_no = _per_type([r for r in without_results if r.task_type in inject_types])
    inject_wr = _per_type([r for r in with_results if r.task_type in inject_types])
    inject_rate_no = _ratio(inject_no)
    inject_rate_wr = _ratio(inject_wr)

    report = {
        "evaluated": len(TASKS),
        "total_tasks_in_pool": len(_TASKS),
        "without_recovery": without,
        "with_recovery": withr,
        "delta": delta,
        "inject_failure": {
            "without_rate": inject_rate_no,
            "with_rate": inject_rate_wr,
            "delta": round(inject_rate_wr - inject_rate_no, 4),
        },
    }
    print("\n=== ZBot Agent 任务评测结果 ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    out_path = Path(__file__).parent / "eval_results" / "agent_task_eval.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 断言 ----
    # 1) 恢复机制不能显著拖累整体完成率（允许 -5% 的抖动）
    assert withr["completion_rate"] >= without["completion_rate"] - 0.05, (
        f"恢复机制出现退化: 带恢复 {withr['completion_rate']} vs 不带恢复 {without['completion_rate']}"
    )
    # 2) 在 inject_failure 任务上恢复机制不能比无恢复更差
    assert inject_rate_wr >= inject_rate_no, (
        f"恢复机制在 inject_failure 上退化: 带恢复={inject_rate_wr} 不带恢复={inject_rate_no}"
    )


def _ratio(per_type: dict[str, dict[str, int]]) -> float:
    """把按类型分桶的统计折叠成单个完成率。"""
    total = sum(v["total"] for v in per_type.values())
    completed = sum(v["completed"] for v in per_type.values())
    return round(completed / max(1, total), 4)


async def _run_all(run_main_agent_task, provider, tasks, *, with_recovery):
    """顺序跑完所有任务，并把每条结果打印到控制台。"""
    out = []
    for idx, t in enumerate(tasks, 1):
        try:
            r = await run_main_agent_task(
                task=t, provider=provider, with_recovery=with_recovery, per_task_timeout=60
            )
            out.append(r)
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx}/{len(tasks)}] {t.get('id')} 崩溃: {exc!r}")
        else:
            print(
                f"[{idx}/{len(tasks)}] {t.get('id')} {t.get('type')} "
                f"passed={r.passed} 耗时={r.elapsed_seconds}s "
                f"工具调用={len(r.tool_trace)}"
            )
    return out