# -*- coding: utf-8 -*-
"""用真实的 :class:`BaseAgent` 主循环跑单条评测任务。

Test 1（``test_agent_task_eval.py``）直接使用 :class:`EvalParent`
（一个不注册默认工具的 ``BaseAgent`` 最小子类）来验证恢复机制；
Test 2（``test_subagent_splittable_eval.py``）则把同一个父 Agent
与真实的 :class:`SubAgent` / :class:`SubAgentPool` 拼起来，对比
串行 vs 并发的执行效果。

绕开循环导入：``ZBot.services.agent_run.__init__`` 会预导入
``agent_factory`` -> ``core_agent`` -> ``base_agent``，而
``ZBot.agent.base_agent`` 又会 import
``ZBot.services.agent_run.agent_runtime``，两者相互依赖。这里
先用 ``importlib`` 把 ``agent_runtime`` 提前加载进 ``sys.modules``，
使 ``base_agent`` 后续 import 时能直接拿到符号，避免循环。
"""

from __future__ import annotations

import asyncio
import importlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

_agent_runtime = importlib.import_module("ZBot.services.agent_run.agent_runtime")
AgentRuntimeConfig = _agent_runtime.AgentRuntimeConfig

_base_agent_mod = importlib.import_module("ZBot.agent.base_agent")
BaseAgent = _base_agent_mod.BaseAgent

_subagent_mod = importlib.import_module("ZBot.agent.subagent.subagent")
SubAgent = _subagent_mod.SubAgent

_pool_mod = importlib.import_module("ZBot.agent.subagent.subagent_pool")
SubAgentPool = _pool_mod.SubAgentPool

from ZBot.providers.litellm_provider import LiteLLMProvider  # noqa: E402

from ZBot.test.evals._tools import build_registry  # noqa: E402
from ZBot.test.evals._verifiers import run_verifiers  # noqa: E402
from ZBot.test.evals._workspace_setup import apply_setup, prepare_workspace  # noqa: E402


API_BASE = "https://mimimax.cn/v1"
API_KEY = "sk-656a779cf75a488b8e05d51694d5d2d5"
MODEL = "MiniMax-M3"

SYSTEM_PROMPT = (
    "你是 ZBot，一个直接、可靠、擅于执行的 AI 助手。回答用户问题时请："
    "1) 简洁问题直接给出答案；2) 涉及文件/目录的工具任务使用对应工具；"
    "3) 工具返回错误时换路径或换工具重试，不要重复相同的错误调用；"
    "4) 不要编造工具结果；5) 完成后用一两句话告诉用户最终结果。"
)

RECOVERY_THRESHOLD = 3

RECOVERY_HINT = (
    "\n\n[系统提示：你已经连续多次用相同路径或参数失败，"
    "且工具没有返回任何新观察。请立刻停止当前路径，"
    "改用不同工具或不同参数；如果实在没有新路径，"
    "请基于已知观察直接给用户最终回答，不要再无限重试。]"
)


class EvalParent(BaseAgent):
    """最小 ``BaseAgent`` 子类：跳过默认工具注册，由评测代码自己注入。"""

    def _register_default_tools(self) -> None:  # type: ignore[override]
        return


@dataclass
class TaskRunResult:
    """单条主 Agent 任务的运行结果。"""
    task_id: str
    task_type: str
    task_text: str
    passed: bool
    elapsed_seconds: float
    tool_trace: list = field(default_factory=list)
    final_text: str = ""
    verifier_reasons: list = field(default_factory=list)
    error: str | None = None


def make_provider() -> LiteLLMProvider:
    """构造一个真实可用的 LLM Provider（指向测试 API）。"""
    return LiteLLMProvider(
        api_key=API_KEY,
        api_base=API_BASE,
        default_model=MODEL,
        provider_name="openrouter",
    )


def make_runtime_config(workspace: Path) -> AgentRuntimeConfig:
    """为评测构造一个 ``AgentRuntimeConfig``，把工作区锁死。"""
    return AgentRuntimeConfig(
        workspace=workspace,
        model=MODEL,
        temperature=0.1,
        max_tokens=2048,
        context_compaction_threshold=0.8,
        restrict_to_workspace=True,
    )


async def _silent_progress(*_args, **_kwargs):
    """静默的进度回调：什么都不做，避免污染测试输出。"""
    return None


@dataclass
class _RecoveryState:
    """恢复机制的状态机：连续失败计数 + 注入次数。"""
    consecutive: int = 0
    injected_count: int = 0


def _make_recovery_wrapper(registry, no_progress_limit=RECOVERY_THRESHOLD):
    """包装 ``ToolRegistry.execute``，复现 ZBot 源码中的换策略提醒逻辑。

    判定规则（与 ``BaseAgent._count_no_progress_failures`` 一致）：
    - 工具返回以"错误"开头、且没有"观察结果"的字符串时，视为一次无进展失败，计数 +1
    - 计数达到阈值后，向返回串末尾追加 ZBot 原版换策略 system 提示
    """
    state = _RecoveryState()

    async def execute(name, params):
        result = await registry.execute(name, params)
        if (
            isinstance(result, str)
            and result.startswith("错误")
            and "观察结果" not in result
        ):
            state.consecutive += 1
        else:
            state.consecutive = 0
        if state.consecutive >= no_progress_limit:
            result = (result or "") + RECOVERY_HINT
            state.consecutive = 0
            state.injected_count += 1
        return result

    return execute, state


async def run_main_agent_task(*, task, provider, with_recovery, per_task_timeout=90.0):
    """跑一条主 Agent 任务（Test 1）。"""
    workspace = prepare_workspace()
    apply_setup(workspace, task.get("setup"))
    registry = build_registry(workspace)
    runtime_config = make_runtime_config(workspace)

    parent = EvalParent(provider=provider, runtime_config=runtime_config)
    parent.tools = registry

    if with_recovery:
        wrapped_execute, _state = _make_recovery_wrapper(registry)
        parent.tools.execute = wrapped_execute  # type: ignore[method-assign]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task["task"]},
    ]

    started = time.monotonic()
    error = None
    tool_trace: list = []
    final_text = None
    try:
        final_text, tool_trace, _messages = await asyncio.wait_for(
            parent.run_agent_loop(
                initial_messages=messages,
                on_progress=_silent_progress,
                progress_label=task.get("id", "main"),
            ),
            timeout=per_task_timeout,
        )
    except Exception as exc:  # noqa: BLE001
        error = repr(exc)
        logger.error("任务 {} 崩溃: {}", task.get("id"), error)
    elapsed = time.monotonic() - started

    passed, reasons = run_verifiers(
        workspace=workspace,
        tool_trace=tool_trace,
        final_text=final_text or "",
        verifiers=task.get("verifiers", []),
    )
    return TaskRunResult(
        task_id=task.get("id", ""),
        task_type=task.get("type", ""),
        task_text=task.get("task", ""),
        passed=passed,
        elapsed_seconds=round(elapsed, 2),
        tool_trace=tool_trace,
        final_text=final_text or "",
        verifier_reasons=reasons,
        error=error,
    )


@dataclass
class SubtaskResult:
    """单条子 Agent 任务的运行结果。"""
    subtask_id: str
    description: str
    final_text: str
    expected: str
    passed: bool
    elapsed_seconds: float
    error: str | None = None


async def _run_one_subtask(*, sub, parent_messages, subtask, per_subtask_timeout):
    """调用一次 SubAgent.process_messages 执行单个子任务。"""
    started = time.monotonic()
    error = None
    text = None
    try:
        text = await asyncio.wait_for(
            sub.process_messages(
                parent_messages,
                subtask_id=subtask["id"],
                task_description=subtask["description"],
                expected_result=subtask.get("expected", ""),
                on_progress=_silent_progress,
            ),
            timeout=per_subtask_timeout,
        )
    except Exception as exc:  # noqa: BLE001
        error = repr(exc)
    elapsed = time.monotonic() - started
    expected = subtask.get("expected", "")
    passed = (expected.lower() in (text or "").lower()) if expected else bool(text)
    return SubtaskResult(
        subtask_id=subtask["id"],
        description=subtask["description"],
        final_text=text or "",
        expected=expected,
        passed=passed,
        elapsed_seconds=round(elapsed, 2),
        error=error,
    )


async def run_splittable_task(*, task, provider, mode, pool_size=5, per_subtask_timeout=120.0):
    """跑一条可拆分任务：串行或通过 SubAgentPool 并发。"""
    workspace = prepare_workspace()
    apply_setup(workspace, task.get("setup"))
    registry = build_registry(workspace)
    runtime_config = make_runtime_config(workspace)

    parent = EvalParent(provider=provider, runtime_config=runtime_config)
    parent.tools = registry

    subtasks = task.get("subtasks", [])
    parent_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task["task"]},
    ]

    started = time.monotonic()
    results = []

    if mode == "serial":
        # 串行：单 SubAgent 顺序 await 每个子任务
        sub = SubAgent(provider=provider, runtime_config=runtime_config, parent_tools=registry)
        for st in subtasks:
            r = await _run_one_subtask(
                sub=sub,
                parent_messages=parent_messages,
                subtask=st,
                per_subtask_timeout=per_subtask_timeout,
            )
            results.append(r)
    elif mode == "parallel":
        # 并发：用 SubAgentPool 借出 lease，asyncio.gather 同时跑
        pool = SubAgentPool(parent=parent, max_count=pool_size)
        leases = []
        try:
            for st in subtasks:
                cm = pool.acquire()
                lease = await cm.__aenter__()
                leases.append((cm, lease, st))
            coros = [
                _run_one_subtask(
                    sub=lease.agent,
                    parent_messages=parent_messages,
                    subtask=st,
                    per_subtask_timeout=per_subtask_timeout,
                )
                for _cm, lease, st in leases
            ]
            results = await asyncio.gather(*coros)
        finally:
            for cm, _lease, _st in leases:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
            await pool.close()
    else:
        raise ValueError("未知模式: " + str(mode))

    total = time.monotonic() - started
    return {
        "task_id": task.get("id", ""),
        "mode": mode,
        "elapsed_seconds": round(total, 2),
        "subtask_count": len(subtasks),
        "subtasks": [
            {
                "id": r.subtask_id,
                "description": r.description,
                "expected": r.expected,
                "final_text": r.final_text[:200],
                "passed": r.passed,
                "elapsed_seconds": r.elapsed_seconds,
                "error": r.error,
            }
            for r in results
        ],
        "passed_count": sum(1 for r in results if r.passed),
    }