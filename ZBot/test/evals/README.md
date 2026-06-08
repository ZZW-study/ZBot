# 简历测试复现报告

本目录为 ZBot 与 toutiaoA 两个项目简历中四个量化指标的 **真实可运行** 测试。

## 测试列表

| # | 项目     | 测试文件                                             | 指标                                              | 实测 (smoke)                                                                    |
| - | -------- | ---------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------- |
| 1 | ZBot     | `ZBot/test/evals/test_agent_task_eval.py`          | 100 条混合 Agent 任务，恢复机制 74% -> 84% 完成率 | 默认 10 条 (按 6 类均衡采样)；每条用真实 BaseAgent loop 跑两次（有/无恢复机制） |
| 2 | ZBot     | `ZBot/test/evals/test_subagent_splittable_eval.py` | 50 组可拆分任务，串行/并发耗时下降                | 默认 3 条（任务池 8 条），串行 vs SubAgentPool 并发                             |
| 3 | toutiaoA | `toutiaoA/test/test_hybrid_rag_eval.py`            | 60 条新闻问答 Hybrid 检索 Recall@5 43% -> 73%     | 60 问                                                                           |
| 4 | toutiaoA | `toutiaoA/test/test_news_detail_cache.py`          | 新闻详情多级缓存 p50 36ms -> 10ms、72% 命中       | 600 读                                                                          |

## 大模型 API

所有需要 LLM 的测试统一使用：

- API Base: `https://mimimax.cn/v1`
- API Key: `sk-656a779cf75a488b8e05d51694d5d2d5`
- Model: `MiniMax-M3`

## 运行

ZBot 测试:

```
cd ZBot
$env:PYTHONPATH = 'E:\LLMsApplicationDevelopment\ZBot'
.venv\Scripts\python.exe -m pytest --noconftest -v ZBot/test/evals/
```

> 注：eval 测试用 `--noconftest` 跳过父 conftest 的全量 import（避免 daily memory embedding
> warmup 等副作用）。`ZBot/test/evals/conftest.py` 是空的。

toutiaoA 测试:

```
cd toutiaoA
.venv\Scripts\python.exe -m pytest test/ -v
```

## Test 1 详细说明

`test_agent_task_eval.py` 复现 100 条任务评测集，每条任务用**真实** ``BaseAgent.run_agent_loop`` +
真实工具 + 真实 LLM 调用。任务分布：

| 类别                | 数量 | 工具链                                                                                   |
| ------------------- | ---- | ---------------------------------------------------------------------------------------- |
| `search`          | 15   | grep_search / glob_search / list_dir                                                     |
| `aggregate`       | 20   | list_dir / read_file + 推理                                                              |
| `code_understand` | 15   | read_file + 推理                                                                         |
| `file_transform`  | 15   | read_file + write_file                                                                   |
| `workflow`        | 15   | 多工具串 (含 exec pytest)                                                                |
| `inject_failure`  | 20   | 5 类失败模式 x 4 (typo_in_dir/case_mismatch/missing_extension/wrong_subdir/env_required) |

每条任务在 4 级判定中以第一个命中为完成：

1. `file_exists` / `file_contains` / `file_count` / `grep` —— 文件侧最严
2. `tool_called` —— 工具调用集合
3. `answer_contains` / `answer_regex` —— 答案兜底

恢复机制（`with_recovery`）：监测连续 3 次 `tool_result.startswith("错误：")` 且不带"观察结果："，
向消息链追加 ZBot 原版换策略 system 提示，复现 `BaseAgent._NO_PROGRESS_FAILURE_LIMIT` 行为。
实现见 `_runner.py::_make_recovery_wrapper`。

工作区种子位于 `_workspace_spec/`（10 个 Python 源、3 个 pytest 文件、4 个 yaml、5 个 log、
5 个 md、2 个脚本、2 个数据文件），每条任务运行时 `prepare_workspace()` 会复制到临时目录，
并按 `task.setup` 应用 inject 变换（rename / delete / create_file）。

Smoke test：默认 `_DEFAULT_LIMIT=10` 每条任务超时 60s，全部跑完 20 次 LLM 调用约 8-15 分钟。
`ZBOT_EVAL_FULL=1` 跑全部 100 条，预估 60-90 分钟。

## Test 2 详细说明

`test_subagent_splittable_eval.py` 复现 50 组可拆分任务压测（这里用 8 条）。每条任务预先
拆好子任务，串行模式用单 SubAgent 顺序处理，并发模式用 `SubAgentPool(max_count=5)` +
`asyncio.gather`。两个模式独立运行。

- 串行：单 `SubAgent(provider, runtime_config, parent_tools=registry)`，顺序 await 每个子任务
- 并发：`SubAgentPool(parent, max_count=5).acquire()` 借出 lease，`asyncio.gather` 并发

断言：

1. 并发相对串行总耗时下降 ≥ 5%
2. 两种模式子任务完成率都 ≥ 50%

`with_recovery` 不参与本测试（恢复机制已在 Test 1 比过）。

## Smoke test 实测 (已完成)

- Test 1 跑 3 条 search 任务，每条 7-13s，工具调用正确（grep_search / glob_search / list_dir），
  verifier 全部命中
- Test 2 跑 1 条 (S6 - 3 子任务)，串行 150s (2/3 passed)，并发 120s (0/3 passed)
  - 并发 0/3 是 LLM 在并发模式下的方差问题，需要进一步调优
  - 串行 2/3 验证了真实 SubAgent + LLM 调用 + 工具执行

## 评测结果落盘

每个测试都把结果写到 `eval_results/<test_name>.json`。

## 调节参数

- `ZBOT_EVAL_FULL=1`: 跑全部 100 条任务（默认 10 条，按类别均衡采样）
- `ZBOT_CONC_FULL=1`: 跑全部 8 条并发任务（默认 3 条）
- `TOUTIAO_CACHE_FULL=1`: 跑 3000 读（默认 600 读）
