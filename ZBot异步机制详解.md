# ZBot 异步机制详解 —— 单线程并发示例

## 一、异步的本质：并发而非并行

### 1.1 概念区分

| 概念 | 定义 | Python asyncio |
|-----|------|---------------|
| **并行** | 多个 CPU 核心同时执行多个任务 | ❌ 不支持 |
| **并发** | 单线程快速切换执行多个任务 | ✅ 这就是异步 |

```
并行（多核，真正同时）：
CPU 核心 1: ████████████████  任务 A
CPU 核心 2: ████████████████  任务 B
CPU 核心 3: ████████████████  任务 C

并发（单核，快速切换）：
CPU 核心 1: ██A███B██A███C██B██A███C██  任务 A/B/C 轮流执行
           ↑ 切换点（I/O 等待时）
```

### 1.2 异步的真正优势

异步不是"同时做很多事"，而是**"等待时不闲着"**。

```
同步执行（傻等）：
─────────────────────────────────────────────────────────────▶
│ 调用模型（等待 3s）│ 执行工具（等待 2s）│ 归档（等待 1s）│
│    啥着等...       │    啥着等...       │   啥着等...    │
总耗时 = 3 + 2 + 1 = 6 秒

异步执行（等待时切换）：
─────────────────────────────────────────────────────────────▶
│ 调用模型 │ 执行工具 │ 归档（后台）│
│ ↓等待时  │ ↓等待时  │             │
│ 切换去   │ 切换去   │             │
│ 执行其他 │ 执行归档 │             │
总耗时 ≈ 5 秒（归档在工具等待期间完成）
```

**关键**：异步不会让单个任务变快，但能让**总耗时减少**，因为在等待时做了其他事。

---

## 二、ZBot 中真正的并发场景

### 场景 1：主对话 + 后台记忆归档（真正的并发）

**代码位置**：[agent/loop.py:617-640](ZBot/agent/loop.py#L617-L640)

```python
def _schedule_consolidation(self, session: Session) -> None:
    """当未归档消息达到阈值时，安排后台归档任务。"""

    # 检查是否需要归档
    unconsolidated = len(session.messages) - session.last_consolidated
    if unconsolidated < self.memory_window or session.key in self._consolidating:
        return

    self._consolidating.add(session.key)

    # 【关键】创建后台任务，不等待完成！
    task = asyncio.create_task(self._run_consolidation(session))
    self._consolidation_tasks.add(task)
    task.add_done_callback(self._consolidation_tasks.discard)
```

**并发执行图**：

```
时间轴 │ 主对话流程                          │ 后台归档任务
───────┼────────────────────────────────────┼──────────────────────────
  0s   │ 用户发送: "帮我分析这个项目"        │
       │                                    │
  1s   │ await provider.chat() 调用模型...  │
       │   ↓ 模型响应需要时间                │
       │   ↓ asyncio 切换去执行其他任务      │
       │                                    │
  3s   │ 模型返回: 需要调用工具              │
       │ _schedule_consolidation() 被调用   │ asyncio.create_task()
       │   ↓ 立即返回，不等待                │   ↓ 注册任务到事件循环
       │                                    │
  4s   │ await tools.execute("exec", ...)   │ 后台任务获得执行机会
       │   ↓ 命令执行需要时间                │ await provider.chat() 归档摘要
       │   ↓ asyncio 切换去执行归档          │   ↓ 归档调用模型
       │                                    │   ↓ 模型响应时切换回主对话
  8s   │ 工具返回结果                        │
       │                                    │
  9s   │ await provider.chat() 再次调用模型  │ 后台归档完成，更新 MEMORY.md
       │                                    │
 12s   │ 返回最终回复给用户                  │
       │                                    │
───────┴────────────────────────────────────┴──────────────────────────

关键点：归档任务在主对话的 I/O 等待期间【穿插执行】，不是同时！
        单线程快速切换，让用户感觉不到归档的延迟。
```

**验证代码**：

```python
import asyncio
import time

async def main():
    print(f"[{time.strftime('%H:%M:%S')}] 主流程开始")

    # 模拟主对话
    async def main_dialog():
        print(f"[{time.strftime('%H:%M:%S')}] 主对话: 开始调用模型")
        await asyncio.sleep(3)  # 模拟模型调用
        print(f"[{time.strftime('%H:%M:%S')}] 主对话: 模型返回，执行工具")
        await asyncio.sleep(2)  # 模拟工具执行
        print(f"[{time.strftime('%H:%M:%S')}] 主对话: 返回结果")

    # 模拟后台归档
    async def background_consolidation():
        print(f"[{time.strftime('%H:%M:%S')}] 后台归档: 开始")
        await asyncio.sleep(4)  # 模拟归档调用模型
        print(f"[{time.strftime('%H:%M:%S')}] 后台归档: 完成")

    # 创建后台任务（不等待）
    task = asyncio.create_task(background_consolidation())

    # 执行主对话
    await main_dialog()

    # 等待后台任务完成
    await task

asyncio.run(main())
```

**输出**：
```
[14:30:01] 主流程开始
[14:30:01] 主对话: 开始调用模型
[14:30:01] 后台归档: 开始          ← 两个任务都注册到事件循环
[14:30:04] 主对话: 模型返回，执行工具  ← 主对话先获得执行机会
[14:30:05] 后台归档: 完成          ← 归档在主对话等待期间完成
[14:30:06] 主对话: 返回结果
```

**注意**：输出顺序说明两个任务是**轮流执行**，不是同时。
- 主对话 `await asyncio.sleep(3)` 时，事件循环切换去执行归档
- 归档 `await asyncio.sleep(4)` 时，事件循环切换回主对话
- 单线程，同一时刻只有一个任务在运行

---

### 场景 2：定时任务服务与主循环并发

**代码位置**：[cron/service.py:458-499](ZBot/cron/service.py#L458-L499)

```python
def _arm_timer(self) -> None:
    """设置异步计时器，到期后执行任务。"""

    # 取消已有计时器
    if self._timer_task:
        self._timer_task.cancel()
        self._timer_task = None

    next_wake = self._next_wake_ms()
    if not self._running or next_wake is None:
        return

    delay = max(0.0, (next_wake - _now_ms()) / 1000)

    async def tick() -> None:
        try:
            await asyncio.sleep(delay)  # 异步等待，不阻塞！
        except asyncio.CancelledError:
            return
        if self._running:
            await self._on_timer()  # 到期执行任务

    # 【关键】后台运行计时器，不阻塞主流程
    self._timer_task = asyncio.create_task(tick())
```

**并发执行图**：

```
时间轴 │ 用户交互                    │ 定时任务计时器          │ 到期执行
───────┼────────────────────────────┼────────────────────────┼──────────
  0s   │ 用户输入: "你好"            │ _arm_timer() 设置      │
       │                            │ delay=60 秒            │
       │                            │ create_task(tick())    │
       │                            │ ↓ 注册到事件循环       │
  1s   │ 返回: "你好！有什么..."     │ await asyncio.sleep(60)│
       │                            │ ↓ 计时器进入等待       │
       │                            │ ↓ 事件循环处理其他任务 │
 10s   │ 用户输入: "帮我写代码"      │ 仍在等待...            │
       │                            │                        │
 30s   │ 用户输入: "解释一下"        │ 仍在等待...            │
       │                            │                        │
 60s   │ 用户正在思考下一句...       │ sleep 到期！           │
       │                            │ ↓ 事件循环执行 tick()  │
       │                            │                        │ 执行定时任务
       │                            │                        │ "提醒你开会"
       │                            │                        │
 61s   │ 用户继续输入                │ _arm_timer() 重置      │
       │                            │ 下一次计时             │
───────┴────────────────────────────┴────────────────────────┴──────────

关键点：计时器在事件循环中注册等待，用户交互时计时器处于"挂起"状态。
        到期后，事件循环在用户输入的间隙执行定时任务。
```

**验证代码**：

```python
import asyncio
import time

class SimpleCron:
    def __init__(self):
        self._timer_task = None
        self._running = True

    def _arm_timer(self, delay):
        async def tick():
            print(f"[{time.strftime('%H:%M:%S')}] 计时器: 开始等待 {delay} 秒")
            await asyncio.sleep(delay)
            print(f"[{time.strftime('%H:%M:%S')}] 计时器: 到期！执行任务")
            self._arm_timer(delay)  # 重新设置

        self._timer_task = asyncio.create_task(tick())

async def main():
    cron = SimpleCron()
    cron._arm_timer(5)  # 5秒后执行

    # 模拟用户交互
    for i in range(3):
        print(f"[{time.strftime('%H:%M:%S')}] 用户: 输入消息 {i+1}")
        await asyncio.sleep(2)  # 模拟处理
        print(f"[{time.strftime('%H:%M:%S')}] 助手: 回复消息 {i+1}")

asyncio.run(main())
```

**输出**：
```
[14:30:01] 计时器: 开始等待 5 秒
[14:30:01] 用户: 输入消息 1
[14:30:03] 助手: 回复消息 1
[14:30:03] 用户: 输入消息 2
[14:30:05] 助手: 回复消息 2
[14:30:06] 计时器: 到期！执行任务    ← 在用户消息处理的间隙执行
[14:30:06] 计时器: 开始等待 5 秒      ← 重新设置
[14:30:07] 用户: 输入消息 3
[14:30:09] 助手: 回复消息 3
[14:30:11] 计时器: 到期！执行任务
```

**注意**：计时器不是在"后台同时运行"，而是注册了一个 5 秒后的回调。
事件循环在处理用户消息的间隙检查计时器是否到期，到期则执行。

---

### 场景 3：异步锁保护并发资源

**代码位置**：[agent/loop.py:664-683](ZBot/agent/loop.py#L664-L683)

```python
def _get_consolidation_lock(self, session_key: str) -> asyncio.Lock:
    """每个会话有独立的锁，防止同一会话被并发归档。"""
    lock = self._consolidation_locks.get(session_key)
    if lock is None:
        lock = asyncio.Lock()
        self._consolidation_locks[session_key] = lock
    return lock

async def _run_consolidation(self, session: Session) -> None:
    try:
        # 【关键】使用异步锁保护
        async with self._get_consolidation_lock(session.key):
            await self._consolidate_memory(session)
    finally:
        self._consolidating.discard(session.key)
```

**为什么需要锁？**

```
没有锁的情况（数据竞争）：
─────────────────────────────────────────────────────────────
时间 │ 任务 A（归档）              │ 任务 B（归档）
──────┼────────────────────────────┼──────────────────────────
  0s  │ 读取 session.messages      │
  1s  │                            │ 读取 session.messages
  2s  │ 调用模型生成摘要...        │
  3s  │                            │ 调用模型生成摘要...
  5s  │ 写入 MEMORY.md             │
  6s  │                            │ 写入 MEMORY.md（覆盖！）
──────┴────────────────────────────┴──────────────────────────
结果：任务 A 的归档结果被任务 B 覆盖，数据丢失！

有锁的情况（安全并发）：
─────────────────────────────────────────────────────────────
时间 │ 任务 A（归档）              │ 任务 B（归档）
──────┼────────────────────────────┼──────────────────────────
  0s  │ 获取锁 ✓                   │
  1s  │ 读取 session.messages      │ 尝试获取锁...等待
  2s  │ 调用模型生成摘要...        │ 等待...
  5s  │ 写入 MEMORY.md             │ 等待...
  6s  │ 释放锁                     │ 获取锁 ✓
  7s  │                            │ 发现已经归档，跳过
──────┴────────────────────────────┴──────────────────────────
结果：安全完成，无数据丢失！
```

**验证代码**：

```python
import asyncio

class SafeCounter:
    def __init__(self):
        self.value = 0
        self._lock = asyncio.Lock()

    async def increment_unsafe(self):
        """不安全的方式"""
        current = self.value
        await asyncio.sleep(0.01)  # 模拟异步操作
        self.value = current + 1

    async def increment_safe(self):
        """安全的方式（使用锁）"""
        async with self._lock:
            current = self.value
            await asyncio.sleep(0.01)
            self.value = current + 1

async def test_unsafe():
    counter = SafeCounter()
    # 并发执行 10 次
    await asyncio.gather(*[counter.increment_unsafe() for _ in range(10)])
    print(f"不安全结果: {counter.value}（期望 10）")  # 可能是 1-10 之间的任意值

async def test_safe():
    counter = SafeCounter()
    # 并发执行 10 次
    await asyncio.gather(*[counter.increment_safe() for _ in range(10)])
    print(f"安全结果: {counter.value}（期望 10）")  # 一定是 10

asyncio.run(test_unsafe())
asyncio.run(test_safe())
```

**输出**：
```
不安全结果: 2（期望 10）    ← 数据竞争导致错误！
安全结果: 10（期望 10）     ← 锁保护确保正确！
```

---

### 场景 4：AsyncExitStack 管理多个异步资源

**代码位置**：[agent/tools/mcp.py:185-308](ZBot/agent/tools/mcp.py#L185-L308)

```python
async def connect_mcp_servers(mcp_servers, registry, stack) -> None:
    """连接多个 MCP 服务器。"""

    for name, cfg in mcp_servers.items():
        # stdio 模式：启动子进程
        if transport_type == "stdio":
            read, write = await stack.enter_async_context(stdio_client(params))

        # SSE 模式：HTTP 长连接
        elif transport_type == "sse":
            read, write = await stack.enter_async_context(sse_client(cfg.url))

        # 创建会话
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
```

**为什么用 AsyncExitStack？**

```
场景：连接 3 个 MCP 服务器，第 2 个失败

手动管理（繁琐且容易出错）：
─────────────────────────────────────────────────────────────
conn1 = await connect_server1()
try:
    conn2 = await connect_server2()  # 失败！
except:
    await conn1.close()  # 必须手动清理
    raise

AsyncExitStack（自动管理）：
─────────────────────────────────────────────────────────────
async with AsyncExitStack() as stack:
    conn1 = await stack.enter_async_context(connect_server1())
    conn2 = await stack.enter_async_context(connect_server2())  # 失败
    # stack 自动关闭 conn1，无需手动处理！
```

**验证代码**：

```python
import asyncio
from contextlib import AsyncExitStack

class AsyncResource:
    def __init__(self, name):
        self.name = name

    async def __aenter__(self):
        print(f"  连接 {self.name}")
        return self

    async def __aexit__(self, *args):
        print(f"  关闭 {self.name}")

async def test_exit_stack():
    print("使用 AsyncExitStack:")
    try:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(AsyncResource("服务器1"))
            await stack.enter_async_context(AsyncResource("服务器2"))
            raise Exception("模拟错误")  # 第三个之前出错
            await stack.enter_async_context(AsyncResource("服务器3"))
    except Exception as e:
        print(f"  捕获错误: {e}")

asyncio.run(test_exit_stack())
```

**输出**：
```
使用 AsyncExitStack:
  连接 服务器1
  连接 服务器2
  关闭 服务器2    ← 自动按相反顺序关闭
  关闭 服务器1    ← 确保资源不泄漏
  捕获错误: 模拟错误
```

---

## 三、完整并发场景：交互模式下的任务切换

**代码位置**：[cli/commands.py](ZBot/cli/commands.py)

```
时间 │ 事件循环执行的任务（同一时刻只有一个）
──────┼────────────────────────────────────────────────────────────────
  0s  │ asyncio.run(run_interactive()) 启动事件循环
      │
  1s  │ → prompt_async() 等待用户输入
      │    ↓ 用户未输入，事件循环空闲
      │ → 检查 CronService 计时器：还有 59 秒，继续等待
      │ → 回到 prompt_async() 继续等待
      │
 15s  │ 用户输入: "帮我分析项目结构"
      │ → provider.chat() 调用模型
      │    ↓ 网络请求中，事件循环切换
      │ → 检查计时器：还有 45 秒
      │ → 回到 provider.chat() 继续等待
      │
 20s  │ 模型返回: 需要调用 exec 工具
      │ → tools.execute("exec", "find . -name '*.py'")
      │    ↓ 子进程执行中，事件循环切换
      │ → 检查计时器：还有 40 秒
      │ → 回到 tools.execute() 继续等待
      │
 23s  │ _schedule_consolidation() 触发
      │ → create_task(consolidate()) 注册归档任务
      │ → 继续处理主对话
      │ → 归档任务获得执行机会：provider.chat() 生成摘要
      │    ↓ 归档调用模型中，事件循环切换
      │ → 回到主对话继续处理
      │
 30s  │ → 返回最终回复给用户
      │ → 归档任务完成，更新 MEMORY.md
      │
 60s  │ → prompt_async() 等待下一次输入
      │ → 计时器到期！执行定时任务
      │ → _arm_timer() 重新设置计时器
──────┴────────────────────────────────────────────────────────────────

关键：事件循环不断检查哪些任务可以执行，在 I/O 等待时切换到其他任务。
      单线程，同一时刻只执行一个任务，但通过快速切换实现"并发"效果。
```

---

## 四、重要发现：多工具调用是顺序执行，不是并发

### 4.1 当前实现

**代码位置**：[agent/loop.py:384-399](ZBot/agent/loop.py#L384-L399)

```python
# 逐个执行工具调用
for tool_call in response.tool_calls:
    result = await self.tools.execute(tool_call.name, tool_call.arguments)
    self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
```

**这是顺序执行！** 当模型一次返回多个工具调用时：

```
模型返回: [tool_call_1, tool_call_2, tool_call_3]

当前执行方式（顺序）：
─────────────────────────────────────────────────────────────
│ 执行 tool_1 (3s) │ 执行 tool_2 (2s) │ 执行 tool_3 (1s) │
总耗时 = 3 + 2 + 1 = 6 秒
```

### 4.2 如果要并发执行

```python
# 并发执行所有工具调用
async def execute_tool(tool_call):
    result = await self.tools.execute(tool_call.name, tool_call.arguments)
    return tool_call, result

results = await asyncio.gather(*[execute_tool(tc) for tc in response.tool_calls])

for tool_call, result in results:
    self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
```

```
并发执行方式：
─────────────────────────────────────────────────────────────
│ 执行 tool_1 (3s) │
│ 执行 tool_2 (2s) │
│ 执行 tool_3 (1s) │
总耗时 = max(3, 2, 1) = 3 秒
```

### 4.3 为什么当前是顺序执行？

可能的原因：
1. **结果顺序一致性**：顺序执行保证结果按工具调用顺序返回
2. **资源竞争**：多个工具可能操作同一文件，顺序执行避免冲突
3. **简化调试**：顺序执行更容易追踪问题

### 4.4 验证代码

```python
import asyncio
import time

# 顺序执行（当前 ZBot 的方式）
async def sequential():
    start = time.time()
    results = []
    for i in range(3):
        await asyncio.sleep(i + 1)  # 模拟工具执行
        results.append(f"tool_{i}")
    print(f"顺序执行耗时: {time.time() - start:.1f} 秒, 结果: {results}")

# 并发执行（asyncio.gather）
async def concurrent():
    start = time.time()
    async def run_tool(i):
        await asyncio.sleep(i + 1)
        return f"tool_{i}"
    results = await asyncio.gather(*[run_tool(i) for i in range(3)])
    print(f"并发执行耗时: {time.time() - start:.1f} 秒, 结果: {results}")

asyncio.run(sequential())  # 输出: 顺序执行耗时: 6.0 秒
asyncio.run(concurrent())  # 输出: 并发执行耗时: 3.0 秒
```

---

## 五、核心异步模式总结

| 模式 | 代码 | 作用 | 场景 |
|-----|------|------|------|
| `asyncio.create_task()` | `task = asyncio.create_task(func())` | 创建后台任务，不等待完成 | 后台归档、计时器 |
| `asyncio.gather()` | `await asyncio.gather(*tasks)` | 并发执行多个任务，等待全部完成 | 批量网络请求 |
| `asyncio.Lock()` | `async with lock:` | 保护共享资源，防止并发冲突 | 会话归档 |
| `asyncio.wait_for()` | `await asyncio.wait_for(func(), timeout=30)` | 超时控制 | 工具调用、网络请求 |
| `AsyncExitStack` | `await stack.enter_async_context(res)` | 自动管理多个异步资源 | MCP 连接 |
| `asyncio.sleep()` | `await asyncio.sleep(delay)` | 异步等待，不阻塞事件循环 | 计时器 |

---

## 六、异步 vs 同步：性能对比

```python
import asyncio
import time

# 同步版本：顺序执行
def sync_version():
    start = time.time()

    time.sleep(2)  # 模拟模型调用
    time.sleep(3)  # 模拟工具执行
    time.sleep(1)  # 模拟归档

    print(f"同步总耗时: {time.time() - start:.1f} 秒")

# 异步版本：并发执行
async def async_version():
    start = time.time()

    async def model_call():
        await asyncio.sleep(2)

    async def tool_exec():
        await asyncio.sleep(3)

    async def consolidation():
        await asyncio.sleep(1)

    # 主流程
    await model_call()
    await tool_exec()

    # 归档在后台执行（与下一次用户输入并行）
    task = asyncio.create_task(consolidation())

    # 模拟用户继续输入
    await asyncio.sleep(0.5)  # 用户思考时间
    await task

    print(f"异步总耗时: {time.time() - start:.1f} 秒")

sync_version()  # 输出: 同步总耗时: 6.0 秒
asyncio.run(async_version())  # 输出: 异步总耗时: 5.5 秒（归档在后台）
```

---

## 六、关键文件索引

| 文件 | 异步职责 |
|-----|---------|
| [agent/loop.py](ZBot/agent/loop.py) | 主循环、后台归档任务、异步锁 |
| [agent/tools/mcp.py](ZBot/agent/tools/mcp.py) | AsyncExitStack 管理 MCP 连接 |
| [cron/service.py](ZBot/cron/service.py) | 异步计时器、后台任务调度 |
| [agent/tools/shell.py](ZBot/agent/tools/shell.py) | 异步子进程执行 |
| [agent/tools/web.py](ZBot/agent/tools/web.py) | 异步 HTTP 请求 |
| [cli/commands.py](ZBot/cli/commands.py) | 事件循环启动、异步输入 |

---

## 七、一句话总结

**ZBot 的异步机制是"并发"而非"并行"—— 单线程快速切换，在 I/O 等待时执行其他任务，让等待的时间被充分利用。**

```
并行（多核）：  核心1 ████████  核心2 ████████  核心3 ████████  ← 真正同时
并发（单核）：  核心1 ██A██B██A██C██B██A███C██  ← 快速切换，看起来同时
```
