# My 工具：实用示例

下面是一些具体场景，说明什么时候以及如何有效使用 `my` 工具。

## 诊断

### “为什么你不能联网搜索？”
```
→ my(action="check", key="web_config.enable")
  → False
→ “Web search 被禁用了。请在配置里添加 web.enable: true 来启用它。”
```

### “你为什么停下来了？”
```
→ my(action="check", key="agent_timeout_seconds")
  → 3600
→ my(action="check", key="_last_usage")
  → {"prompt_tokens": 62000, "completion_tokens": 3000}
→ “我没有固定轮数上限；这次停止更可能是总超时、上下文预算、用户中断或工具失败导致。我会先说明当前停止原因和已有结果。”
```

### “你现在运行的是什么模型？”
```
→ my(action="check", key="model")
  → 'anthropic/claude-sonnet-4-20250514'
```

## 自适应行为

### 大型代码库分析
```
→ my(action="check")
  → context_window_tokens: 65536
→ my(action="set", key="context_window_tokens", value=131072)
  → "Set context_window_tokens = 131072 (was 65536)"
→ “我已经扩大上下文窗口，以便处理这个大型代码库。”
```

### 为重复任务切换到更快模型
```
→ my(action="set", key="model", value="anthropic/claude-haiku-4-5-20251001")
  → "Set model = 'anthropic/claude-haiku-4-5-20251001' (was 'anthropic/claude-sonnet-4-20250514')"
→ “已为这些批量任务切换到更快的模型。”
```

## 跨轮记忆

### 记住用户偏好
```
# 第 1 轮：用户说“简短一点”
→ my(action="set", key="user_style", value="concise")
  → "Set scratchpad.user_style = 'concise'"

# 第 3 轮：新话题
→ my(action="check", key="user_style")
  → 'concise'
  （据此调整回复风格）
```

### 追踪项目上下文
```
→ my(action="set", key="active_branch", value="feat/auth")
→ my(action="set", key="test_framework", value="pytest")
→ my(action="set", key="has_docker", value=true)
```

## 预算感知

### 有 token 意识的行为
```
→ my(action="check", key="_last_usage")
  → {"prompt_tokens": 58000, "completion_tokens": 12000}
→ “我已经消耗约 70k tokens。接下来的回复会更聚焦。”
```
