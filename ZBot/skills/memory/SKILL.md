---
name: memory
description: "由 Dream 管理知识文件的双层记忆系统。"
always: true
---

# 记忆

## 结构

- `SOUL.md`：Bot 的人格和沟通风格。**由 Dream 管理。**不要编辑。
- `USER.md`：用户画像和偏好。**由 Dream 管理。**不要编辑。
- `memory/MEMORY.md`：长期事实（项目上下文、重要事件）。**由 Dream 管理。**不要编辑。
- `memory/history.jsonl`：只追加写入的 JSONL，不会加载进上下文。搜索时优先使用内置 `grep` 工具。

## 搜索过去事件

`memory/history.jsonl` 是 JSONL 格式，每一行都是一个 JSON 对象，包含 `cursor`、`timestamp`、`content`。

- 大范围搜索时，先用 `grep(..., path="memory", glob="*.jsonl", output_mode="count")` 或默认的 `files_with_matches` 模式，再决定是否展开完整内容。
- 需要精确匹配行时，使用 `output_mode="content"`，并配合 `context_before` / `context_after`。
- 搜索字面量时间戳或 JSON 片段时，使用 `fixed_strings=true`。
- 历史很长时，使用 `head_limit` / `offset` 分页。
- 只有内置搜索表达不了需求时，才把 `exec` 作为最后兜底。

示例（把 `keyword` 替换成真实关键词）：
- `grep(pattern="keyword", path="memory/history.jsonl", case_insensitive=true)`
- `grep(pattern="2026-04-02 10:00", path="memory/history.jsonl", fixed_strings=true)`
- `grep(pattern="keyword", path="memory", glob="*.jsonl", output_mode="count", case_insensitive=true)`
- `grep(pattern="oauth|token", path="memory", glob="*.jsonl", output_mode="content", case_insensitive=true)`

## 重要

- **不要编辑 SOUL.md、USER.md 或 MEMORY.md。** 它们由 Dream 自动管理。
- 如果发现过时信息，Dream 下一次运行时会修正。
- 用户可以用 `/dream-log` 查看 Dream 的活动。
