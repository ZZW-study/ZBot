# 会话列表功能 — 零基础前端教程

> 目标：在左侧栏添加一个会话列表，像 Codex 那样可以选择、新建、删除会话。
> 你将从零学会：React 组件、状态管理、API 调用、CSS 样式。

---

## 目录

1. [回顾：现有代码是怎么工作的](#1-回顾现有代码是怎么工作的)
2. [功能设计：我们要做什么](#2-功能设计我们要做什么)
3. [第一步：后端 — 添加会话列表 API](#3-第一步后端--添加会话列表-api)
4. [第二步：前端 — 创建 useSessions Hook](#4-第二步前端--创建-usesessions-hook)
5. [第三步：前端 — 创建 SessionList 组件](#5-第三步前端--创建-sessionlist-组件)
6. [第四步：前端 — 修改 Sidebar 集成会话列表](#6-第四步前端--修改-sidebar-集成会话列表)
7. [第五步：前端 — 修改 ChatPage 串联一切](#7-第五步前端--修改-chatpage-串联一切)
8. [第六步：前端 — 添加 CSS 样式](#8-第六步前端--添加-css-样式)
9. [第七步：测试](#9-第七步测试)
10. [总结：你学到了什么](#10-总结你学到了什么)

---

## 1. 回顾：现有代码是怎么工作的

在开始写新功能之前，我们先回顾一下现有代码。你需要理解这些，因为新功能会模仿它们的写法。

### 1.1 数据流：一个请求从前端到后端的完整路径

```
用户输入文字 → Composer 组件 → ChatPage.handleSend() → useWebSocket.sendMessage()
    → WebSocket → 后端 agent_websocket() → AgentRunService → CoreAgent
    → 后端返回事件 → WebSocket → useWebSocket.handleAgentEvent() → ChatPage 更新状态
    → MessageList 重新渲染
```

**后端类比：** 就像 FastAPI 里一个请求从路由到 service 到 repository 的完整链路。

### 1.2 每个文件的作用（快速回顾）

```
src/
├── main.jsx              # 入口，把 App 渲染到 #root（类似 FastAPI 的 main.py）
├── App.jsx               # 路由控制器，根据配置状态显示不同页面
├── App.css               # 所有样式
├── index.css             # 全局重置样式
│
├── pages/
│   ├── ChatPage.jsx      # 聊天页面（核心！管理消息、WebSocket、会话名）
│   └── OnboardPage.jsx   # 配置页面（首次使用时的设置表单）
│
├── components/
│   ├── Sidebar.jsx       # 左侧栏（品牌、会话输入框、状态、按钮）
│   ├── MessageList.jsx   # 消息列表（渲染聊天气泡）
│   ├── Composer.jsx      # 输入框 + 发送按钮
│   ├── ActivityPanel.jsx # 右侧事件面板
│   ├── EventRow.jsx      # 单个事件行
│   └── StatusRow.jsx     # 单个状态行
│
├── hooks/
│   ├── useConfig.js      # Hook：检测后端配置状态
│   └── useWebSocket.js   # Hook：管理 WebSocket 连接和事件
│
└── utils/
    └── format.js         # 工具函数（格式化时间、事件标题等）
```

### 1.3 关键文件详解（你需要重点理解的）

#### `ChatPage.jsx` — 聊天页面（核心）

```jsx
// ChatPage 管理的状态（类似 FastAPI 的全局变量）
const [messages, setMessages] = useState([]);           // 消息列表
const [streamingContent, setStreamingContent] = useState(''); // 流式内容
const [input, setInput] = useState('');                 // 输入框内容
const [sessionName, setSessionName] = useState('default');   // 会话名称
```

**关键点：** `sessionName` 是一个字符串状态，默认值 `'default'`。它被传给 `Sidebar` 组件显示，也被传给 `sendMessage` 发送给后端。

```jsx
// ChatPage 渲染的结构
<main className="shell">
  <Sidebar ... />              // 左侧栏
  <section className="chat">   // 中间聊天区
    <MessageList ... />
    <Composer ... />
  </section>
  <ActivityPanel ... />        // 右侧事件面板
</main>
```

**后端类比：** 就像 FastAPI 的模板里 `{% include "sidebar.html" %}` 一样，`Sidebar` 是被"嵌入"到 `ChatPage` 里的。

#### `Sidebar.jsx` — 左侧栏

```jsx
export default function Sidebar({
  sessionName,      // 从 ChatPage 传来的会话名
  setSessionName,   // 从 ChatPage 传来的修改会话名的函数
  socketState,      // WebSocket 连接状态
  isRunning,        // 是否正在运行
  activeRunId,      // 当前运行 ID
  onReconnect,      // 重新连接的回调函数
  onOpenSettings,   // 打开设置的回调函数
}) {
  return (
    <aside className="sidebar">
      {/* 品牌标识 */}
      <div className="brand">...</div>

      {/* 会话输入框 — 用户手动输入会话名 */}
      <label>会话</label>
      <input value={sessionName} onChange={(event) => setSessionName(event.target.value)} />

      {/* 状态面板 */}
      <section className="status-panel">
        <StatusRow label="连接" ... />
        <StatusRow label="运行" ... />
        <StatusRow label="Run ID" ... />
      </section>

      {/* 按钮 */}
      <button>重新连接</button>
      <button>设置</button>
    </aside>
  );
}
```

**关键点：** 现在的会话选择是一个**文本输入框**，用户需要手动输入会话名。我们要把它改成一个**可选择的列表**。

#### `useWebSocket.js` — WebSocket Hook

```jsx
// 发送消息时，sessionName 被一起发给后端
const sendMessage = useCallback((message, sessionName) => {
  socketRef.current.send(JSON.stringify({
    type: 'run.start',
    message,
    session_name: sessionName || 'default',  // ← 会话名在这里
  }));
}, []);
```

**关键点：** `sessionName` 通过 WebSocket 的 `run.start` 消息发给后端。后端根据这个名字找到对应的会话文件。

#### `useConfig.js` — 配置检测 Hook

```jsx
export function useConfig() {
  const [configured, setConfigured] = useState(null);  // null=加载中

  const apiBase = useMemo(() => {
    // 计算后端 API 地址
    if (import.meta.env.VITE_ZBOT_API_URL) return import.meta.env.VITE_ZBOT_API_URL;
    if (import.meta.env.DEV) {
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
    return '';
  }, []);

  useEffect(() => {
    // 启动时调用后端 API 检测配置
    fetch(`${apiBase}/api/config/status`)
      .then((r) => r.json())
      .then((data) => setConfigured(!!data.configured))
      .catch(() => setConfigured(false));
  }, [apiBase]);

  return { configured, setConfigured, apiBase };
}
```

**关键点：**
- `useState(null)` — 初始值是 `null`，表示"加载中"
- `useEffect` — 组件挂载时自动执行一次（类似 FastAPI 的 `@app.on_event("startup")`）
- `fetch` — 调用后端 API（类似 Python 的 `requests.get`）
- `apiBase` — 后端地址，所有 API 调用都要用它

**这就是我们接下来要模仿的模式！** 我们要写一个类似的 `useSessions` Hook。

---

## 2. 功能设计：我们要做什么

### 2.1 目标效果

```
┌──────────────────────────────────────────────────────────────┐
│  左侧栏（Sidebar）                                            │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Z ZBot                                                  │ │
│  │   Agent Harness                                         │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │ 会话列表                                    [+ 新建]     │ │
│  │ ┌──────────────────────────────────────────────────────┐ │ │
│  │ │ ▶ default                              [🗑]          │ │ │
│  │ │   my-project                            [🗑]          │ │ │
│  │ │   test-session                          [🗑]          │ │ │
│  └──┴──────────────────────────────────────────────────────┴─┘ │
│  [连接状态] [运行状态] [Run ID]                                │
│  [重新连接] [设置]                                             │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 需要做的事情

| 步骤 | 做什么 | 涉及文件 |
|------|--------|----------|
| 1 | 后端：添加"列出会话"API | `session/manager.py`, `backend/routers/agent.py` |
| 2 | 前端：创建 `useSessions` Hook | `src/hooks/useSessions.js`（新文件） |
| 3 | 前端：创建 `SessionList` 组件 | `src/components/SessionList.jsx`（新文件） |
| 4 | 前端：修改 `Sidebar` 集成会话列表 | `src/components/Sidebar.jsx` |
| 5 | 前端：修改 `ChatPage` 串联一切 | `src/pages/ChatPage.jsx` |
| 6 | 前端：添加 CSS 样式 | `src/App.css` |
| 7 | 测试 | 运行前后端 |

### 2.3 React 核心概念预告

在开始之前，你需要理解几个 React 概念：

| 概念 | 后端类比 | 我们什么时候用 |
|------|----------|---------------|
| `useState` | Pydantic 模型的字段 | 管理会话列表、当前选中的会话 |
| `useEffect` | `@app.on_event("startup")` | 组件加载时调用 API 获取会话列表 |
| `useCallback` | `functools.lru_cache` | 缓存函数，避免重复创建 |
| `props` | 函数参数 | 父组件传数据给子组件 |
| 条件渲染 | `if/else` 选择模板 | 有会话时显示列表，没有时显示空状态 |
| 列表渲染 | `for` 循环渲染模板 | 把会话数组渲染成列表项 |

---

## 3. 第一步：后端 — 添加会话列表 API

**为什么先做后端？** 因为前端需要从后端获取会话列表数据。没有 API，前端就没数据可显示。

### 3.1 给 SessionManager 添加 `list` 方法

打开 `ZBot/session/manager.py`，找到 `SessionManager` 类。

现在它只有 `get_or_create` 和 `save` 两个方法。我们需要添加一个 `list` 方法来列出所有会话。

**在 `save` 方法后面添加以下代码：**

```python
    async def list_sessions(self) -> list[dict[str, Any]]:
        """列出所有会话的元数据（不加载消息内容）。

        只读取每个 .jsonl 文件的第一行（元数据行），不加载消息，
        这样即使有几百个会话也能快速返回。

        Returns:
            会话元数据列表，按更新时间倒序排列（最新的在前面）
        """
        sessions: list[dict[str, Any]] = []

        def scan_files():
            """在线程池中扫描会话文件。"""
            for path in self.sessions_dir.glob("*.jsonl"):
                try:
                    with path.open("r", encoding="utf-8") as f:
                        first_line = f.readline().strip()
                        if first_line:
                            data = json.loads(first_line)
                            if data.get("_type") == "metadata":
                                # 计算消息数量（总行数 - 1 行元数据）
                                line_count = sum(1 for _ in f)
                                data["message_count"] = line_count
                                sessions.append(data)
                except Exception:
                    continue  # 跳过损坏的文件

        await asyncio.to_thread(scan_files)

        # 按更新时间倒序排列
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions
```

**代码解释：**

| 部分 | 作用 | 后端类比 |
|------|------|----------|
| `async def` | 异步函数 | FastAPI 的 `async def` 路由 |
| `def scan_files()` | 内部同步函数 | 在线程池里执行的阻塞操作 |
| `await asyncio.to_thread()` | 把同步操作放到线程池 | FastAPI 里用 `run_in_executor` |
| `self.sessions_dir.glob("*.jsonl")` | 查找所有 .jsonl 文件 | `pathlib` 的 glob 模式匹配 |
| `f.readline()` | 只读第一行 | 不加载全部消息，性能好 |
| `sessions.sort(...)` | 排序 | Python 的 list.sort |

**同样添加一个 `delete` 方法：**

```python
    async def delete(self, session_name: str) -> bool:
        """删除指定会话。

        Args:
            session_name: 会话名称

        Returns:
            True 表示删除成功，False 表示会话不存在
        """
        path = self._session_path(session_name)
        if not path.exists():
            return False

        def remove_file():
            path.unlink()  # 删除文件

        await asyncio.to_thread(remove_file)
        # 同时从缓存中移除
        self._cache.pop(session_name, None)
        return True
```

### 3.2 添加 API 路由

打开 `ZBot/backend/routers/agent.py`，在 `router = APIRouter(tags=["agent"])` 后面添加：

```python
from ZBot.session.manager import SessionManager


@router.get("/api/sessions")
async def list_sessions():
    """列出所有会话。"""
    # 从配置中获取 workspace 路径
    config = config_cache.get()
    if config is None:
        return {"sessions": []}

    workspace = config.get("workspace", "workspace")
    manager = SessionManager(workspace)
    sessions = await manager.list_sessions()
    return {"sessions": sessions}


@router.delete("/api/sessions/{session_name}")
async def delete_session(session_name: str):
    """删除指定会话。"""
    config = config_cache.get()
    if config is None:
        return {"ok": False, "error": "未配置"}

    workspace = config.get("workspace", "workspace")
    manager = SessionManager(workspace)
    deleted = await manager.delete(session_name)
    return {"ok": deleted}
```

**代码解释：**

| 部分 | 作用 |
|------|------|
| `@router.get("/api/sessions")` | GET 请求路由，类似 FastAPI 的 `@app.get` |
| `@router.delete("/api/sessions/{session_name}")` | DELETE 请求路由，`{session_name}` 是路径参数 |
| `config_cache.get()` | 获取配置（全局缓存） |
| `SessionManager(workspace)` | 创建会话管理器实例 |

### 3.3 重启后端测试

```bash
# 重启后端
cd E:/LLMsApplicationDevelopment/ZBot
python start.py

# 测试 API（在另一个终端）
curl http://localhost:8000/api/sessions
```

你应该看到类似这样的返回：

```json
{"sessions": [{"_type": "metadata", "name": "default", "created_at": "...", "updated_at": "...", "message_count": 5}]}
```

**后端完成！** 现在前端可以调用 `/api/sessions` 获取会话列表了。

---

## 4. 第二步：前端 — 创建 useSessions Hook

**什么是 Hook？** Hook 是 React 的一种机制，让你在函数组件里"钩入" React 的功能（状态、生命周期等）。自定义 Hook 就是把你自己的逻辑封装成可复用的函数。

**后端类比：** Hook 类似 FastAPI 的 `Depends` 依赖注入——你定义一个函数，它返回你需要的数据，组件里直接调用就能用。

### 4.1 分析 useConfig 的模式

让我们再看一遍 `useConfig.js`，因为我们要模仿它：

```jsx
// useConfig.js 的模式：
export function useConfig() {
  const [configured, setConfigured] = useState(null);  // 1. 定义状态
  const apiBase = useMemo(() => { ... }, []);           // 2. 计算值

  useEffect(() => {                                     // 3. 组件挂载时执行
    fetch(`${apiBase}/api/config/status`)               // 4. 调用 API
      .then((r) => r.json())                            // 5. 解析 JSON
      .then((data) => setConfigured(!!data.configured)) // 6. 更新状态
      .catch(() => setConfigured(false));               // 7. 错误处理
  }, [apiBase]);

  return { configured, setConfigured, apiBase };        // 8. 返回数据
}
```

**我们要模仿这个模式来写 `useSessions`！**

### 4.2 创建 useSessions.js

创建新文件 `src/hooks/useSessions.js`：

```jsx
/**
 * useSessions Hook — 管理会话列表
 *
 * 后端类比：类似 FastAPI 的 Depends(get_sessions)
 * 作用：获取会话列表，提供刷新、删除功能
 */
import { useCallback, useEffect, useState } from 'react';

/**
 * 自定义 Hook：管理会话列表
 *
 * @param {string} apiBase - 后端 API 地址（从 useConfig 获取）
 * @returns {object} - { sessions, loading, error, refresh, deleteSession }
 *
 * 使用方式：
 *   const { sessions, loading, error, refresh, deleteSession } = useSessions(apiBase);
 */
export function useSessions(apiBase) {
  // sessions: 会话列表数组，初始值 []（空数组）
  // 类似 Python 的 sessions: list[dict] = []
  const [sessions, setSessions] = useState([]);

  // loading: 是否正在加载，初始值 true
  // 类似 Python 的 loading: bool = True
  const [loading, setLoading] = useState(true);

  // error: 错误信息，初始值 null（没有错误）
  // 类似 Python 的 error: str | None = None
  const [error, setError] = useState(null);

  // refresh: 刷新会话列表的函数
  // useCallback 会缓存这个函数，不会每次渲染都创建新的
  // 依赖项 [apiBase] 表示只有 apiBase 变化时才重新创建
  const refresh = useCallback(async () => {
    try {
      setLoading(true);   // 开始加载
      setError(null);     // 清除之前的错误

      // fetch 调用后端 API（类似 Python 的 requests.get）
      const response = await fetch(`${apiBase}/api/sessions`);

      // 检查响应状态
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      // 解析 JSON（类似 Python 的 response.json()）
      const data = await response.json();

      // 更新状态（类似 Python 的 self.sessions = data["sessions"]）
      setSessions(data.sessions || []);
    } catch (err) {
      // 错误处理
      setError(err.message);
      setSessions([]);
    } finally {
      setLoading(false);  // 无论成功失败，都结束加载
    }
  }, [apiBase]);  // 依赖项：apiBase 变化时重新创建

  // deleteSession: 删除指定会话的函数
  const deleteSession = useCallback(async (sessionName) => {
    try {
      // 调用后端 DELETE API
      const response = await fetch(
        `${apiBase}/api/sessions/${encodeURIComponent(sessionName)}`,
        { method: 'DELETE' }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      // 删除成功后，刷新列表
      // 注意：这里用函数式更新 setSessions(prev => ...)
      // 因为我们需要基于"当前最新的"列表来过滤
      setSessions((prev) => prev.filter((s) => s.name !== sessionName));

      return true;  // 返回成功标志
    } catch (err) {
      setError(err.message);
      return false;  // 返回失败标志
    }
  }, [apiBase]);

  // useEffect：组件挂载时自动执行一次
  // 空依赖项 [] 表示只在挂载时执行一次
  // 类似 FastAPI 的 @app.on_event("startup")
  useEffect(() => {
    refresh();
  }, [refresh]);

  // 返回所有数据和函数
  return { sessions, loading, error, refresh, deleteSession };
}
```

### 4.3 逐行解释新概念

#### `useCallback` 是什么？

```jsx
// 没有 useCallback（每次渲染都创建新函数）
const refresh = async () => { ... };

// 有 useCallback（缓存函数，只在依赖项变化时重新创建）
const refresh = useCallback(async () => { ... }, [apiBase]);
```

**为什么要用它？** 因为 `refresh` 会被传给 `useEffect` 的依赖项。如果不用 `useCallback`，每次组件渲染都会创建一个新的 `refresh`，导致 `useEffect` 无限循环执行。

**后端类比：** 类似 `@lru_cache` 装饰器，缓存函数结果。

#### `setSessions((prev) => ...)` 是什么？

```jsx
// 错误写法：直接修改
setSessions(sessions.filter(...));  // ← 可能拿到旧的 sessions

// 正确写法：函数式更新
setSessions((prev) => prev.filter(...));  // ← prev 保证是最新的
```

**为什么要函数式更新？** 因为 React 的状态更新是异步的。如果你直接用 `sessions` 变量，它可能是旧值。用函数式更新 `(prev) => ...` 可以保证拿到最新的值。

**后端类比：** 类似数据库的乐观锁，确保基于最新状态操作。

#### `encodeURIComponent` 是什么？

```jsx
fetch(`${apiBase}/api/sessions/${encodeURIComponent(sessionName)}`)
```

如果 `sessionName` 是 `"my session"`（有空格），URL 会变成 `/api/sessions/my%20session`。这是 URL 编码，防止特殊字符破坏 URL。

**后端类比：** 类似 Python 的 `urllib.parse.quote()`。

---

## 5. 第三步：前端 — 创建 SessionList 组件

### 5.1 分析现有组件的模式

让我们再看一遍 `Sidebar.jsx`，因为我们的 `SessionList` 要嵌入到它里面：

```jsx
// Sidebar.jsx 的结构
export default function Sidebar({ sessionName, setSessionName, ... }) {
  return (
    <aside className="sidebar">
      <div className="brand">...</div>

      {/* 会话输入框 — 我们要把这个替换成 SessionList */}
      <label>会话</label>
      <input value={sessionName} onChange={...} />

      <section className="status-panel">...</section>
      <button>重新连接</button>
      <button>设置</button>
    </aside>
  );
}
```

**关键点：**
- 组件是一个函数，接收 `props`（类似函数参数）
- 返回 JSX（类似 HTML 的语法）
- `export default` 导出，其他文件 `import` 就能用

### 5.2 创建 SessionList.jsx

创建新文件 `src/components/SessionList.jsx`：

```jsx
/**
 * SessionList 组件 — 会话列表
 *
 * 后端类比：类似 FastAPI 模板里的 {% for session in sessions %} 循环
 * 作用：显示会话列表，支持选择、新建、删除
 *
 * Props（从父组件传来的参数）：
 *   sessions        - 会话列表数组
 *   currentSession  - 当前选中的会话名
 *   onSelect        - 选择会话的回调函数
 *   onDelete        - 删除会话的回调函数
 *   onNew           - 新建会话的回调函数
 *   loading         - 是否正在加载
 */
export default function SessionList({
  sessions,
  currentSession,
  onSelect,
  onDelete,
  onNew,
  loading,
}) {
  // ---- 渲染逻辑 ----

  // 加载中状态
  if (loading) {
    return (
      <div className="session-list">
        <p className="session-empty">加载中...</p>
      </div>
    );
  }

  return (
    <div className="session-list">
      {/* 头部：标题 + 新建按钮 */}
      <div className="session-header">
        <span className="session-title">会话</span>
        <button
          className="session-new-btn"
          onClick={onNew}
          title="新建会话"
        >
          +
        </button>
      </div>

      {/* 会话列表 */}
      <ul className="session-items">
        {sessions.length === 0 ? (
          // 空状态：没有会话
          <li className="session-empty">还没有会话</li>
        ) : (
          // 有会话：渲染列表
          sessions.map((session) => (
            <li
              key={session.name}
              className={`session-item ${session.name === currentSession ? 'active' : ''}`}
              onClick={() => onSelect(session.name)}
            >
              {/* 会话名称 */}
              <span className="session-name">{session.name}</span>

              {/* 删除按钮 */}
              <button
                className="session-delete-btn"
                onClick={(event) => {
                  event.stopPropagation();  // 阻止冒泡，防止触发选择
                  onDelete(session.name);
                }}
                title="删除会话"
              >
                ×
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
```

### 5.3 逐行解释

#### `props` 解构

```jsx
export default function SessionList({
  sessions,        // 会话列表
  currentSession,  // 当前选中的会话名
  onSelect,        // 选择会话的回调函数
  onDelete,        // 删除会话的回调函数
  onNew,           // 新建会话的回调函数
  loading,         // 是否正在加载
}) {
```

**后端类比：** 类似 FastAPI 路由函数的参数：

```python
@app.get("/sessions")
async def list_sessions(
    sessions: list,           # 会话列表
    current_session: str,     # 当前选中的会话名
    onSelect: Callable,       # 选择会话的回调
    ...
):
```

#### 条件渲染

```jsx
if (loading) {
  return <p>加载中...</p>;
}

// 等价于 Python：
// if loading:
//     return render_template("loading.html")
```

#### 列表渲染

```jsx
{sessions.map((session) => (
  <li key={session.name}>
    <span>{session.name}</span>
  </li>
))}
```

**`map` 是什么？** 类似 Python 的列表推导式：

```python
# Python 等价
[render_session(session) for session in sessions]
```

**`key` 是什么？** React 需要每个列表项有一个唯一的 `key`，用来高效更新 DOM。类似数据库的主键。

#### `event.stopPropagation()`

```jsx
onClick={(event) => {
  event.stopPropagation();  // 阻止事件冒泡
  onDelete(session.name);
}}
```

**为什么要阻止冒泡？** 因为删除按钮在 `<li>` 里面，点击删除按钮会同时触发 `<li>` 的 `onClick`（选择会话）。`stopPropagation()` 阻止事件向上传播。

**后端类比：** 类似中间件里 `return` 阻止请求继续往下传递。

---

## 6. 第四步：前端 — 修改 Sidebar 集成会话列表

### 6.1 回顾 Sidebar 的当前代码

`Sidebar.jsx` 现在是这样的：

```jsx
import StatusRow from './StatusRow';
import { socketStateLabel } from '../utils/format';

export default function Sidebar({
  sessionName, setSessionName, socketState, isRunning,
  activeRunId, onReconnect, onOpenSettings,
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">Z</div>
        <div>
          <h1>ZBot</h1>
          <p>Agent Harness</p>
        </div>
      </div>

      {/* 这个输入框要替换成 SessionList */}
      <label className="field-label" htmlFor="session-name">会话</label>
      <input
        id="session-name"
        className="session-input"
        value={sessionName}
        onChange={(event) => setSessionName(event.target.value)}
        disabled={isRunning}
      />

      <section className="status-panel">
        <StatusRow label="连接" value={socketStateLabel(socketState)} tone={socketState} />
        <StatusRow label="运行" value={isRunning ? '执行中' : '空闲'} tone={isRunning ? 'running' : 'idle'} />
        <StatusRow label="Run ID" value={activeRunId || '-'} />
      </section>

      <button className="connect-button" type="button" onClick={onReconnect}
        disabled={socketState === 'connected' || isRunning}>
        重新连接
      </button>

      <button className="settings-button" type="button" onClick={onOpenSettings}
        disabled={isRunning}>
        设置
      </button>
    </aside>
  );
}
```

### 6.2 修改后的 Sidebar

用以下代码**替换**整个 `Sidebar.jsx`：

```jsx
import StatusRow from './StatusRow';
import SessionList from './SessionList';
import { socketStateLabel } from '../utils/format';

export default function Sidebar({
  // 原有的 props
  sessionName, setSessionName, socketState, isRunning,
  activeRunId, onReconnect, onOpenSettings,
  // 新增的 props（会话列表相关）
  sessions, sessionsLoading, onSelectSession, onDeleteSession, onNewSession,
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">Z</div>
        <div>
          <h1>ZBot</h1>
          <p>Agent Harness</p>
        </div>
      </div>

      {/* 会话列表 — 替换了原来的输入框 */}
      <SessionList
        sessions={sessions}
        currentSession={sessionName}
        onSelect={onSelectSession}
        onDelete={onDeleteSession}
        onNew={onNewSession}
        loading={sessionsLoading}
      />

      <section className="status-panel">
        <StatusRow label="连接" value={socketStateLabel(socketState)} tone={socketState} />
        <StatusRow label="运行" value={isRunning ? '执行中' : '空闲'} tone={isRunning ? 'running' : 'idle'} />
        <StatusRow label="Run ID" value={activeRunId || '-'} />
      </section>

      <button className="connect-button" type="button" onClick={onReconnect}
        disabled={socketState === 'connected' || isRunning}>
        重新连接
      </button>

      <button className="settings-button" type="button" onClick={onOpenSettings}
        disabled={isRunning}>
        设置
      </button>
    </aside>
  );
}
```

**变化对比：**

```diff
  import StatusRow from './StatusRow';
+ import SessionList from './SessionList';
  import { socketStateLabel } from '../utils/format';

  export default function Sidebar({
    sessionName, setSessionName, socketState, isRunning,
    activeRunId, onReconnect, onOpenSettings,
+   sessions, sessionsLoading, onSelectSession, onDeleteSession, onNewSession,
  }) {
    return (
      <aside className="sidebar">
        <div className="brand">...</div>

-       <label className="field-label" htmlFor="session-name">会话</label>
-       <input
-         id="session-name"
-         className="session-input"
-         value={sessionName}
-         onChange={(event) => setSessionName(event.target.value)}
-         disabled={isRunning}
-       />
+       <SessionList
+         sessions={sessions}
+         currentSession={sessionName}
+         onSelect={onSelectSession}
+         onDelete={onDeleteSession}
+         onNew={onNewSession}
+         loading={sessionsLoading}
+       />

        <section className="status-panel">...</section>
        <button>重新连接</button>
        <button>设置</button>
      </aside>
    );
  }
```

**解释：**

| 变化 | 作用 |
|------|------|
| `import SessionList` | 导入新组件 |
| 新增 5 个 props | 会话列表相关数据和回调 |
| `<SessionList ... />` | 替换原来的输入框 |

---

## 7. 第五步：前端 — 修改 ChatPage 串联一切

### 7.1 回顾 ChatPage 的当前代码

`ChatPage.jsx` 现在是这样的（简化版）：

```jsx
import { useCallback, useMemo, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import Sidebar from '../components/Sidebar';
import MessageList from '../components/MessageList';
import Composer from '../components/Composer';
import ActivityPanel from '../components/ActivityPanel';

export default function ChatPage({ onOpenSettings }) {
  const [messages, setMessages] = useState([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [input, setInput] = useState('');
  const [sessionName, setSessionName] = useState('default');

  // WebSocket 相关逻辑...
  const { socketState, events, isRunning, activeRunId, sendMessage, stopRun, reconnect } = useWebSocket(wsUrl, { ... });

  // 发送消息
  const handleSend = useCallback(() => { ... }, [input, sessionName, sendMessage]);

  return (
    <main className="shell">
      <Sidebar
        sessionName={sessionName}
        setSessionName={setSessionName}
        socketState={socketState}
        isRunning={isRunning}
        activeRunId={activeRunId}
        onReconnect={reconnect}
        onOpenSettings={onOpenSettings}
      />
      <section className="chat">...</section>
      <ActivityPanel events={events} />
    </main>
  );
}
```

### 7.2 修改后的 ChatPage

用以下代码**替换**整个 `ChatPage.jsx`：

```jsx
import { useCallback, useMemo, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useConfig } from '../hooks/useConfig';
import { useSessions } from '../hooks/useSessions';
import Sidebar from '../components/Sidebar';
import MessageList from '../components/MessageList';
import Composer from '../components/Composer';
import ActivityPanel from '../components/ActivityPanel';

export default function ChatPage({ onOpenSettings }) {
  const [messages, setMessages] = useState([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [input, setInput] = useState('');
  const [sessionName, setSessionName] = useState('default');

  // 获取 apiBase（用于 API 调用）
  const { apiBase } = useConfig();

  // 会话列表管理
  const {
    sessions,
    loading: sessionsLoading,
    refresh: refreshSessions,
    deleteSession,
  } = useSessions(apiBase);

  // WebSocket URL 计算
  const wsUrl = useMemo(() => {
    if (import.meta.env.VITE_ZBOT_WS_URL) return import.meta.env.VITE_ZBOT_WS_URL;
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    if (import.meta.env.DEV) {
      return `${protocol}://${window.location.hostname}:8000/api/agent/ws`;
    }
    return `${protocol}://${window.location.host}/api/agent/ws`;
  }, []);

  // WebSocket 事件回调
  const handleCompleted = useCallback((event) => {
    const finalContent = event.payload?.final_content || event.message;
    setStreamingContent('');
    setMessages((prev) => [
      ...prev,
      { id: `${event.run_id}-${event.created_at}-assistant`, role: 'assistant', content: finalContent },
    ]);
  }, []);

  const handleFailed = useCallback((event) => {
    setStreamingContent('');
    setMessages((prev) => [
      ...prev,
      { id: `${event.run_id}-${event.created_at}-error`, role: 'assistant', content: event.message },
    ]);
  }, []);

  const handleStarted = useCallback(() => {
    setStreamingContent('');
  }, []);

  const handleDelta = useCallback((event) => {
    const delta = event.payload?.delta ?? event.message ?? '';
    if (!delta) return;
    setStreamingContent((prev) => `${prev}${delta}`);
  }, []);

  // WebSocket 连接
  const {
    socketState, events, isRunning, activeRunId,
    sendMessage, stopRun, reconnect,
  } = useWebSocket(wsUrl, {
    onCompleted: handleCompleted,
    onDelta: handleDelta,
    onFailed: handleFailed,
    onStarted: handleStarted,
  });

  // 发送消息
  const handleSend = useCallback(() => {
    const content = input.trim();
    if (!content) return;
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content }]);
    setInput('');
    sendMessage(content, sessionName.trim() || 'default');
  }, [input, sessionName, sendMessage]);

  // ---- 新增：会话操作回调 ----

  // 选择会话
  const handleSelectSession = useCallback((name) => {
    setSessionName(name);
    setMessages([]);           // 清空当前消息（切换会话）
    setStreamingContent('');   // 清空流式内容
  }, []);

  // 删除会话
  const handleDeleteSession = useCallback(async (name) => {
    const ok = await deleteSession(name);
    if (ok && name === sessionName) {
      // 如果删除的是当前会话，切换到 default
      setSessionName('default');
      setMessages([]);
    }
  }, [deleteSession, sessionName]);

  // 新建会话
  const handleNewSession = useCallback(() => {
    const name = prompt('请输入新会话名称：');
    if (!name || !name.trim()) return;

    const trimmed = name.trim();
    setSessionName(trimmed);
    setMessages([]);
    setStreamingContent('');
    // 刷新列表（后端会在第一次发消息时自动创建会话）
    setTimeout(() => refreshSessions(), 500);
  }, [refreshSessions]);

  const canSend = socketState === 'connected' && !isRunning && input.trim().length > 0;
  const latestEvent = events[0] || null;

  return (
    <main className="shell">
      <Sidebar
        sessionName={sessionName}
        setSessionName={setSessionName}
        socketState={socketState}
        isRunning={isRunning}
        activeRunId={activeRunId}
        onReconnect={reconnect}
        onOpenSettings={onOpenSettings}
        // 会话列表相关 props
        sessions={sessions}
        sessionsLoading={sessionsLoading}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onNewSession={handleNewSession}
      />

      <section className="chat">
        <header className="chat-header">
          <h2>对话</h2>
          <button className="stop-button" type="button" onClick={stopRun} disabled={!isRunning}>
            停止
          </button>
        </header>

        <MessageList
          messages={messages}
          isRunning={isRunning}
          latestEvent={latestEvent}
          streamingContent={streamingContent}
        />
        <Composer input={input} setInput={setInput} onSend={handleSend} disabled={!canSend} />
      </section>

      <ActivityPanel events={events} />
    </main>
  );
}
```

### 7.3 变化对比

```diff
  import { useCallback, useMemo, useState } from 'react';
  import { useWebSocket } from '../hooks/useWebSocket';
+ import { useConfig } from '../hooks/useConfig';
+ import { useSessions } from '../hooks/useSessions';
  import Sidebar from '../components/Sidebar';
  // ... 其他 import

  export default function ChatPage({ onOpenSettings }) {
    const [messages, setMessages] = useState([]);
    const [streamingContent, setStreamingContent] = useState('');
    const [input, setInput] = useState('');
    const [sessionName, setSessionName] = useState('default');

+   // 获取 apiBase
+   const { apiBase } = useConfig();
+
+   // 会话列表管理
+   const {
+     sessions,
+     loading: sessionsLoading,
+     refresh: refreshSessions,
+     deleteSession,
+   } = useSessions(apiBase);

    // ... WebSocket 相关代码不变 ...

+   // 选择会话
+   const handleSelectSession = useCallback((name) => {
+     setSessionName(name);
+     setMessages([]);
+     setStreamingContent('');
+   }, []);
+
+   // 删除会话
+   const handleDeleteSession = useCallback(async (name) => {
+     const ok = await deleteSession(name);
+     if (ok && name === sessionName) {
+       setSessionName('default');
+       setMessages([]);
+     }
+   }, [deleteSession, sessionName]);
+
+   // 新建会话
+   const handleNewSession = useCallback(() => {
+     const name = prompt('请输入新会话名称：');
+     if (!name || !name.trim()) return;
+     const trimmed = name.trim();
+     setSessionName(trimmed);
+     setMessages([]);
+     setStreamingContent('');
+     setTimeout(() => refreshSessions(), 500);
+   }, [refreshSessions]);

    return (
      <main className="shell">
        <Sidebar
          sessionName={sessionName}
          setSessionName={setSessionName}
          socketState={socketState}
          isRunning={isRunning}
          activeRunId={activeRunId}
          onReconnect={reconnect}
          onOpenSettings={onOpenSettings}
+         sessions={sessions}
+         sessionsLoading={sessionsLoading}
+         onSelectSession={handleSelectSession}
+         onDeleteSession={handleDeleteSession}
+         onNewSession={handleNewSession}
        />
        {/* ... 其余不变 ... */}
      </main>
    );
  }
```

### 7.4 逐行解释新代码

#### 导入 useConfig 和 useSessions

```jsx
import { useConfig } from '../hooks/useConfig';
import { useSessions } from '../hooks/useSessions';
```

**为什么需要 useConfig？** 因为我们需要 `apiBase`（后端地址）来调用 `/api/sessions` API。

**为什么在 ChatPage 里调用 useSessions？** 因为 `ChatPage` 是"页面级"组件，它负责管理所有数据和逻辑，然后通过 `props` 分发给子组件。

#### 选择会话

```jsx
const handleSelectSession = useCallback((name) => {
  setSessionName(name);        // 更新会话名
  setMessages([]);             // 清空消息列表
  setStreamingContent('');     // 清空流式内容
}, []);
```

**为什么要清空消息？** 因为切换会话后，当前显示的消息属于旧会话，需要清空。后端会在下次发消息时自动加载对应会话的历史。

#### 删除会话

```jsx
const handleDeleteSession = useCallback(async (name) => {
  const ok = await deleteSession(name);  // 调用 API 删除
  if (ok && name === sessionName) {      // 如果删除的是当前会话
    setSessionName('default');           // 切换到 default
    setMessages([]);                     // 清空消息
  }
}, [deleteSession, sessionName]);
```

**为什么用 `async/await`？** 因为删除是异步操作（调用后端 API）。`await` 等待 API 返回结果后再执行后续逻辑。

#### 新建会话

```jsx
const handleNewSession = useCallback(() => {
  const name = prompt('请输入新会话名称：');  // 弹出输入框
  if (!name || !name.trim()) return;         // 用户取消或输入为空

  const trimmed = name.trim();
  setSessionName(trimmed);                   // 设置为当前会话
  setMessages([]);                           // 清空消息
  setStreamingContent('');
  setTimeout(() => refreshSessions(), 500);  // 延迟刷新列表
}, [refreshSessions]);
```

**为什么用 `setTimeout`？** 因为新会话是后端在第一次发消息时才创建的。我们延迟 500ms 后刷新列表，给后端一点时间创建会话文件。

**`prompt` 是什么？** 浏览器的原生弹窗输入框，类似 Python 的 `input()`。简单但不好看，后面可以改成自定义弹窗。

#### 传递 props 给 Sidebar

```jsx
<Sidebar
  // 原有的 props
  sessionName={sessionName}
  setSessionName={setSessionName}
  ...
  // 新增的 props
  sessions={sessions}
  sessionsLoading={sessionsLoading}
  onSelectSession={handleSelectSession}
  onDeleteSession={handleDeleteSession}
  onNewSession={handleNewSession}
/>
```

**数据流：**
```
ChatPage (管理数据) → Sidebar (接收 props) → SessionList (接收 props)
     ↓                      ↓                       ↓
  useSessions           传递给子组件             渲染列表
```

---

## 8. 第六步：前端 — 添加 CSS 样式

### 8.1 回顾 CSS 基础

CSS 的基本语法：

```css
.类名 {
  属性: 值;
  属性: 值;
}
```

**选择器：**
- `.类名` — 选中 `class="类名"` 的元素
- `.父类 .子类` — 选中 `.父类` 里面的 `.子类`
- `.类名:hover` — 鼠标悬停时的状态
- `.类名:active` — 鼠标点击时的状态

### 8.2 添加样式

打开 `src/App.css`，在文件**末尾**添加以下内容：

```css
/* ══════════════════════════════════════════════════
   会话列表 — 左侧栏的会话选择功能
   ══════════════════════════════════════════════════ */

/* 会话列表容器 */
.session-list {
  display: flex;
  flex-direction: column;          /* 垂直排列 */
  gap: 4px;                        /* 子元素间距 */
}

/* 头部：标题 + 新建按钮 */
.session-header {
  display: flex;
  align-items: center;             /* 垂直居中 */
  justify-content: space-between;  /* 两端对齐 */
  padding: 0 2px;
}

/* 标题 */
.session-title {
  color: #4c596e;                  /* 深灰文字 */
  font-size: 13px;
  font-weight: 700;                /* 粗体 */
}

/* 新建按钮 */
.session-new-btn {
  width: 24px;
  height: 24px;
  border: 1px solid #cfd7e6;       /* 边框 */
  border-radius: 6px;              /* 圆角 */
  background: #ffffff;
  color: #4c596e;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;                 /* 手型光标 */
  display: grid;
  place-items: center;             /* 水平+垂直居中 */
  padding: 0;
  line-height: 1;
  transition: background 0.15s, border-color 0.15s;
  /* 过渡动画：背景色和边框色变化时有动画效果 */
}

.session-new-btn:hover {
  background: #edf3ff;             /* 悬停时浅蓝背景 */
  border-color: #2f6fed;           /* 悬停时蓝色边框 */
  color: #2f6fed;                  /* 悬停时蓝色文字 */
}

/* 会话列表（ul 元素） */
.session-items {
  list-style: none;                /* 去掉默认的圆点 */
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 240px;               /* 最大高度 */
  overflow-y: auto;                /* 超出时垂直滚动 */
}

/* 单个会话项（li 元素） */
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 6px;              /* 圆角 */
  cursor: pointer;                 /* 手型光标 */
  font-size: 14px;
  color: #172033;
  transition: background 0.15s;
}

/* 鼠标悬停 */
.session-item:hover {
  background: #f1f4f9;             /* 浅灰背景 */
}

/* 当前选中的会话 */
.session-item.active {
  background: #edf3ff;             /* 浅蓝背景 */
  color: #2f6fed;                  /* 蓝色文字 */
  font-weight: 600;                /* 稍粗 */
}

/* 会话名称 */
.session-name {
  overflow: hidden;                /* 超出隐藏 */
  text-overflow: ellipsis;         /* 超出显示省略号 ... */
  white-space: nowrap;             /* 不换行 */
  min-width: 0;                    /* 允许缩小 */
}

/* 删除按钮 */
.session-delete-btn {
  flex-shrink: 0;                  /* 不缩放 */
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;         /* 透明背景 */
  color: #69758a;                  /* 灰色 */
  font-size: 16px;
  cursor: pointer;
  display: grid;
  place-items: center;
  padding: 0;
  line-height: 1;
  opacity: 0;                      /* 默认隐藏 */
  transition: opacity 0.15s, background 0.15s;
}

/* 鼠标悬停在会话项上时显示删除按钮 */
.session-item:hover .session-delete-btn {
  opacity: 1;                      /* 显示 */
}

/* 删除按钮悬停效果 */
.session-delete-btn:hover {
  background: #fff2f1;             /* 浅红背景 */
  color: #b42318;                  /* 红色文字 */
}

/* 空状态和加载状态 */
.session-empty {
  color: #69758a;                  /* 灰色文字 */
  font-size: 13px;
  text-align: center;
  padding: 12px 0;
  margin: 0;
}

/* 响应式：小屏幕时限制列表高度 */
@media (max-width: 760px) {
  .session-items {
    max-height: 180px;
  }
}
```

### 8.3 CSS 逐段解释

#### `transition` 是什么？

```css
transition: background 0.15s, border-color 0.15s;
```

**作用：** 当 `background` 或 `border-color` 变化时，不是瞬间切换，而是用 0.15 秒的动画过渡。

**效果：** 鼠标悬停时，背景色会平滑地从白色变成浅灰色，而不是突然变化。

#### `opacity: 0` 和 `opacity: 1`

```css
.session-delete-btn {
  opacity: 0;                      /* 默认隐藏 */
}

.session-item:hover .session-delete-btn {
  opacity: 1;                      /* 鼠标悬停时显示 */
}
```

**作用：** 删除按钮默认隐藏，只有鼠标悬停在会话项上时才显示。

**`.session-item:hover .session-delete-btn`** — 这是一个"后代选择器"，意思是"当鼠标悬停在 `.session-item` 上时，它里面的 `.session-delete-btn` 应用这个样式"。

#### `text-overflow: ellipsis`

```css
.session-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

**作用：** 如果会话名太长，显示省略号 `...`。

**效果：** `"my-very-long-session-name"` → `"my-very-long-sess..."`

---

## 9. 第七步：测试

### 9.1 启动后端

```bash
cd E:/LLMsApplicationDevelopment/ZBot
python start.py
```

### 9.2 启动前端

```bash
cd E:/LLMsApplicationDevelopment/ZBot/ZBot/frontend
npm run dev
```

### 9.3 浏览器测试

打开 `http://localhost:5173`，你应该看到：

1. 左侧栏有一个会话列表，显示 `default` 会话（如果有）
2. 点击 `+` 按钮可以新建会话
3. 点击会话名可以切换会话
4. 鼠标悬停在会话项上会显示删除按钮
5. 点击删除按钮可以删除会话

### 9.4 常见问题

#### Q: 会话列表为空？

**原因：** 还没有任何会话文件。

**解决：** 先在聊天页面发一条消息，后端会自动创建 `default` 会话。然后刷新页面。

#### Q: API 调用失败（CORS 错误）？

**原因：** 前端和后端不在同一个端口。

**解决：** 检查 `vite.config.js` 的代理配置，确保 `/api` 请求被转发到后端。

#### Q: 删除会话后列表没有更新？

**原因：** `deleteSession` 函数里已经用 `setSessions` 更新了列表，但如果 API 调用失败，列表不会更新。

**解决：** 打开浏览器 F12 → Console，看看有没有错误信息。

---

## 10. 总结：你学到了什么

### 10.1 React 核心概念

| 概念 | 作用 | 你在哪里用的 |
|------|------|-------------|
| `useState` | 管理组件状态 | 会话列表、加载状态、错误信息 |
| `useEffect` | 组件挂载时执行 | 调用 API 获取会话列表 |
| `useCallback` | 缓存函数 | 所有回调函数（选择、删除、新建） |
| `props` | 父传子数据 | ChatPage → Sidebar → SessionList |
| 条件渲染 | 根据状态显示不同内容 | 加载中、空状态、有数据 |
| 列表渲染 | 循环渲染列表项 | `sessions.map(...)` |
| `export default` | 导出组件 | 每个组件文件 |

### 10.2 项目架构模式

```
Hook (useSessions)     → 管理数据和 API 调用
    ↓
Page (ChatPage)        → 组合 Hook，管理业务逻辑
    ↓
Component (Sidebar)    → 接收 props，渲染 UI
    ↓
Component (SessionList) → 接收 props，渲染列表
```

**后端类比：**
```
Service (SessionManager) → 管理数据和数据库操作
    ↓
Router (agent.py)        → 调用 Service，处理请求
    ↓
Template (Jinja2)        → 接收数据，渲染 HTML
```

### 10.3 代码模式总结

#### 模式1：获取数据

```jsx
// 1. 定义状态
const [data, setData] = useState([]);
const [loading, setLoading] = useState(true);

// 2. 定义获取函数
const fetchData = useCallback(async () => {
  setLoading(true);
  const response = await fetch(`${apiBase}/api/xxx`);
  const result = await response.json();
  setData(result.data);
  setLoading(false);
}, [apiBase]);

// 3. 组件挂载时执行
useEffect(() => { fetchData(); }, [fetchData]);
```

#### 模式2：父子组件通信

```jsx
// 父组件
function Parent() {
  const [value, setValue] = useState('');
  return <Child value={value} onChange={setValue} />;
}

// 子组件
function Child({ value, onChange }) {
  return <input value={value} onChange={(e) => onChange(e.target.value)} />;
}
```

#### 模式3：列表渲染

```jsx
{items.map((item) => (
  <div key={item.id}>{item.name}</div>
))}
```

### 10.4 下一步可以做什么

1. **美化新建会话弹窗** — 把 `prompt()` 改成自定义弹窗组件
2. **会话重命名** — 双击会话名可以编辑
3. **会话搜索** — 在列表上方添加搜索框
4. **会话排序** — 按最后活跃时间排序
5. **加载历史消息** — 切换会话时从后端加载该会话的消息

---

## 附录：文件修改清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `ZBot/session/manager.py` | 修改 | 添加 `list_sessions` 和 `delete` 方法 |
| `ZBot/backend/routers/agent.py` | 修改 | 添加 GET `/api/sessions` 和 DELETE `/api/sessions/{name}` 路由 |
| `src/hooks/useSessions.js` | 新建 | 会话列表 Hook |
| `src/components/SessionList.jsx` | 新建 | 会话列表组件 |
| `src/components/Sidebar.jsx` | 修改 | 集成 SessionList，替换输入框 |
| `src/pages/ChatPage.jsx` | 修改 | 添加 useSessions 和会话操作回调 |
| `src/App.css` | 修改 | 添加会话列表样式 |
