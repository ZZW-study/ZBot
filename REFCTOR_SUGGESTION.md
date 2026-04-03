# Nanobot 项目精简建议

## 项目现状分析

当前项目共有 **52个 Python 文件**，包含大量扩展性设计、兜底机制和多平台支持代码。

根据你的需求（保留核心功能：调用大模型、循环工作、调用工具），我将项目模块分为三类：

---

## 一、核心模块（必须保留）

这些是项目运行的基础，**不可删除**：

| 模块路径 | 功能说明 | 依赖关系 |
|---------|---------|---------|
| `nanobot/agent/loop.py` | **核心循环**：Agent 主循环，调用 LLM、处理工具调用 | 核心入口 |
| `nanobot/agent/tools/base.py` | **工具基类**：所有工具的抽象基类定义 | 被所有工具依赖 |
| `nanobot/agent/tools/registry.py` | **工具注册器**：管理工具注册、执行 | 被 loop.py 依赖 |
| `nanobot/providers/base.py` | **LLM 提供商基类**：定义调用大模型的接口 | 被 loop.py 依赖 |
| `nanobot/providers/litellm_provider.py` | **LLM 实现**：基于 LiteLLM 调用各大模型 | 核心 LLM 调用 |
| `nanobot/providers/registry.py` | **提供商注册表**：管理多厂商配置 | 被 litellm_provider 依赖 |
| `nanobot/config/schema.py` | **配置模型**：Pydantic 配置定义 | 全局依赖 |
| `nanobot/config/loader.py` | **配置加载器**：读取/保存配置 | 全局依赖 |
| `nanobot/agent/tools/shell.py` | **Shell 工具**：执行命令行命令 | 核心工具 |
| `nanobot/agent/tools/filesystem.py` | **文件系统工具**：读写文件 | 核心工具 |
| `nanobot/utils/helpers.py` | **通用工具函数**：时间戳、文件名处理等 | 全局依赖 |

**核心工具保留建议**：只保留 `shell.py` 和 `filesystem.py`，其他工具按需选择。

---

## 二、可删除模块（推荐删除）

这些模块提供扩展功能，删除后不影响核心运行：

### 2.1 多平台通道系统（整个目录删除）

| 目录/文件 | 功能 | 删除理由 |
|----------|------|---------|
| `nanobot/channels/` **整个目录** | QQ/Telegram/Discord 等多平台消息通道 | 只用 CLI 不需要 |
| `nanobot/bus/` **整个目录** | 消息总线，配合 channels 使用 | 与 channels 强耦合 |
| `nanobot/agent/tools/message.py` | 消息发送工具 | 依赖 channels |

**影响**：删除后无法通过 QQ/Telegram 等平台交互，仅保留 CLI 模式。

### 2.2 定时/心跳服务（整个目录删除）

| 目录/文件 | 功能 | 删除理由 |
|----------|------|---------|
| `nanobot/cron/` **整个目录** | 定时任务服务 | 非核心功能 |
| `nanobot/heartbeat/` **整个目录** | 心跳检测服务 | 非核心功能 |
| `nanobot/agent/tools/cron.py` | 定时任务工具 | 依赖 cron 服务 |

**影响**：无法使用定时任务和心跳检测功能。

### 2.3 子代理系统

| 文件 | 功能 | 删除理由 |
|-----|------|---------|
| `nanobot/agent/subagent.py` | 子代理管理器 | 扩展功能 |
| `nanobot/agent/tools/spawn.py` | 创建子代理工具 | 依赖 subagent.py |

**影响**：无法创建后台子代理执行异步任务。

### 2.4 扩展工具（可选删除）

| 文件 | 功能 | 删除理由 |
|-----|------|---------|
| `nanobot/agent/tools/web.py` | 网页搜索/抓取工具 | 按需保留 |
| `nanobot/agent/tools/mcp.py` | MCP 协议工具 | 按需保留 |

**建议**：如果你需要网络能力，保留 `web.py`。

### 2.5 语音转录服务

| 文件 | 功能 | 删除理由 |
|-----|------|---------|
| `nanobot/providers/transcription.py` | Groq Whisper 语音转录 | 非核心功能 |

**影响**：无法处理语音消息。

### 2.6 会话管理（可选删除）

| 文件 | 功能 | 删除理由 |
|-----|------|---------|
| `nanobot/session/manager.py` | 会话历史管理 | 可精简 |

**建议**：可以保留基础会话管理，或简化为内存存储。

### 2.7 记忆系统（可选删除）

| 文件 | 功能 | 删除理由 |
|-----|------|---------|
| `nanobot/agent/memory.py` | 双层记忆存储（长期+历史） | 扩展功能 |

**影响**：无法持久化对话记忆，每次对话独立。

### 2.8 技能系统（可精简）

| 目录 | 功能 | 删除理由 |
|-----|------|---------|
| `nanobot/skills/claudhub/` | ClaudHub 技能 | 示例技能 |
| `nanobot/skills/corn/` | Corn 技能 | 示例技能 |
| `nanobot/skills/github/` | GitHub 技能 | 示例技能 |
| `nanobot/skills/memory/` | 记忆技能 | 示例技能 |
| `nanobot/skills/summarize/` | 摘要技能 | 示例技能 |
| `nanobot/skills/tmux/` | Tmux 技能 | 示例技能 |
| `nanobot/skills/weather/` | 天气技能 | 示例技能 |
| `nanobot/skills/skill-creator/` | 技能创建工具 | 开发辅助 |
| `nanobot/agent/skills.py` | 技能系统核心 | 与 skills 目录配合 |

**建议**：保留空 `skills/` 目录和 `skills.py`，删除示例技能。

### 2.9 评估器

| 文件 | 功能 | 删除理由 |
|-----|------|---------|
| `nanobot/utils/evaluator.py` | 后台任务结果评估 | 与 heartbeat 配合 |

**影响**：删除 heartbeat 后此模块无用。

### 2.10 模板系统（可精简）

| 目录 | 功能 | 删除理由 |
|-----|------|---------|
| `nanobot/templates/` | 初始化模板文件 | 可保留精简版 |

---

## 三、精简方案

### 方案 A：最小核心版（推荐）

删除以下目录/文件：

```
nanobot/
├── channels/          # 删除整个目录
├── bus/               # 删除整个目录
├── cron/              # 删除整个目录
├── heartbeat/         # 删除整个目录
├── session/           # 删除整个目录
├── skills/            # 保留空目录，删除内部示例
│   └── (保留 README.md)
├── templates/         # 可保留精简版
├── agent/
│   ├── subagent.py    # 删除
│   ├── memory.py      # 删除
│   ├── skills.py      # 删除
│   └── tools/
│       ├── cron.py    # 删除
│       ├── message.py # 删除
│       ├── spawn.py   # 删除
│       ├── mcp.py     # 删除（可选）
│       └── web.py     # 删除（可选，按需保留）
├── providers/
│   └── transcription.py  # 删除
└── utils/
    └── evaluator.py   # 删除
```

**精简后预计**：约 **20-25 个文件**，代码量减少约 50%。

### 方案 B：保守精简版

保留会话管理和记忆系统，删除：

```
nanobot/
├── channels/          # 删除
├── bus/               # 删除
├── cron/              # 删除
├── heartbeat/         # 删除
├── skills/            # 删除示例，保留框架
├── agent/
│   ├── subagent.py    # 删除
│   └── tools/
│       ├── cron.py    # 删除
│       ├── message.py # 删除
│       └── spawn.py   # 删除
└── providers/
    └── transcription.py  # 删除
```

**精简后预计**：约 **30-35 个文件**。

---

## 四、需要修改的依赖代码

删除上述模块后，需要修改以下文件中的导入：

### 4.1 `nanobot/agent/__init__.py`

删除对已删除模块的导出。

### 4.2 `nanobot/cli/commands.py`

可能需要移除：
- channels 相关的启动逻辑
- cron/heartbeat 服务启动代码

### 4.3 `nanobot/agent/loop.py`

检查是否有可选依赖的导入，添加条件判断。

---

## 五、精简步骤建议

1. **备份原项目**
2. **创建测试用例**（确保核心功能正常）
3. **按顺序删除**：
   - 先删除 `channels/` 和 `bus/`
   - 再删除 `cron/` 和 `heartbeat/`
   - 然后删除 `subagent.py` 和 `spawn.py`
   - 最后删除 skills 示例
4. **每次删除后运行测试**
5. **修复导入错误**
6. **精简配置 schema**（移除已删除功能的配置项）

---

## 六、保留的核心功能

精简后项目仍支持：

- ✅ 通过 LiteLLM 调用各大模型（OpenAI/Anthropic/DeepSeek 等）
- ✅ Agent 主循环运行
- ✅ 工具注册与执行
- ✅ Shell 命令执行
- ✅ 文件读写操作
- ✅ 基础配置管理
- ✅ CLI 命令行交互

---

## 七、风险提示

1. **配置兼容性**：删除后旧配置文件可能报错，需同步更新 `config/schema.py`
2. **隐式依赖**：某些模块可能有隐藏的循环导入，需逐步测试
3. **CLI 命令**：部分 CLI 子命令可能失效，需更新 `commands.py`

---

## 八、总结

| 项目 | 精简前 | 精简后（方案A） |
|-----|-------|---------------|
| Python 文件数 | 52 | ~20 |
| 目录数 | 30+ | ~15 |
| 核心功能 | 完整 | 保留 |
| 扩展性 | 高 | 低 |
| 维护复杂度 | 高 | 低 |

**推荐执行方案 A**，保留核心的 LLM 调用、循环工作、工具执行功能，删除所有多平台通道、定时任务、子代理、记忆系统等扩展模块。
