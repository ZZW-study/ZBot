---
name: my
description: "检查和设置 Agent 自身运行状态（模型、总超时、上下文窗口、token 用量、联网配置）。当需要诊断为什么某件事不能工作、复杂任务前检查资源限制、为长任务/简单任务调整配置、跨轮记住用户偏好，或用户询问当前模型、token 用量、设置时使用。"
always: true
---

# 自我状态感知

## 怎么使用

1. 从下面的类别中**判断当前情况**。
2. 用合适的 action **调用 `my` 工具**。
3. 如果要 `set`，在修改重要设置（模型、总超时等）前先提醒用户。
4. 需要详细示例时，读取 [references/examples.md](references/examples.md)。

## 什么时候检查

<rule>
**解释前先诊断。** 某件事不能工作时，先检查自身状态。
</rule>

<rule>
**复杂任务前先检查预算。** 承诺任务前先知道自己的限制。
</rule>

<rule>
**跨轮召回。** 把偏好存在 scratchpad 里，后面再读出来。
</rule>

## 什么时候设置

<rule>
**只有收益明确且用户知情时才设置。** 修改模型前要先提醒。
</rule>

| 场景 | 命令 |
|------|------|
| 大型代码库分析 | `my(action="set", key="context_window_tokens", value=131072)` |
| 重复的简单任务 | `my(action="set", key="model", value="<fast-model>")` |
| 长链路多步骤任务 | `my(action="set", key="agent_timeout_seconds", value=3600)` |

**取舍：** 偏向稳定。只有默认值确实不够时才设置。

## 反模式

<rule>
**不要每轮都检查。** 这会消耗一次工具调用。只有需要信息时才用，不要条件反射式调用。
</rule>

<rule>
**不要存敏感数据。** 不要把 API key、密码或 token 存进 scratchpad。
</rule>

<rule>
**不要设置 workspace。** 这不会更新文件工具边界，因此无效。
</rule>

## 约束

- 所有修改只在内存中生效，重启后会重置。
- ZBot 的主 Agent loop 不使用固定轮数上限；长任务主要受总超时、上下文预算、压缩和用户中断控制。
- 受保护参数有类型/范围校验：`agent_timeout_seconds`、`context_window_tokens`、`model` 等。
- 如果 `tools.my.allow_set` 为 false，只能检查，不能设置。

## 相关工具

| 需求 | 使用 | 是否持久化 |
|------|------|------------|
| 单会话临时状态 | `my(action="set", key="...", value=...)` | 否 |
| 长期事实 | Memory 技能（`MEMORY.md`、`USER.md`） | 是 |
| 永久配置变更 | 编辑配置文件 | 是 |

**经验法则：** 明天还要用？写 Memory。只在本轮用？写 My。
