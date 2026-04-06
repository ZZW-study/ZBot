# AgentLoop 模块详解

> 文件路径：`nanobot/agent/loop.py`

## 一、模块概述

`AgentLoop` 是 Agent 的**运行时核心**，负责将"用户输入 → 模型推理 → 工具执行 → 会话落盘"这一完整链路串联起来。

### 核心职责

1. **消息消费**：从消息总线或直接调用获取用户输入
2. **会话管理**：找到或创建对应 session，构造模型上下文
3. **模型交互**：处理模型的普通回复或工具调用
4. **会话落盘**：把本轮消息安全地写回 session
5. **记忆归档**：在合适时机触发长期记忆归档

---

## 二、类结构总览

```
AgentLoop
├── 初始化与配置
│   ├── __init__()
│   ├── _register_default_tools()
│   └── _connect_mcp()
│
├── 主循环入口
│   ├── run()                    # 消息总线消费主循环
│   ├── process_direct()         # CLI/脚本直接调用入口
│   └── stop()                   # 停止主循环
│
├── 消息处理链路
│   ├── _dispatch()              # 消息分发（带锁串行处理）
│   ├── _process_message()       # 消息类型判断与命令处理
│   ├── _run_turn()              # 单轮对话执行
│   └── _run_agent_loop()        # 模型-工具循环
│
├── 会话与记忆管理
│   ├── _save_turn()             # 保存本轮消息到 session
│   ├── _schedule_consolidation()# 安排后台记忆归档
│   ├── _run_consolidation()     # 执行归档任务
│   ├── _consolidate_memory()    # 调用 MemoryStore 归档
│   └── _archive_and_reset_session() # /new 命令的归档+重置
│
└── 辅助方法
    ├── _set_tool_context()
    ├── _strip_think()
    ├── _tool_hint()
    ├── _resolve_system_target()
    ├── _annotate_tools_used()
    └── _strip_runtime_context()
```

---

## 三、核心函数详解

### 3.1 初始化相关

#### `__init__()`

**作用**：初始化 Agent 运行时所需的所有依赖和内部状态。

**关键属性**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `bus` | MessageBus | 消息总线，用于接收 inbound 消息和发布 outbound 回复 |
| `provider` | LLMProvider | LLM 提供者抽象，负责与模型交互 |
| `workspace` | Path | 工作目录，文件工具基于此执行操作 |
| `model` | str | 使用的模型名 |
| `max_iterations` | int | 单轮最大工具调用次数（默认 40），防止无限循环 |
| `temperature` | float | 模型采样温度 |
| `max_tokens` | int | 模型返回最大 token 限制 |
| `memory_window` | int | 会话历史窗口大小 |
| `context` | ContextBuilder | 负责构建模型输入的 messages |
| `sessions` | SessionManager | 会话管理器 |
| `tools` | ToolRegistry | 工具注册中心 |
| `_processing_lock` | asyncio.Lock | 全局消息处理锁，保证串行处理 |
| `_active_tasks` | dict | 跟踪每个 session 下正在执行的 asyncio.Task |
| `_consolidating` | set | 正在执行归档的 session 集合 |

---

#### `_register_default_tools()`

**作用**：注册默认工具集。

**注册的工具**：

| 工具类 | 说明 |
|--------|------|
| `ReadFileTool` | 读取文件 |
| `WriteFileTool` | 写入文件 |
| `EditFileTool` | 编辑文件 |
| `ListDirTool` | 列出目录 |
| `ExecTool` | 执行 shell 命令 |
| `WebSearchTool` | 网络搜索 |
| `WebFetchTool` | 网络请求 |
| `CronTool` | 定时任务（仅当提供 CronService 时） |

**参数影响**：
- `restrict_to_workspace=True` 时，文件工具会被限制在工作目录内

---

#### `_connect_mcp()`

**作用**：懒连接 MCP（Model Context Protocol）服务器。

**特点**：
- 只在首次真正使用 Agent 时才连接
- 使用 `AsyncExitStack` 管理连接生命周期
- 连接失败会在下次收到消息时重试

---

### 3.2 主循环入口

#### `run()`

**作用**：从消息总线持续消费入站消息，是 Agent 的主事件循环。

**执行流程**：

```
while _running:
    1. 从 bus.consume_inbound() 获取消息（带 1 秒超时）
    2. 如果是 /stop 命令 → 调用 _handle_stop()
    3. 否则 → 创建 asyncio.Task 执行 _dispatch()
    4. 将 task 记录到 _active_tasks（供 /stop 取消）
```

**关键点**：
- 使用 `create_task` 将消息处理放到后台，主循环快速返回继续消费
- `/stop` 命令可以取消当前会话的所有活跃任务

---

#### `process_direct()`

**作用**：供 CLI 或脚本直接调用的一次性入口。

**参数**：
- `content`: 用户输入内容
- `session_key`: 会话标识（默认 "cli:direct"）
- `channel`: 渠道（默认 "cli"）
- `chat_id`: 聊天 ID（默认 "direct"）
- `on_progress`: 进度回调

**返回**：模型的最终回复文本

---

#### `stop()`

**作用**：请求主循环停止，设置 `_running = False`。

---

### 3.3 消息处理链路（核心）

#### `_dispatch(msg)`

**作用**：串行处理单条消息，负责把结果发布到总线。

**执行流程**：

```
async with _processing_lock:  # 全局锁，保证串行处理
    1. 调用 _process_message(msg) 获取回复
    2. 如果有回复 → 发布到 bus.publish_outbound()
    3. 如果是 cli 渠道且无回复 → 发布空消息
    4. 异常处理 → 发布错误消息
```

**为什么需要锁**：
- 简化会话落盘逻辑
- 避免并发写导致的竞态问题

---

#### `_process_message(msg)`

**作用**：处理单条消息，返回 `OutboundMessage`。

**执行流程**：

```
1. 判断消息类型
   ├── channel == "system" → 系统消息路径
   │   ├── 解析目标 channel/chat_id
   │   ├── 获取或创建 session
   │   └── 调用 _run_turn() 执行对话
   │
   └── 普通消息路径
       ├── 处理内建命令
       │   ├── /new → _archive_and_reset_session()
       │   └── /help → 返回帮助文本
       │
       ├── _schedule_consolidation() 安排后台归档
       └── 调用 _run_turn() 执行对话
```

**内建命令**：

| 命令 | 作用 |
|------|------|
| `/new` | 归档当前会话并开始新会话 |
| `/help` | 显示帮助信息 |
| `/stop` | 在 `run()` 中处理，取消当前任务 |

---

#### `_run_turn(session, content, channel, chat_id, media, on_progress)`

**作用**：执行一轮标准对话，是普通消息和 system 消息共用的主路径。

**执行流程**：

```
1. _set_tool_context(channel, chat_id)  # 注入工具上下文
2. session.get_history(memory_window)   # 获取历史消息
3. context.build_messages()             # 构造模型请求
4. _run_agent_loop()                    # 执行模型-工具循环
5. _save_turn()                         # 保存本轮消息
6. sessions.save(session)               # 持久化会话
7. 返回 final_content
```

---

#### `_run_agent_loop(initial_messages, on_progress)`

**作用**：驱动"模型回复 → 工具执行 → 再喂回模型"的循环。

**返回值**：
1. `final_content`: 最终用户可见回复
2. `tools_used`: 本轮实际调用过的工具列表
3. `messages`: 完整消息链，用于写回 session

**执行流程**：

```
for _ in range(max_iterations):
    1. provider.chat(messages, tools) → 调用模型

    2. 如果模型返回工具调用 (has_tool_calls):
       ├── 发送进度提示（如果有 on_progress）
       ├── 将 tool_calls 写入消息链
       ├── 逐个执行工具：tools.execute(name, args)
       └── 将工具结果追加到消息链
       → continue（下一轮循环）

    3. 如果模型没有工具调用:
       ├── _strip_think() 移除思考块
       ├── 将 assistant 消息写入消息链
       └── break（循环结束）

4. 如果达到 max_iterations 仍未结束:
   └── 返回提示信息，建议用户拆分任务
```

**关键点**：
- 每轮都把"当前消息链 + 工具 schema"发给模型
- 模型自行决定是直接回答还是调用工具
- 工具结果会追加到消息链，供下一轮模型消费

---

### 3.4 会话与记忆管理

#### `_save_turn(session, messages, skip, tools_used)`

**作用**：把本轮新增消息写回 session。

**参数**：
- `messages`: 完整消息链（包含 system + 历史 + 本轮）
- `skip`: 跳过前 N 条（通常是 1 + len(history)）
- `tools_used`: 本轮使用的工具列表

**处理逻辑**：

```
1. 跳过 system prompt 和已有历史，只保留本轮新增消息
2. _annotate_tools_used() → 标注使用的工具
3. 遍历消息：
   ├── assistant 消息：空内容且无 tool_calls 则跳过
   ├── tool 消息：超过 500 字符则截断
   └── user 消息：移除运行时元信息
4. 添加时间戳
5. 追加到 session.messages
```

---

#### `_schedule_consolidation(session)`

**作用**：在满足阈值时，为会话安排后台记忆归档任务。

**触发条件**：
- 未归档消息数 >= memory_window
- 当前 session 未在归档中

**执行**：
- 创建 `asyncio.Task` 执行 `_run_consolidation()`
- 任务加入 `_consolidation_tasks` 集合

---

#### `_run_consolidation(session)`

**作用**：真正执行后台归档任务。

**流程**：
```
async with session 专属锁:
    await _consolidate_memory(session)
finally:
    从 _consolidating 中移除 session.key
```

---

#### `_consolidate_memory(session, archive_all=False)`

**作用**：调用 `MemoryStore` 做长期记忆归档。

**实现**：
```python
return await self.context.memory.consolidate(
    session,
    provider,
    model,
    archive_all=archive_all,
    memory_window=memory_window,
)
```

---

#### `_archive_and_reset_session(session)`

**作用**：归档当前会话剩余消息，并把会话清空重置（用于 `/new` 命令）。

**流程**：
```
1. 获取归档锁
2. 将未归档消息快照交给 _consolidate_memory(archive_all=True)
3. 归档成功后：
   ├── session.clear() 清空消息
   ├── sessions.save(session) 保存
   └── sessions.invalidate() 使缓存失效
```

---

### 3.5 辅助方法

#### `_set_tool_context(channel, chat_id)`

**作用**：把当前 channel/chat_id 注入给支持上下文的工具。

**用途**：某些工具需要知道当前会话信息（如发送消息到特定渠道）。

---

#### `_strip_think(text)`

**作用**：移除模型输出中的 `<think>...</think>` 思维块。

**用途**：某些模型会在输出中包含思考过程，这个方法清理后只保留最终答案。

---

#### `_tool_hint(tool_calls)`

**作用**：把工具调用列表压缩成适合进度展示的短提示。

**示例输出**：
- `read_file("src/main.py")`
- `write_file("config.json"), exec("npm install")`

---

#### `_resolve_system_target(chat_id)`

**作用**：解析 system 消息的目标 channel/chat_id。

**格式**：
- 如果 chat_id 包含 `:` → 拆分为 `(channel, chat_id)`
- 否则 → 默认返回 `("cli", chat_id)`

---

#### `_annotate_tools_used(messages, tools_used)`

**作用**：把本轮使用过的工具集合挂到最后一条 assistant 消息上。

**用途**：便于后续分析或展示。

---

#### `_strip_runtime_context(content)`

**作用**：从 user 消息里移除运行时元信息。

**原因**：运行时信息只对当前轮推理有意义，长期保留在 session 里会污染历史。

---

## 四、函数调用关系图

### 4.1 主循环流程

```
run()
  │
  ├── [收到消息] → asyncio.create_task(_dispatch(msg))
  │                     │
  │                     └── _process_message(msg)
  │                              │
  │                              ├── [system 消息] → _run_turn()
  │                              │                         │
  │                              │                         └── _run_agent_loop()
  │                              │
  │                              ├── [/new 命令] → _archive_and_reset_session()
  │                              │
  │                              └── [普通消息] → _run_turn()
  │                                                       │
  │                                                       ├── _set_tool_context()
  │                                                       ├── context.build_messages()
  │                                                       ├── _run_agent_loop()
  │                                                       ├── _save_turn()
  │                                                       └── sessions.save()
  │
  └── [/stop 命令] → _handle_stop()
```

### 4.2 模型-工具循环

```
_run_agent_loop(messages, on_progress)
  │
  └── for iteration in range(max_iterations):
        │
        ├── provider.chat(messages, tools)  # 调用模型
        │
        ├── [有工具调用]
        │     │
        │     ├── on_progress() 发送进度
        │     ├── context.add_assistant_message() 记录调用意图
        │     │
        │     └── for tool_call in tool_calls:
        │           │
        │           ├── tools.execute(name, args)  # 执行工具
        │           └── context.add_tool_result()  # 追加结果
        │
        └── [无工具调用]
              │
              ├── _strip_think() 清理输出
              ├── context.add_assistant_message()
              └── break  # 循环结束
```

### 4.3 记忆归档流程

```
_process_message()
  │
  └── _schedule_consolidation(session)
          │
          └── [满足阈值] → asyncio.create_task(_run_consolidation())
                                  │
                                  └── _consolidate_memory()
                                          │
                                          └── context.memory.consolidate()
```

---

## 五、关键设计点

### 5.1 并发控制

| 机制 | 作用 |
|------|------|
| `_processing_lock` | 全局消息处理锁，保证串行处理 |
| `_consolidation_locks` | 每个 session 专属的归档锁 |
| `_active_tasks` | 跟踪活跃任务，支持 `/stop` 取消 |
| `_consolidating` | 防止同一 session 重复归档 |

### 5.2 消息截断策略

| 场景 | 策略 |
|------|------|
| tool 结果 | 超过 500 字符截断 |
| 进度日志 | 参数预览最多 40 字符 |
| 日志输出 | 消息预览 80-120 字符 |

### 5.3 错误处理

- 模型返回错误 → 返回友好提示
- 工具执行异常 → 结果作为错误消息喂回模型
- 达到最大迭代 → 建议用户拆分任务

---

## 六、使用示例

### 6.1 作为服务运行

```python
agent = AgentLoop(
    bus=message_bus,
    provider=llm_provider,
    workspace=Path("./workspace"),
)
await agent.run()  # 阻塞，持续消费消息
```

### 6.2 CLI 直接调用

```python
agent = AgentLoop(...)
response = await agent.process_direct(
    content="帮我读取 config.json 文件",
    session_key="cli:user123",
)
print(response)
```

### 6.3 停止服务

```python
agent.stop()  # 设置标志，主循环会在下次检查时退出
await agent.close_mcp()  # 关闭 MCP 连接
```

---

## 七、依赖关系

```
AgentLoop
├── nanobot.agent.context.ContextBuilder      # 消息构建
├── nanobot.agent.tools.registry.ToolRegistry # 工具管理
├── nanobot.agent.tools.*                     # 具体工具实现
├── nanobot.bus.events.InboundMessage         # 入站消息
├── nanobot.bus.events.OutboundMessage        # 出站消息
├── nanobot.bus.queue.MessageBus              # 消息总线
├── nanobot.providers.base.LLMProvider        # 模型抽象
├── nanobot.session.manager.SessionManager    # 会话管理
└── nanobot.config.schema.*                   # 配置定义
```
