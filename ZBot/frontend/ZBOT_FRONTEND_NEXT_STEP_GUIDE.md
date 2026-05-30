# ZBot 前端下一阶段改写指导

> 本文档基于对 ZBot 前端代码、ZBot 后端 API/数据模型、nanobot 前端项目的完整审查后编写。
> 生成日期：2026-05-28
> 前提假设：`SESSION_LIST_TUTORIAL.md` 中描述的功能已规划完成（但实际代码尚未集成）。

---

## 1. 执行摘要

**ZBot 前端当前处于"可运行原型"阶段。** 整个前端仅 16 个源文件、约 1,750 行代码，使用 React 19 + Vite + 纯 CSS，无 TypeScript、无路由、无 UI 组件库、无测试。后端已有完整的会话管理、多模态文件上传、定时任务、技能系统、记忆系统等能力，但前端仅消费了配置检查和 WebSocket 聊天两个能力。

**SESSION_LIST_TUTORIAL.md 描述的会话列表功能尚未集成到实际代码中。** 当前 [Sidebar.jsx](src/components/Sidebar.jsx) 仍然只有一个手动输入会话名称的文本框，没有会话列表、没有会话切换、没有会话删除。

**下一步最应该做的不是改 UI 样式，而是分三步走：**

1. **先补基础设施**（Phase 1）：引入 CSS 变量设计令牌、建立统一 API client 层、引入路由。
2. **再补核心业务能力**（Phase 2）：把 SESSION_LIST_TUTORIAL 的代码实际集成进来，加上会话历史加载、消息持久化、空状态/错误状态处理。
3. **然后逐步升级视觉和交互**（Phase 3-5）：借鉴 nanobot 的视觉语言，抽象基础组件，接入后端未使用的能力。

---

## 2. 当前前端状态

### 2.1 技术栈

| 维度      | 当前状态                                                                  |
| --------- | ------------------------------------------------------------------------- |
| 框架      | React 19.2.6                                                              |
| 构建工具  | Vite 8.0.12                                                               |
| 语言      | 纯 JavaScript（.jsx），无 TypeScript                                      |
| UI 组件库 | 无。全部手写 HTML 元素                                                    |
| CSS 方案  | 纯 CSS 文件（App.css 649 行 + index.css 46 行），无 CSS 变量、无 Tailwind |
| 路由      | 无。条件渲染实现页面切换                                                  |
| 状态管理  | React 内置 hooks（useState/useEffect/useCallback/useMemo/useRef）         |
| API 请求  | 原生 fetch + 原生 WebSocket，无抽象层                                     |
| 测试      | 无。零测试文件、零测试框架                                                |
| Lint      | ESLint 10.3.0（仅 react-hooks + react-refresh 插件）                      |

### 2.2 目录结构

```
frontend/src/
├── App.css              (649 行 — 全部样式集中于此)
├── App.jsx              (82 行 — 根组件/路由控制器)
├── index.css            (46 行 — 全局重置)
├── main.jsx             (32 行 — 入口)
├── components/
│   ├── ActivityPanel.jsx  (40 行 — 右侧事件面板)
│   ├── Composer.jsx       (47 行 — 消息输入区)
│   ├── EventRow.jsx       (31 行 — 单条事件)
│   ├── MessageList.jsx    (45 行 — 消息列表)
│   ├── Sidebar.jsx        (83 行 — 左侧栏)
│   └── StatusRow.jsx      (26 行 — 状态行)
├── hooks/
│   ├── useConfig.js       (60 行 — 配置检测)
│   └── useWebSocket.js    (196 行 — WebSocket 生命周期)
├── pages/
│   ├── ChatPage.jsx       (266 行 — 聊天主页面)
│   └── OnboardPage.jsx    (282 行 — 配置/设置页面)
└── utils/
    └── format.js          (113 行 — 格式化工具)
```

### 2.3 当前页面能力

| 能力           | 状态               | 说明                                                    |
| -------------- | ------------------ | ------------------------------------------------------- |
| 会话列表       | **未实现**   | SESSION_LIST_TUTORIAL.md 已规划但代码未集成             |
| 会话详情       | **未实现**   | 无历史消息加载、无会话元数据展示                        |
| 聊天界面       | **基础可用** | 支持发送消息、流式接收、停止运行                        |
| Bot/Agent 配置 | **基础可用** | OnboardPage 支持 LLM provider/model/apiKey/apiBase 配置 |
| 设置页         | **基础可用** | 复用 OnboardPage，仅暴露 4 个配置字段                   |
| 登录/认证      | **不存在**   | 无任何认证机制                                          |
| 文件上传       | **不存在**   | Composer 仅文本输入                                     |
| 定时任务管理   | **不存在**   | 后端有 cron 能力但前端无 UI                             |
| 技能/工具管理  | **不存在**   | 后端有完整技能系统但前端无 UI                           |
| 记忆系统查看   | **不存在**   | 后端有三层记忆但前端无 UI                               |
| 响应式布局     | **基础可用** | 1180px 隐藏 ActivityPanel，760px 单列                   |

---

## 3. SESSION_LIST_TUTORIAL 完成后的判断

### 3.1 该教程解决了什么

SESSION_LIST_TUTORIAL.md 是一份面向后端开发者的前端入门教程（1,494 行），它计划完成以下内容：

- 创建 `useSessions.js` hook — 封装 `GET /api/sessions` 和 `DELETE /api/sessions/{name}` 调用
- 创建 `SessionList.jsx` 组件 — 显示会话列表、支持选择和删除
- 修改 `Sidebar.jsx` — 集成 SessionList 组件替代纯文本输入框
- 修改 `ChatPage.jsx` — 实现会话切换时加载不同会话的上下文

**如果这些内容真的完成，ZBot 前端将从"单会话聊天工具"升级为"多会话管理工具"。**

### 3.2 该教程完成后仍未解决的问题

| 问题类别                  | 具体问题                                                          |
| ------------------------- | ----------------------------------------------------------------- |
| **消息持久化**      | 刷新页面后所有聊天记录丢失。后端有完整历史但前端从不加载          |
| **空状态/错误状态** | 无 EmptyState 组件、无 ErrorBoundary、无加载骨架屏                |
| **API 抽象层**      | fetch 调用仍然散落在各 hook/组件中，无统一错误处理                |
| **类型安全**        | 全 JavaScript，无 TypeScript，无 PropTypes                        |
| **样式系统**        | 仍然在一个 649 行的 App.css 中硬编码所有样式，无 CSS 变量、无主题 |
| **组件复用**        | 无基础 UI 组件库（Button/Input/Card/Dialog 等全部手写）           |
| **文件上传**        | 后端有 `POST /api/multimodal/ask` 但前端无任何文件上传 UI       |
| **工具执行可视化**  | tool.started/tool.completed 仅显示为纯文本事件行，无结构化展示    |
| **配置能力**        | 后端有 30+ 配置字段，前端仅暴露 4 个                              |
| **测试**            | 零测试覆盖                                                        |

### 3.3 阶段判断

> **SESSION_LIST_TUTORIAL 完成后，ZBot 前端处于"功能原型补全"阶段。**
> 核心缺失不是 UI 好不好看，而是基础架构缺失导致无法支撑后续迭代。
> 下一步优先级：API 层抽象 > 路由引入 > 消息历史加载 > 样式系统化 > 视觉升级。

---

## 4. nanobot 可借鉴点

### 4.1 视觉语言

| 借鉴点             | nanobot 做法                                                                                                         | 对 ZBot 的价值                                                     |
| ------------------ | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| **色彩系统** | HSL CSS 变量定义语义色（background/foreground/muted/accent/destructive/border），dark mode 通过 `.dark` class 切换 | ZBot 当前硬编码颜色值，无法统一换肤。引入 CSS 变量是最低成本的改进 |
| **圆角体系** | 基础 `--radius: 7px`，组件级 `rounded-xl`/`rounded-2xl`/`rounded-[28px]`，pill 形状 `rounded-full`         | ZBot 当前圆角不一致（有些 4px、有些 8px），统一体系立刻提升质感    |
| **阴影层级** | 多层阴影叠加（如 `shadow-[0_20px_55px_rgba(15,23,42,0.08)]`），暗色模式用更深阴影                                  | ZBot 当前无阴影，卡片/面板缺乏层次感                               |
| **字体栈**   | 系统字体 + CJK 专用字体（Noto Sans SC、PingFang SC 等），CJK 行高 1.8                                                | ZBot 仅用 Inter + 系统字体，中文显示效果一般                       |
| **间距体系** | Tailwind 的 4px 基础网格（p-1=4px, p-2=8px, p-4=16px...）                                                            | ZBot 当前间距随意，无统一规范                                      |

### 4.2 组件模式

| 借鉴点                    | nanobot 做法                                                                            | 对 ZBot 的价值                                          |
| ------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| **用户消息气泡**    | 右对齐圆角药丸（`rounded-[18px]`），`bg-secondary/70`，最大宽度 `min(85%, 36rem)` | ZBot 当前气泡样式可用但较粗糙，可借鉴圆角和最大宽度控制 |
| **助手消息**        | 不用气泡，直接以文档散文形式渲染 markdown（prose 类）                                   | ZBot 当前助手消息也用气泡，改为散文形式更适合长文本场景 |
| **Composer 双形态** | `hero`（居中大号，空状态用）和 `thread`（底部固定，聊天中用）两种形态               | ZBot Composer 只有一种形态，空状态体验差                |
| **空状态快速操作**  | 6 个操作卡片网格（plan/analyze/brainstorm/code/summarize/more）                         | ZBot 空状态无任何引导，用户不知道能做什么               |
| **连接状态指示器**  | 小圆点 + 颜色（emerald=连接中, amber=重连中, red=错误）+ 脉冲动画                       | ZBot 用文本显示状态，不如指示器直观                     |
| **侧边栏折叠**      | 可折叠导航栏（272px 展开 / 56px 图标栏收起）                                            | ZBot 侧边栏不可折叠，小屏幕下浪费空间                   |

### 4.3 工程模式

| 借鉴点                      | nanobot 做法                                                      | 对 ZBot 的价值                                                      |
| --------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------- |
| **`cn()` 工具函数** | `clsx` + `tailwind-merge` 封装，统一 className 合并           | 条件样式拼接更安全，避免 className 冲突                             |
| **shadcn/ui 模式**    | 基于 Radix 原语 + Tailwind + CVA，组件可控可扩展                  | ZBot 不必用 shadcn，但可以借鉴"原语 + 样式变体"的模式               |
| **Hooks 职责单一**    | 每个 hook 只管一件事：useTheme、useSessions、useSidebarState 等   | ZBot 的 useWebSocket 塞了太多逻辑（连接管理 + 事件路由 + 状态维护） |
| **事件总线模式**      | CustomEvent 用于跨组件通信（CLI app changes、MCP preset changes） | 比 prop drilling 更松耦合                                           |
| **乐观更新**          | 新会话立即出现在列表中，不等服务器确认                            | 提升感知速度                                                        |
| **内存缓存**          | 切换会话时用 Map 缓存消息，返回时无需重新请求                     | 避免重复请求，提升切换体验                                          |

### 4.4 交互体验

| 借鉴点                   | nanobot 做法                                                                    | 对 ZBot 的价值                                      |
| ------------------------ | ------------------------------------------------------------------------------- | --------------------------------------------------- |
| **流式文本动画**   | `requestAnimationFrame` 批量更新 + 延迟提交（80-220ms）避免 markdown 解析抖动 | ZBot 的流式更新较简单，可能在大量文本时出现渲染卡顿 |
| **消息入场动画**   | `animate-in fade-in-0 slide-in-from-bottom-1 duration-300`                    | 消息出现更自然                                      |
| **滚动到底部按钮** | 用户上翻时出现"回到底部"按钮                                                    | ZBot 无此功能，长对话中用户回翻后无法快速定位       |
| **Cmd+K 搜索**     | 全局快捷键打开会话搜索对话框                                                    | 快速定位会话                                        |
| **上下文菜单**     | 会话项右键/下拉菜单（pin/rename/archive/delete）                                | 比直接删除更丰富的操作                              |

---

## 5. nanobot 不建议照搬的点

| 不建议照搬的点                       | 原因                                                                                                                                        |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **TypeScript 迁移**            | ZBot 是教学项目，JS 对后端开发者更友好。建议用 JSDoc 注释 + PropTypes 渐进式补充类型信息，而非一步到位迁移到 TS                             |
| **shadcn/ui 组件库**           | 引入 shadcn/ui 需要同时引入 Radix UI、class-variance-authority、tailwind-merge 等一系列依赖，对当前 16 文件的项目来说过重。建议自建轻量组件 |
| **WebSocket 多路复用**         | nanobot 用一个 WebSocket 连接承载多个会话的流。ZBot 后端是每会话一个 WebSocket，架构不同，不应强求对齐                                      |
| **i18n 国际化**                | nanobot 支持 9 种语言。ZBot 目前面向中文用户，i18n 是远期需求，当前引入会增加不必要的复杂度                                                 |
| **无路由架构**                 | nanobot 用条件渲染代替路由。ZBot 需要支持会话列表 → 会话详情 → 设置等多页面导航，应该引入轻量路由（如 react-router）                      |
| **StrictMode 禁用**            | nanobot 因流式累加器纯净性禁用了 StrictMode。ZBot 当前的流式逻辑较简单，不需要禁用 StrictMode                                               |
| **Web Worker 图片编码**        | nanobot 用 Web Worker 做图片压缩。ZBot 当前无图片上传需求，不需要                                                                           |
| **Image Mode（图片生成模式）** | nanobot 有 AI 图片生成模式。ZBot 后端无此能力，不需要                                                                                       |

---

## 6. ZBot 后端能力分析

### 6.1 后端已有 API 端点

| 端点                     | 方法   | 前端是否已使用     | 能力说明                                                                                           |
| ------------------------ | ------ | ------------------ | -------------------------------------------------------------------------------------------------- |
| `/api/config/status`   | GET    | ✅ 已使用          | 检查配置是否就绪                                                                                   |
| `/api/config`          | GET    | ✅ 已使用          | 获取当前配置                                                                                       |
| `/api/config/defaults` | GET    | ✅ 已使用          | 获取 provider 默认值                                                                               |
| `/api/config`          | PUT    | ✅ 已使用          | 保存配置                                                                                           |
| `/api/agent/ws`        | WS     | ✅ 已使用          | Agent 通信（run.start/run.cancel + 事件流）                                                        |
| `/api/sessions`        | GET    | ❌**未使用** | 列出所有会话（含 name, created_at, updated_at, message_count, last_consolidated, memory_snapshot） |
| `/api/sessions/{name}` | DELETE | ❌**未使用** | 删除会话                                                                                           |
| `/api/multimodal/ask`  | POST   | ❌**未使用** | 文件上传 + 问答（支持图片、文本文件）                                                              |

### 6.2 后端已有但前端未消费的能力

| 能力                           | 后端实现程度                                                     | 前端现状                   | 前端化难度                               |
| ------------------------------ | ---------------------------------------------------------------- | -------------------------- | ---------------------------------------- |
| **会话列表/切换/删除**   | 完整（SessionManager CRUD + JSONL 持久化）                       | TUTORIAL 已规划但未集成    | 低（TUTORIAL 代码可直接用）              |
| **会话历史消息加载**     | 完整（Session.messages 从 JSONL 加载）                           | 前端消息纯内存，刷新即丢失 | 低（需新增 API 端点或复用 session 数据） |
| **多模态文件上传**       | 完整（POST /api/multimodal/ask，支持图片+文本）                  | 无文件上传 UI              | 中（需新增 Composer 文件附件功能）       |
| **Agent 工具执行可视化** | 事件流含 tool.started/completed/failed + tool_name + arguments   | ActivityPanel 仅显示纯文本 | 中（需结构化渲染工具事件）               |
| **子 Agent 进度**        | 事件流含 agent_label 区分主/子 agent                             | 未区分                     | 中                                       |
| **上下文压缩事件**       | 事件流含 compaction.started/completed                            | 仅显示为普通事件           | 低                                       |
| **定时任务**             | 完整（CronService + cron tool + cron.reminder 事件）             | 仅作为事件显示             | 高（需新增 API 端点 + 管理 UI）          |
| **技能系统**             | 完整（发现/生命周期/使用统计/进化）                              | 无                         | 高（需新增 API 端点 + 管理 UI）          |
| **记忆系统**             | 完整（三层记忆 + 向量检索 + 衰减）                               | 无                         | 高（需新增 API 端点 + 查看 UI）          |
| **高级配置**             | 完整（30+ 字段：temperature/max_tokens/reasoning_effort/MCP 等） | 仅暴露 4 字段              | 中（需分层设计设置页）                   |
| **错误结构化处理**       | 事件流含 payload.code（如 agent_setup_failed）                   | 显示为纯文本               | 低（解析 code 显示引导文案）             |

### 6.3 WebSocket 事件类型清单

后端通过 WebSocket 流式推送以下事件类型（定义在 `agent_run_service.py` 的 `AgentEvent` 中）。当前前端在 `utils/format.js` 的 `eventTitle` 中映射了中文标题，在 `eventMessage` 中生成显示文案，但所有事件在 `ActivityPanel` 中以相同样式渲染，无视觉区分。

| 事件类型                 | payload 关键字段                | 前端当前渲染                | Phase 3/4 建议渲染                                |
| ------------------------ | ------------------------------- | --------------------------- | ------------------------------------------------- |
| `run.started`          | `run_id`                      | 文本行                      | 绿色标记 "任务开始"                               |
| `run.completed`        | —                              | 文本行                      | 绿色标记 "任务完成" + 耗时                        |
| `run.failed`           | `code`                        | 文本行                      | 红色错误条 + 按 code 显示引导                     |
| `run.cancelled`        | —                              | 文本行                      | 黄色标记 "已取消"                                 |
| `run.closed`           | —                              | 文本行（兜底）              | 灰色标记 "资源已清理"                             |
| `turn.started`         | —                              | 文本行                      | 不渲染（内部状态）                                |
| `turn.completed`       | —                              | 文本行                      | 不渲染（内部状态）                                |
| `agent.progress`       | —                              | 文本行                      | 蓝色进度条                                        |
| `tool.started`         | `tool_name`, `tool_call_id` | 文本行                      | **可折叠块开始**：工具图标 + 名称 + spinner |
| `tool.completed`       | `tool_name`, `tool_call_id` | 文本行                      | **可折叠块结束**：绿色勾 + 名称 + 耗时      |
| `tool.failed`          | `tool_name`, `tool_call_id` | 文本行                      | **可折叠块结束**：红色叉 + 名称 + 错误信息  |
| `tool.progress`        | —                              | 文本行                      | 工具块内进度更新                                  |
| `model.started`        | —                              | 文本行                      | 不渲染或极简 "思考中..."                          |
| `model.completed`      | —                              | 文本行                      | 不渲染                                            |
| `assistant.delta`      | `delta`                       | 流式追加到 streamingContent | 不在 ActivityPanel 渲染（在 MessageList 中）      |
| `assistant.completed`  | —                              | 文本行                      | 不渲染（消息已在 MessageList 中）                 |
| `compaction.started`   | —                              | 文本行                      | 黄色标记 "压缩上下文..."                          |
| `compaction.completed` | —                              | 文本行                      | 黄色标记 "压缩完成"                               |
| `subagent.started`     | `agent_label`                 | 文本行                      | 子 agent 卡片开始：标签 + spinner                 |
| `subagent.completed`   | `agent_label`                 | 文本行                      | 子 agent 卡片结束：绿色勾                         |
| `subagent.failed`      | `agent_label`                 | 文本行                      | 子 agent 卡片结束：红色叉                         |

**Phase 3/4 关键改造点：** `tool.started` → `tool.completed`/`tool.failed` 应该渲染为一个**可折叠的工具调用块**（参考 nanobot 的 `AgentActivityCluster`），而非三条独立文本行。

### 6.4 前端需要但后端可能缺少的 API

| 需求                       | 说明                                                                                  | 建议后端补充                                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 获取单个会话的消息历史     | 前端切换会话时需要加载历史消息。当前 `GET /api/sessions` 只返回元数据，不返回消息体 | `GET /api/sessions/{name}/messages` 返回该会话的消息列表                                   |
| 获取会话的 memory snapshot | 展示会话记忆快照                                                                      | 可能已包含在 session 元数据中，需确认 `memory_snapshot` 字段内容                           |
| 技能列表/统计              | 前端展示技能系统                                                                      | `GET /api/skills`、`GET /api/skills/{name}/stats`                                        |
| 记忆内容查看               | 前端展示记忆系统                                                                      | `GET /api/memory/session/{name}`、`GET /api/memory/daily`、`GET /api/memory/long-term` |
| 定时任务管理               | 前端 CRUD 定时任务                                                                    | `GET/POST/DELETE /api/cron/jobs`                                                           |

---

## 7. 对比分析表

| 维度                       | nanobot 做法                                                                  | ZBot 当前做法                                                           | 是否建议借鉴                                                    | 具体原因                                                                                                 |
| -------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **页面布局**         | 两栏布局：可折叠侧边栏（272px/56px）+ 主内容区。设置页有独立侧边栏导航        | 三栏布局：固定侧边栏（280px）+ 聊天区 + 活动面板（340px）。无设置页布局 | ✅ 建议借鉴侧边栏可折叠，但保留三栏布局                         | ZBot 的 ActivityPanel 是独特优势（nanobot 的 agent activity 内嵌在消息流中），保留但优化。侧边栏应可折叠 |
| **会话列表**         | 分组（pinned/today/yesterday/earlier）、排序、密度、搜索（Cmd+K）、上下文菜单 | 无会话列表（仅有文本输入框）                                            | ✅ 直接借鉴分组和搜索模式                                       | 这是 ZBot 最大的功能缺口。分组、搜索、上下文菜单都值得借鉴                                               |
| **聊天主界面**       | 用户消息=右对齐药丸、助手消息=散文 markdown、工具活动=可折叠集群              | 用户/助手消息都是气泡、工具活动在右侧面板                               | ✅ 部分借鉴。助手消息改为散文形式，工具活动保留面板但增强结构化 | 助手的长回复用散文形式阅读体验更好。ZBot 的独立面板适合 agent 重场景                                     |
| **侧边栏**           | 品牌区 + 操作按钮 + 会话列表 + 设置 + 连接状态指示器                          | 品牌区 + 会话输入 + 状态面板 + 按钮                                     | ✅ 大量借鉴                                                     | 需要从"手动输入会话名"升级为"会话列表 + 搜索 + 操作"模式                                                 |
| **组件系统**         | shadcn/ui（Radix 原语 + Tailwind + CVA），9 个基础组件                        | 零组件库，全手写                                                        | ⚠️ 借鉴模式但不引入 shadcn/ui                                 | 建议自建轻量组件集（Button/Input/Card/Dialog），用 CSS 变量 + BEM 命名                                   |
| **API 请求层**       | 统一 api.ts（Bearer token auth）、bootstrap.ts（认证启动）                    | 散落在各文件的 inline fetch                                             | ✅ 必须借鉴                                                     | 需要统一 API client 层，集中错误处理、baseURL 管理                                                       |
| **状态管理**         | 纯 React hooks + Context，无外部库                                            | 纯 React hooks，无 Context                                              | ✅ 借鉴 Context 模式                                            | 至少需要一个 API context 提供 apiBase 和全局配置状态                                                     |
| **加载/错误/空状态** | 骨架屏、ConnectionBadge、EmptyState（快速操作卡片）、StreamErrorNotice        | 仅"正在检测配置..."文本                                                 | ✅ 必须借鉴                                                     | 每个列表/面板都需要空状态。错误需要可操作引导而非纯文本                                                  |
| **类型定义**         | TypeScript strict mode，types.ts 集中定义                                     | 无类型定义                                                              | ⚠️ 用 JSDoc + PropTypes 代替                                  | 不建议迁移到 TS，但建议用 JSDoc 补充关键类型信息                                                         |
| **样式系统**         | Tailwind + CSS 变量（HSL 语义色）+ globals.css 设计令牌                       | 纯 CSS，硬编码颜色值，单文件 649 行                                     | ✅ 必须借鉴 CSS 变量方式                                        | 不一定用 Tailwind，但必须引入 CSS 变量设计令牌系统                                                       |
| **响应式布局**       | 移动端 Sheet 抽屉式侧边栏、桌面端固定侧边栏                                   | 断点隐藏/折叠，无移动端适配                                             | ✅ 借鉴移动端 Sheet 模式                                        | 需要为移动端设计侧边栏抽屉                                                                               |
| **测试覆盖**         | 20+ 测试文件，Vitest + happy-dom + testing-library                            | 零测试                                                                  | ✅ 必须补测试                                                   | 至少覆盖 hooks 和工具函数                                                                                |
| **与后端集成**       | WebSocket 多路复用 + REST API + 乐观更新 + 内存缓存                           | 原生 WebSocket + inline fetch，无缓存                                   | ✅ 借鉴乐观更新和缓存模式                                       | 需要消息缓存、会话切换时无需重新加载                                                                     |

---

## 8. 下一阶段改写路线

### Phase 1：前端架构基线整理

**目标：** 建立可支撑后续迭代的基础设施，不改业务逻辑。

**应该做的事情：**

1. **引入 CSS 变量设计令牌系统**

   - 在 `index.css` 或新建 `tokens.css` 中定义 HSL 语义色变量（`--background`、`--foreground`、`--muted`、`--accent`、`--border` 等）
   - 定义圆角、间距、阴影、字体栈变量
   - 将 App.css 中的硬编码颜色值逐步替换为变量引用
   - 这是成本最低但收益最高的改动，为后续暗色模式和视觉统一打基础
2. **建立统一 API client 层**

   - 新建 `src/lib/api.js` — 封装 fetch 调用，统一处理 baseURL、错误、JSON 解析
   - 新建 `src/lib/ws-client.js` — 封装 WebSocket 连接管理（从 useWebSocket 中抽出连接逻辑）
   - 目标：任何组件调用 `api.getSessions()` 而非手动写 `fetch(apiBase + '/api/sessions')`
3. **引入轻量路由**

   - 安装 `react-router-dom`
   - 定义路由：`/`（ChatPage）、`/settings`（OnboardPage）
   - 替换 App.jsx 中的条件渲染逻辑
   - 为后续会话详情页 `/sessions/:name` 做准备
4. **拆分 App.css**

   - 将 649 行的 App.css 拆分为：`layout.css`（shell/grid）、`sidebar.css`、`chat.css`、`composer.css`、`activity.css`、`onboard.css`
   - 拆分时同步将硬编码颜色值替换为 tokens.css 中的 CSS 变量引用（如 `#3b82f6` → `var(--color-accent)`）
   - 不引入 Tailwind，用 CSS 变量 + BEM 命名即可
5. **新建基础目录结构**

```
src/
├── lib/           # 新建：API client、WebSocket client、类型定义
│   ├── api.js     # 统一 REST API client
│   ├── ws-client.js  # WebSocket 连接管理
│   └── types.js   # JSDoc 类型定义
├── components/    # 现有：逐步添加基础 UI 组件
│   ├── ui/        # 新建：Button、Input、Card、Dialog 等基础组件
│   └── ...        # 现有业务组件
├── hooks/         # 现有：逐步拆分和新增
├── pages/         # 现有
├── styles/        # 新建：拆分后的样式文件 + 设计令牌
│   └── tokens.css # 设计令牌（色彩、圆角、间距、阴影、字体）
└── utils/         # 现有：format.js（保持不动）
```

**哪些旧代码先不动：**

- `MessageList.jsx` — 聊天消息渲染逻辑暂不动
- `EventRow.jsx` — 事件渲染逻辑暂不动
- `StatusRow.jsx` — 状态行暂不动
- `format.js` — 工具函数暂不动

**为什么这是第一步：**

没有 API 抽象层，后续每个新功能都要重复写 fetch 调用。没有 CSS 变量，后续每次改样式都要全局搜索替换硬编码颜色。没有路由，后续加页面只能堆条件渲染。这些基础设施越晚补，后续改动成本越高。

---

### Phase 2：会话列表和聊天页体验升级

**目标：** 将 SESSION_LIST_TUTORIAL 的规划实际落地，并补齐会话管理的核心体验。

**会话列表下一步应该加什么：**

1. **集成 SESSION_LIST_TUTORIAL 代码**

   - 创建 `useSessions.js` hook — 调用 `GET /api/sessions`，管理会话列表状态
   - 创建 `SessionList.jsx` 组件 — 渲染会话列表、支持选择、删除
   - 修改 `Sidebar.jsx` — 用 SessionList 替代手动输入框
   - 关键验证：选择不同会话后，WebSocket 连接到正确的 session_name
2. **会话历史消息加载**

   - 这需要后端新增 `GET /api/sessions/{name}/messages` 端点（返回该会话的消息列表）
   - 前端新建 `useSessionHistory.js` hook — 切换会话时加载历史消息
   - 在 ChatPage 中，切换会话时先加载历史再显示
   - 缓存已加载的消息（参考 nanobot 的 Map 缓存模式）
3. **会话分组和排序**

   - 按时间分组：今天、昨天、更早
   - 按更新时间倒序排列
   - 显示 message_count 和最后更新时间
4. **会话搜索**

   - 本地过滤（根据会话名关键字）
   - 后续可扩展为 Cmd+K 全局搜索

**会话详情页应该怎么组织：**

当前不需要独立的"会话详情页"。会话详情就是聊天界面本身，但需要：

- 切换会话时自动加载该会话的历史消息
- 显示会话元数据（创建时间、消息数、最后更新时间）
- 会话名称可编辑（双击重命名）

**空状态、错误状态、loading 状态怎么做：**

| 状态         | 场景           | 建议做法                                               |
| ------------ | -------------- | ------------------------------------------------------ |
| EmptyState   | 会话列表为空   | 居中图标 + "还没有会话，发送第一条消息开始" + 引导按钮 |
| EmptyState   | 聊天区无消息   | 居中图标 + 快速操作卡片（参考 nanobot 的 6 宫格）      |
| LoadingState | 会话列表加载中 | 骨架屏（3 个灰色矩形占位）                             |
| LoadingState | 历史消息加载中 | 聊天区显示 spinner + "加载历史消息..."                 |
| ErrorState   | API 请求失败   | 红色提示条 + 重试按钮                                  |
| ErrorState   | WebSocket 断开 | 连接状态指示器变红 + 自动重连 + 手动重连按钮（已有）   |

**和后端 session/message 接口怎么对齐：**

| 前端需求         | 后端接口                                  | 状态          |
| ---------------- | ----------------------------------------- | ------------- |
| 列出会话         | `GET /api/sessions`                     | ✅ 已有       |
| 删除会话         | `DELETE /api/sessions/{name}`           | ✅ 已有       |
| 加载会话历史消息 | `GET /api/sessions/{name}/messages`     | ❌ 需后端新增 |
| 重命名会话       | `PATCH /api/sessions/{name}`            | ❌ 需后端新增 |
| 发送消息         | `WS: run.start {message, session_name}` | ✅ 已有       |
| 接收流式回复     | `WS: assistant.delta`                   | ✅ 已有       |

**哪些组件应该抽象：**

| 新组件              | 用途                                      | 从哪里提取                                     |
| ------------------- | ----------------------------------------- | ---------------------------------------------- |
| `SessionList`     | 会话列表容器                              | 新建                                           |
| `SessionListItem` | 单个会话条目（名称+时间+消息数+操作）     | 新建                                           |
| `EmptyState`      | 通用空状态组件（图标+标题+描述+操作按钮） | 新建                                           |
| `Spinner`         | 通用加载指示器（圆环旋转动画）            | 新建，参考 OnboardPage 的"正在检测配置..."文案 |

---

### Phase 3：借鉴 nanobot 的视觉系统

**目标：** 在 Phase 1 的 CSS 变量基础上，建立 ZBot 自己的设计系统。

**哪些视觉风格可以借鉴：**

| 视觉元素     | 借鉴方式                                                                                                                                                      |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 色彩体系     | 采用 HSL CSS 变量，语义化命名（background/foreground/muted/accent/destructive/border）。ZBot 品牌色保留蓝色调（当前 `#3b82f6` 附近），而非 nanobot 的中性色 |
| 圆角体系     | 基础圆角 `--radius: 6px`，组件级 `--radius-sm: 4px`、`--radius-lg: 12px`、`--radius-full: 9999px`                                                     |
| 阴影层级     | 3 级阴影：`--shadow-sm`（卡片）、`--shadow-md`（弹出层）、`--shadow-lg`（模态框）                                                                       |
| 字体栈       | 采用 nanobot 的 CJK 字体栈方案，确保中文显示效果                                                                                                              |
| 消息入场动画 | `fade-in + slide-in-from-bottom`，300ms                                                                                                                     |

**哪些不适合照搬：**

| 不照搬的点                | 原因                                                                                                                                      |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 中性色（neutral）为主色调 | ZBot 是 Agent 工具，蓝色调更符合"智能助手"的品牌定位                                                                                      |
| 消息不用气泡              | ZBot 的助手消息包含工具输出、代码、分析等多种内容，长度变化大。建议对纯文本短回复保留气泡，对含 markdown/代码块的长回复切换为散文渲染形式 |
| 极简侧边栏                | ZBot 需要保留状态面板（连接状态、运行状态），这是 Agent 工具的重要信息                                                                    |
| 大量圆角药丸形状          | ZBot 更偏工具感，适度圆角即可，不必过度圆润                                                                                               |

**ZBot 应该保留什么自己的风格：**

- **三栏布局** — 左侧会话列表 + 中间聊天 + 右侧活动面板。这是 ZBot 的独特优势，nanobot 没有独立的活动面板
- **状态面板** — 连接状态、运行状态、Run ID 对 Agent 工具很重要
- **工具事件可视化** — 右侧 ActivityPanel 是 ZBot 的特色，应增强而非移除
- **中文优先** — 所有 UI 文案保持中文，不引入 i18n

**如何抽象基础组件：**

建议自建轻量组件集（不引入 shadcn/ui），每个组件一个文件：

```
src/components/ui/
├── Button.jsx       # 变体：primary/secondary/ghost/danger，尺寸：sm/md/lg
├── Input.jsx        # 支持 label、error、disabled
├── Card.jsx         # 圆角容器，可选阴影和边框
├── Dialog.jsx       # 基于 <dialog> 或手写 modal
├── Badge.jsx        # 状态标签（连接状态、运行状态）
├── Spinner.jsx      # 加载指示器
├── EmptyState.jsx   # 空状态（图标+标题+描述+操作）
└── IconButton.jsx   # 图标按钮（关闭、折叠、更多）
```

**Tailwind 或 CSS 变量应该怎么组织：**

**建议方案：CSS 变量 + BEM 命名（不引入 Tailwind）**

理由：

- ZBot 当前 16 个文件，引入 Tailwind 的配置成本（tailwind.config.js、PostCSS、purge 配置）高于收益
- CSS 变量已经能提供主题切换和设计令牌能力
- BEM 命名（`.sidebar__item--active`）比 Tailwind 的长 className 串更易读

**如果后续项目增长到 50+ 文件，再考虑引入 Tailwind。**

```css
/* tokens.css — 设计令牌 */
:root {
  /* 色彩 */
  --color-background: #ffffff;
  --color-foreground: #1a1a2e;
  --color-muted: #f1f5f9;
  --color-muted-foreground: #64748b;
  --color-accent: #3b82f6;
  --color-accent-foreground: #ffffff;
  --color-destructive: #ef4444;
  --color-border: #e2e8f0;
  --color-card: #ffffff;
  --color-card-foreground: #1a1a2e;

  /* 圆角 */
  --radius-sm: 4px;
  --radius: 6px;
  --radius-lg: 12px;
  --radius-full: 9999px;

  /* 间距 */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  /* 阴影 */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);

  /* 字体 */
  --font-sans: 'Inter', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
}

/* 暗色模式（未来） */
.dark {
  --color-background: #0f0f1a;
  --color-foreground: #e2e8f0;
  /* ... */
}
```

---

### Phase 4：后端能力前端化

**目标：** 把后端已有但前端未使用的能力逐步体现在产品中，按优先级排序。

**优先级排序：**

| 优先级 | 能力                   | 前端化工作量                         | 用户价值                        |
| ------ | ---------------------- | ------------------------------------ | ------------------------------- |
| P0     | 会话历史消息加载       | 低（需后端新增端点 + 前端 hook）     | 极高（刷新不丢记录）            |
| P1     | 工具执行结构化可视化   | 中（改造 ActivityPanel + EventRow）  | 高（用户能看懂 agent 在做什么） |
| P1     | 错误结构化处理         | 低（解析 payload.code 显示引导）     | 高（用户知道怎么修错）          |
| P2     | 文件上传（多模态）     | 中（Composer 加文件选择 + 调用 API） | 中（扩展使用场景）              |
| P2     | 高级配置（分层设置页） | 中（OnboardPage 拆分为多 section）   | 中（高级用户需要调参）          |
| P3     | 定时任务管理           | 高（需后端新增 API + 前端管理页）    | 中（特定场景需要）              |
| P3     | 子 Agent 进度区分      | 低（解析 agent_label 字段）          | 中（复杂任务可观测性）          |
| P4     | 技能系统管理           | 高（需后端新增 API + 前端管理页）    | 低（目前主要由 agent 自管理）   |
| P4     | 记忆系统查看           | 高（需后端新增 API + 前端查看页）    | 低（调试/学习用途）             |

**API types 应该怎么管理：**

在 JavaScript 项目中，用 JSDoc 注释补充类型信息：

```javascript
// src/lib/types.js — 集中定义数据结构的 JSDoc 类型

/**
 * @typedef {Object} Session
 * @property {string} name
 * @property {string} created_at - ISO 8601
 * @property {string} updated_at - ISO 8601
 * @property {number} message_count
 * @property {number} last_consolidated
 * @property {string|null} memory_snapshot
 */

/**
 * @typedef {Object} AgentEvent
 * @property {string} type
 * @property {string} run_id
 * @property {string} session_name
 * @property {string} message
 * @property {string|null} agent_label
 * @property {Object} payload
 * @property {string} created_at
 */
```

**错误处理和请求状态怎么统一：**

在 API client 层统一处理：

```javascript
// src/lib/api.js
class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(path, options = {}) {
  const url = `${apiBase}${path}`;
  // FormData 不能设 Content-Type（浏览器会自动加 boundary）
  const isFormData = options.body instanceof FormData;
  const headers = isFormData
    ? { ...options.headers }
    : { 'Content-Type': 'application/json', ...options.headers };
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail || res.statusText, res.status, body.code);
  }
  return res.json();
}
```

---

### Phase 5：测试、质量和可维护性

**目标：** 防止前端越改越乱。

**应该加哪些测试：**

| 测试类型     | 覆盖范围                                                                            | 工具                                        |
| ------------ | ----------------------------------------------------------------------------------- | ------------------------------------------- |
| 工具函数单测 | `format.js` 中的 4 个函数、`api.js` 中的请求函数                                | Vitest                                      |
| Hook 单测    | `useConfig`、`useWebSocket`、`useSessions`（需 mock fetch/WebSocket）         | Vitest + @testing-library/react             |
| 组件单测     | `SessionList`、`SessionListItem`、`MessageList`、`Composer`、`EmptyState` | Vitest + @testing-library/react + happy-dom |
| 集成测试     | 完整聊天流程（连接 → 发消息 → 收回复 → 切换会话）                                | Vitest + @testing-library/react             |
| E2E 测试     | 暂不需要（项目规模太小）                                                            | —                                          |

**是否需要 Storybook：**

**当前不需要。** 项目仅 16 个文件，视觉组件不超过 10 个，Storybook 的配置和维护成本高于收益。当组件数量增长到 30+ 时再考虑。

**是否需要 lint/typecheck/build gate：**

| 门禁       | 建议                                                  |
| ---------- | ----------------------------------------------------- |
| ESLint     | ✅ 已有，建议增加 `no-unused-vars`、`eqeqeq` 规则 |
| TypeScript | ❌ 不引入。但建议在 ESLint 中启用 JSDoc 检查          |
| Build      | ✅`vite build` 应该加入 CI，确保构建不报错          |
| 测试       | ✅ 引入 Vitest 后，`vitest run` 应该加入 CI         |

**如何防止 UI 重构破坏业务逻辑：**

1. **先写测试再重构** — 对现有 hooks（useWebSocket、useConfig）先补测试，再改代码
2. **逐步替换** — 不要一次性重写所有组件。每次只改一个组件，确保其他组件不受影响
3. **保留 WebSocket 协议兼容** — 改前端组件时，确保发送的 `run.start`/`run.cancel` 消息格式不变
4. **视觉回归对比** — 重构前后截图对比，确保关键页面没有意外变化

---

## 9. 文件级改写建议

| 优先级       | 文件/目录                               | 当前问题                                     | 建议动作                                                 | 是否新建 | 是否修改 | 依赖后端                |
| ------------ | --------------------------------------- | -------------------------------------------- | -------------------------------------------------------- | -------- | -------- | ----------------------- |
| **P0** | `src/lib/api.js`                      | 不存在。fetch 调用散落各处                   | 新建统一 API client                                      | ✅ 新建  | —       | 否                      |
| **P0** | `src/lib/ws-client.js`                | WebSocket 管理逻辑塞在 useWebSocket 196 行中 | 抽出连接管理为独立模块                                   | ✅ 新建  | —       | 否                      |
| **P0** | `src/styles/tokens.css`               | 不存在。颜色/间距硬编码                      | 新建设计令牌文件                                         | ✅ 新建  | —       | 否                      |
| **P0** | `src/hooks/useSessions.js`            | 不存在（TUTORIAL 规划但未实现）              | 新建，调用 GET /api/sessions                             | ✅ 新建  | —       | 否（API 已有）          |
| **P0** | `src/components/SessionList.jsx`      | 不存在（TUTORIAL 规划但未实现）              | 新建会话列表组件                                         | ✅ 新建  | —       | 否                      |
| **P0** | `src/components/SessionListItem.jsx`  | 不存在                                       | 新建单个会话条目组件                                     | ✅ 新建  | —       | 否                      |
| **P1** | `src/components/Sidebar.jsx`          | 只有手动输入框，无会话列表                   | 大幅修改：集成 SessionList、折叠支持、连接状态指示器     | —       | ✅ 修改  | 否                      |
| **P1** | `src/pages/ChatPage.jsx`              | 266 行，状态管理+业务逻辑混杂                | 重构：抽离状态管理到 hooks，加入会话切换和历史加载       | —       | ✅ 修改  | 是（需历史消息 API）    |
| **P1** | `src/components/MessageList.jsx`      | 仅支持 user/assistant 两种角色，无空状态     | 修改：增加 EmptyState、支持 assistant 散文模式           | —       | ✅ 修改  | 否                      |
| **P1** | `src/components/Composer.jsx`         | 仅文本输入，无文件上传                       | 修改：增加文件附件按钮（Phase 4 再做）                   | —       | ✅ 修改  | 是（需 multimodal API） |
| **P1** | `src/components/ActivityPanel.jsx`    | 纯文本事件列表，无结构化                     | 修改：工具事件结构化渲染、图标区分、折叠/展开            | —       | ✅ 修改  | 否                      |
| **P1** | `src/components/EventRow.jsx`         | 无图标、无颜色区分、无折叠                   | 修改：按事件类型显示不同图标和颜色                       | —       | ✅ 修改  | 否                      |
| **P1** | `src/App.jsx`                         | 条件渲染代替路由                             | 修改：引入 react-router-dom                              | —       | ✅ 修改  | 否                      |
| **P1** | `src/hooks/useWebSocket.js`           | 196 行，连接管理+事件路由+状态维护混杂       | 重构：抽出连接管理，简化事件路由                         | —       | ✅ 修改  | 否                      |
| **P2** | `src/hooks/useSessionHistory.js`      | 不存在                                       | 新建：切换会话时加载历史消息                             | ✅ 新建  | —       | 是（需新 API）          |
| **P2** | `src/components/ui/Button.jsx`        | 不存在。按钮样式散落在 App.css               | 新建基础按钮组件                                         | ✅ 新建  | —       | 否                      |
| **P2** | `src/components/ui/Input.jsx`         | 不存在                                       | 新建基础输入组件                                         | ✅ 新建  | —       | 否                      |
| **P2** | `src/components/ui/Card.jsx`          | 不存在                                       | 新建基础卡片组件                                         | ✅ 新建  | —       | 否                      |
| **P2** | `src/components/ui/EmptyState.jsx`    | 不存在                                       | 新建通用空状态组件                                       | ✅ 新建  | —       | 否                      |
| **P2** | `src/components/ui/Badge.jsx`         | 不存在                                       | 新建状态标签组件                                         | ✅ 新建  | —       | 否                      |
| **P2** | `src/components/ui/Spinner.jsx`       | 不存在                                       | 新建加载指示器组件                                       | ✅ 新建  | —       | 否                      |
| **P2** | `src/pages/OnboardPage.jsx`           | 282 行，仅 4 个配置字段                      | 重构：分层设置（基础+高级+工具+MCP）                     | —       | ✅ 修改  | 否                      |
| **P1** | `src/App.css`                         | 649 行全在一个文件，颜色硬编码               | 拆分为多个样式文件 + 替换为 CSS 变量引用（Phase 1 执行） | —       | ✅ 修改  | 否                      |
| **P2** | `src/utils/format.js`                 | 无变化。Phase 1 先不动，Phase 2 后再迁移     | 迁移到 src/lib/format.js，更新所有 import 路径           | —       | ✅ 修改  | 否                      |
| **P3** | `src/pages/SettingsPage.jsx`          | 不存在（当前复用 OnboardPage）               | 新建独立设置页面，支持多 section 导航                    | ✅ 新建  | —       | 否                      |
| **P3** | `src/components/ToolEventDetail.jsx`  | 不存在                                       | 新建工具事件详情组件（展示 tool_name、参数、结果）       | ✅ 新建  | —       | 否                      |
| **P3** | `src/components/SubAgentProgress.jsx` | 不存在                                       | 新建子 Agent 进度组件                                    | ✅ 新建  | —       | 否                      |
| **P3** | `src/hooks/useErrorParser.js`         | 不存在                                       | 新建：解析 payload.code 返回用户友好文案                 | ✅ 新建  | —       | 否                      |
| **P4** | `src/pages/CronPage.jsx`              | 不存在                                       | 新建定时任务管理页面                                     | ✅ 新建  | —       | 是（需新 API）          |
| **P4** | `src/pages/SkillsPage.jsx`            | 不存在                                       | 新建技能管理页面                                         | ✅ 新建  | —       | 是（需新 API）          |
| **P4** | `src/pages/MemoryPage.jsx`            | 不存在                                       | 新建记忆系统查看页面                                     | ✅ 新建  | —       | 是（需新 API）          |

---

## 10. 组件规划

| 组件名                    | 用途                                       | 参考 nanobot 的哪些设计                                      | ZBot 中服务哪个业务场景                      | 优先级                     |
| ------------------------- | ------------------------------------------ | ------------------------------------------------------------ | -------------------------------------------- | -------------------------- |
| **AppShell**        | 应用骨架：侧边栏 + 主内容区的布局容器      | nanobot 的 Shell 组件（条件渲染 chat/settings）              | 整体页面布局                                 | P1                         |
| **Sidebar**         | 左侧导航栏：品牌、会话列表、操作按钮、状态 | nanobot 的可折叠侧边栏（272px/56px rail）+ ChatList          | 会话管理和导航                               | P0（改造现有）             |
| **SessionList**     | 会话列表容器：分组、排序、搜索             | nanobot 的 ChatList.tsx（pinned/today/yesterday 分组）       | 会话切换                                     | P0                         |
| **SessionListItem** | 单个会话条目：名称+时间+消息数+操作菜单    | nanobot ChatList 中的每个条目（上下文菜单、选中状态）        | 会话操作                                     | P0                         |
| **ChatWorkspace**   | 聊天工作区：header + 消息列表 + composer   | nanobot 的 ThreadShell（编排历史、流式、快速操作、空状态）   | 聊天主界面                                   | P1（改造现有 ChatPage）    |
| **MessageList**     | 消息列表容器：滚动、自动到底               | nanobot 的 ThreadMessages（display unit clustering）         | 消息展示                                     | P1（改造现有）             |
| **MessageBubble**   | 单条消息：用户=药丸气泡、助手=散文/气泡    | nanobot 的 MessageBubble（用户=右对齐药丸、助手=prose）      | 消息渲染                                     | P1（改造现有 MessageList） |
| **Composer**        | 消息输入区：文本输入、发送、停止           | nanobot 的 ThreadComposer（hero/thread 双形态、auto-resize） | 消息发送                                     | P1（改造现有）             |
| **EmptyState**      | 通用空状态：图标+标题+描述+操作按钮        | nanobot 的空状态快速操作卡片（6 宫格）                       | 各列表/面板空状态                            | P1                         |
| **Spinner**         | 加载指示器：圆环旋转动画                   | nanobot 的 boot splash pulse                                 | 各加载场景（内嵌于 LoadingState 或独立使用） | P1                         |
| **ErrorState**      | 通用错误状态：错误信息+重试按钮+引导       | nanobot 的 StreamErrorNotice                                 | 各错误场景                                   | P1                         |
| **ActivityPanel**   | 右侧活动面板：工具事件时间线               | nanobot 的 AgentActivityCluster（可折叠、diff 展示）         | Agent 活动监控                               | P1（改造现有）             |
| **ToolEventDetail** | 工具事件详情：tool_name、参数、结果、耗时  | nanobot 的 TraceGroup（可折叠、参数展示）                    | 工具执行可视化                               | P2                         |
| **SettingsPanel**   | 设置面板：分层配置                         | nanobot 的 SettingsView（多 section 导航）                   | 配置管理                                     | P2                         |
| **ModelSelector**   | 模型选择器：provider + model 下拉          | nanobot 的模型 badge + provider logo                         | Agent 配置                                   | P3                         |
| **ConnectionBadge** | 连接状态指示器：小圆点+颜色+脉冲           | nanobot 的 ConnectionBadge（emerald/amber/red）              | WebSocket 状态                               | P1                         |

---

## 11. API 与状态管理建议

### 11.1 API Client 组织

```
src/lib/
├── api.js           # REST API client（统一 fetch 封装、错误处理）
├── ws-client.js     # WebSocket client（连接管理、自动重连、事件分发）
├── endpoints.js     # 端点常量定义
└── types.js         # JSDoc 类型定义
```

**api.js 设计要点：**

```javascript
// 统一请求函数
async function request(path, options) { ... }

// 按业务域组织
export const sessions = {
  list: () => request('/api/sessions'),
  getMessages: (name) => request(`/api/sessions/${name}/messages`),
  delete: (name) => request(`/api/sessions/${name}`, { method: 'DELETE' }),
};

export const config = {
  status: () => request('/api/config/status'),
  get: () => request('/api/config'),
  defaults: () => request('/api/config/defaults'),
  save: (patch) => request('/api/config', { method: 'PUT', body: JSON.stringify(patch) }),
};

export const multimodal = {
  ask: (files, question, sessionName) => {
    const form = new FormData();
    files.forEach(f => form.append('files', f));
    form.append('question', question);
    form.append('session_name', sessionName);
    return request('/api/multimodal/ask', { method: 'POST', body: form });
  },
};
```

**ws-client.js 设计要点：**

从当前 `useWebSocket.js` 中抽出 WebSocket 连接管理逻辑：

```javascript
class ZBotWebSocket {
  constructor(url) { ... }
  connect() { ... }
  disconnect() { ... }
  send(command, payload) { ... }
  on(eventType, handler) { ... }   // 事件监听
  off(eventType, handler) { ... }  // 取消监听
  // 自动重连（指数退避 0.5s → 15s）
  // 连接状态：connecting / connected / disconnected / error
}
```

### 11.2 Hooks 组织

```
src/hooks/
├── useConfig.js           # 现有 — 配置状态检测
├── useWebSocket.js        # 现有 — 简化为事件处理，连接管理移至 ws-client.js
├── useSessions.js         # 新建 — 会话列表 CRUD（调用 api.sessions）
├── useSessionHistory.js   # 新建 — 单会话历史消息加载 + 缓存
├── useSendMessage.js      # 新建 — 发送消息逻辑（从 ChatPage 抽出）
└── useErrorParser.js      # 新建 — 错误事件解析为用户友好文案
```

### 11.3 状态管理建议

**不需要引入 Redux/Zustand 等外部库。** 当前项目规模用 React 内置 hooks + Context 足够。

建议引入一个 `ApiContext`：

```javascript
// src/providers/ApiProvider.jsx
const ApiContext = createContext(null);

export function ApiProvider({ children }) {
  const { apiBase } = useConfig();
  const api = useMemo(() => createApiClient(apiBase), [apiBase]);
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi() {
  return useContext(ApiContext);
}
```

这样任何组件都可以通过 `useApi()` 获取 API client，不需要层层传递 `apiBase` prop。

---

## 12. UI 设计系统建议

### 12.1 色彩

**品牌主色：** 蓝色（`hsl(217, 91%, 60%)` — 类似当前的 `#3b82f6`）

**语义色定义：**

| 令牌名                        | 亮色模式值  | 用途                         |
| ----------------------------- | ----------- | ---------------------------- |
| `--color-background`        | `#ffffff` | 页面背景                     |
| `--color-foreground`        | `#1a1a2e` | 正文文字                     |
| `--color-muted`             | `#f1f5f9` | 次要背景（侧边栏、标签）     |
| `--color-muted-foreground`  | `#64748b` | 次要文字                     |
| `--color-accent`            | `#3b82f6` | 强调色（按钮、链接、选中态） |
| `--color-accent-foreground` | `#ffffff` | 强调色上的文字               |
| `--color-destructive`       | `#ef4444` | 危险操作（删除、错误）       |
| `--color-border`            | `#e2e8f0` | 边框、分隔线                 |
| `--color-card`              | `#ffffff` | 卡片背景                     |
| `--color-success`           | `#22c55e` | 成功状态                     |
| `--color-warning`           | `#f59e0b` | 警告状态                     |

### 12.2 间距

采用 4px 基础网格：

| 令牌          | 值   | 典型用途       |
| ------------- | ---- | -------------- |
| `--space-1` | 4px  | 图标与文字间距 |
| `--space-2` | 8px  | 紧凑元素间距   |
| `--space-3` | 12px | 行内元素间距   |
| `--space-4` | 16px | 区块内间距     |
| `--space-6` | 24px | 区块间间距     |
| `--space-8` | 32px | 大区块间距     |

### 12.3 圆角

| 令牌              | 值     | 用途                     |
| ----------------- | ------ | ------------------------ |
| `--radius-sm`   | 4px    | 小元素（badge、小按钮）  |
| `--radius`      | 6px    | 默认（输入框、卡片）     |
| `--radius-lg`   | 12px   | 大容器（面板、对话框）   |
| `--radius-full` | 9999px | 药丸形状（用户消息气泡） |

### 12.4 阴影

| 令牌            | 值                                   | 用途             |
| --------------- | ------------------------------------ | ---------------- |
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)`       | 卡片、输入框     |
| `--shadow-md` | `0 4px 6px -1px rgba(0,0,0,0.1)`   | 弹出菜单、下拉   |
| `--shadow-lg` | `0 10px 15px -3px rgba(0,0,0,0.1)` | 模态框、Composer |

### 12.5 字体层级

| 层级            | 字号 | 行高 | 用途             |
| --------------- | ---- | ---- | ---------------- |
| `--text-xs`   | 12px | 16px | 时间戳、辅助文字 |
| `--text-sm`   | 14px | 20px | 正文、列表项     |
| `--text-base` | 16px | 24px | 标题、重要文字   |
| `--text-lg`   | 18px | 28px | 页面标题         |
| `--text-xl`   | 20px | 28px | 品牌名称         |

**CJK 优化：** 中文内容行高使用 1.6-1.8，比英文内容略大。

### 12.6 组件 Variant 建议

**Button：**

| Variant       | 样式                   | 用途                   |
| ------------- | ---------------------- | ---------------------- |
| `primary`   | 蓝色填充、白色文字     | 主要操作（发送、保存） |
| `secondary` | 灰色填充、深色文字     | 次要操作（取消、关闭） |
| `ghost`     | 透明背景、hover 时浅灰 | 工具栏按钮             |
| `danger`    | 红色填充、白色文字     | 危险操作（删除）       |

| Size   | 样式               |
| ------ | ------------------ |
| `sm` | 32px 高、12px 字号 |
| `md` | 40px 高、14px 字号 |
| `lg` | 48px 高、16px 字号 |

**Badge（连接状态）：**

| Variant     | 颜色   | 含义          |
| ----------- | ------ | ------------- |
| `success` | 绿色   | 已连接        |
| `warning` | 琥珀色 | 连接中/重连中 |
| `error`   | 红色   | 连接错误      |
| `muted`   | 灰色   | 未连接/空闲   |

---

## 13. 测试与质量保障建议

### 13.1 测试框架引入

```bash
# 安装测试依赖
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event happy-dom
```

在 `package.json` 中添加：

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage"
  }
}
```

### 13.2 优先测试的模块

| 优先级 | 模块                               | 测试内容                                                                          |
| ------ | ---------------------------------- | --------------------------------------------------------------------------------- |
| P0     | `utils/format.js`                | `socketStateLabel`、`eventTitle`、`eventMessage`、`formatTime` 的输入输出 |
| P0     | `lib/api.js`（新建后）           | 请求函数的 URL 拼接、错误处理、JSON 解析                                          |
| P1     | `hooks/useConfig.js`             | 配置检测流程（mock fetch）                                                        |
| P1     | `hooks/useWebSocket.js`          | 事件路由、状态转换（mock WebSocket）                                              |
| P1     | `hooks/useSessions.js`（新建后） | 会话列表加载、删除操作                                                            |
| P2     | `components/SessionList.jsx`     | 列表渲染、选择交互、空状态                                                        |
| P2     | `components/MessageList.jsx`     | 消息渲染、流式显示                                                                |
| P2     | `components/Composer.jsx`        | 输入、发送、禁用状态                                                              |

### 13.3 质量门禁

```bash
# 开发前检查
npm run lint          # ESLint 检查
npm run build         # 构建检查（确保无编译错误）

# 提交前检查
npm run test          # 运行全部测试
npm run lint -- --fix # 自动修复 lint 问题
```

建议在 `package.json` 中添加 pre-commit 脚本（可选）：

```json
{
  "scripts": {
    "precommit": "npm run lint && npm run test"
  }
}
```

### 13.4 防止 UI 重构破坏业务逻辑

1. **WebSocket 协议不变** — 无论前端怎么改组件，`sendMessage` 发送的 JSON 格式（`{type: "run.start", message: "...", session_name: "..."}`）必须保持不变
2. **API 接口不变** — 前端改 API client 封装方式时，确保调用的 URL 和 HTTP 方法不变
3. **渐进式替换** — 每次只改一个组件/模块，构建通过 + 手动验证后再改下一个
4. **关键路径手动测试清单：**
   - 首次配置流程：打开页面 → 填写 API key → 保存 → 进入聊天
   - 聊天流程：连接 WebSocket → 发送消息 → 收到流式回复 → 回复完成
   - 会话切换（TUTORIAL 完成后）：切换会话 → 加载历史 → 发送新消息
   - 设置修改：打开设置 → 修改配置 → 保存 → 验证生效

---

## 14. 风险和注意事项

| 风险                                 | 影响                     | 降低措施                                                                            |
| ------------------------------------ | ------------------------ | ----------------------------------------------------------------------------------- |
| **引入 Tailwind 导致样式混乱** | 新旧样式共存，维护两套   | 建议先用 CSS 变量，暂不引入 Tailwind。等项目增长后再考虑                            |
| **会话历史加载缺少后端 API**   | Phase 2 受阻             | 需要后端新增 `GET /api/sessions/{name}/messages`。应在 Phase 1 结束前确认后端排期 |
| **重构破坏 WebSocket 连接**    | 聊天功能不可用           | 重构 useWebSocket 时保持对外接口（sendMessage/stopRun/reconnect）不变               |
| **过度借鉴 nanobot 视觉**      | ZBot 失去自己的特色      | 保留三栏布局和 ActivityPanel，只借鉴色彩/间距/圆角等基础设计语言                    |
| **教学代码注释过多**           | 代码可读性下降           | 重构时逐步精简注释，保留必要的架构说明，删除"JS 入门"类注释                         |
| **TypeScript 迁移诱惑**        | 团队学习成本高、项目延期 | 明确不迁移 TS，用 JSDoc 补充类型。这是硬性决定，不讨论                              |
| **一次性重写太多**             | 无法回滚、bug 难定位     | 严格按 Phase 分阶段执行，每阶段完成后验证再进入下一阶段                             |
| **后端 API 变更**              | 前端对接失败             | 前端 API client 层集中管理端点，变更时只需改一处                                    |

---

## 15. 推荐执行顺序

以下是明确的 To-do list，按优先级和依赖关系排序。每个阶段完成后应验证构建和核心功能再进入下一阶段。

### 阶段 1：基础架构（预计 2-3 天）

- [ ] **1.1** 新建 `src/styles/tokens.css`，定义 CSS 变量设计令牌（色彩、圆角、间距、阴影、字体）
- [ ] **1.2** 在 `src/index.css` 中引入 `tokens.css`
- [ ] **1.3** 新建 `src/lib/api.js`，封装统一 fetch 请求函数和错误处理
- [ ] **1.4** 新建 `src/lib/endpoints.js`，集中定义 API 端点常量
- [ ] **1.5** 从 `useWebSocket.js` 中抽出连接管理逻辑，新建 `src/lib/ws-client.js`
- [ ] **1.6** 简化 `useWebSocket.js`，改为使用 ws-client.js
- [ ] **1.7** 安装 `react-router-dom`，修改 `App.jsx` 引入路由
- [ ] **1.8** 拆分 `App.css` 为多个文件（layout/sidebar/chat/composer/activity/onboard）
- [ ] **1.9** 运行 `npm run build` 确认构建通过
- [ ] **1.10** 手动验证：配置流程 + 聊天流程正常

### 阶段 2：会话管理（预计 3-4 天）

- [ ] **2.1** 创建 `src/hooks/useSessions.js` — 调用 GET /api/sessions，管理会话列表
- [ ] **2.2** 创建 `src/components/SessionListItem.jsx` — 单个会话条目
- [ ] **2.3** 创建 `src/components/SessionList.jsx` — 会话列表容器
- [ ] **2.4** 改造 `src/components/Sidebar.jsx` — 集成 SessionList，替代手动输入框
- [ ] **2.5** 改造 `src/pages/ChatPage.jsx` — 支持会话切换
- [ ] **2.6** 创建 `src/components/ui/EmptyState.jsx` — 通用空状态组件
- [ ] **2.7** 创建 `src/components/ui/Spinner.jsx` — 加载指示器
- [ ] **2.8** 为会话列表和聊天区添加空状态和加载状态
- [ ] **2.9** 运行 `npm run build` 确认构建通过
- [ ] **2.10** 手动验证：列出会话 → 选择会话 → 发送消息 → 切换会话 → 删除会话

### 阶段 3：消息历史与视觉基础（预计 3-4 天）

- [ ] **3.1** 与后端确认 `GET /api/sessions/{name}/messages` 端点排期
- [ ] **3.2** 创建 `src/hooks/useSessionHistory.js` — 加载会话历史消息 + 缓存
- [ ] **3.3** 改造 `ChatPage.jsx` — 切换会话时加载历史
- [ ] **3.4** 创建 `src/components/ui/Button.jsx` — 统一按钮组件
- [ ] **3.5** 创建 `src/components/ui/Input.jsx` — 统一输入组件
- [ ] **3.6** 创建 `src/components/ui/Card.jsx` — 统一卡片组件
- [ ] **3.7** 审查拆分后的样式文件，确保所有颜色值已替换为 CSS 变量（Phase 1 遗漏的补上）
- [ ] **3.8** 改造 `MessageList.jsx` — 助手长消息改为散文渲染模式
- [ ] **3.9** 改造 `ActivityPanel.jsx` + `EventRow.jsx` — 工具事件结构化（图标+颜色+折叠）
- [ ] **3.10** 添加消息入场动画（fade-in + slide-in）

### 阶段 4：交互增强与后端能力前端化（预计 3-4 天）

- [ ] **4.1** 创建 `src/components/ConnectionBadge.jsx` — 连接状态指示器（替换文本显示）
- [ ] **4.2** 创建 `src/components/ui/Badge.jsx` — 通用状态标签
- [ ] **4.3** 创建 `src/hooks/useErrorParser.js` — 解析错误事件 payload.code
- [ ] **4.4** 改造 Composer.jsx — 支持 hero/thread 双形态（空状态时居中大号）
- [ ] **4.5** 实现会话搜索功能（本地关键字过滤）
- [ ] **4.6** 实现侧边栏可折叠（展开/收起切换）
- [ ] **4.7** 实现"滚动到底部"按钮
- [ ] **4.8** 改造 OnboardPage → SettingsPage，支持多 section（基础配置 / 高级配置 / 工具配置）
- [ ] **4.9** 创建 `src/components/ToolEventDetail.jsx` — 工具事件详情展示
- [ ] **4.10** 创建 `src/components/SubAgentProgress.jsx` — 子 Agent 进度区分

### 阶段 5：测试与质量（预计 2-3 天）

- [ ] **5.1** 安装 Vitest + testing-library + happy-dom
- [ ] **5.2** 创建 vitest.config.js
- [ ] **5.3** 编写 `utils/format.js` 的单测
- [ ] **5.4** 编写 `lib/api.js` 的单测
- [ ] **5.5** 编写 `hooks/useSessions.js` 的单测
- [ ] **5.6** 编写 `components/SessionList.jsx` 的单测
- [ ] **5.7** 编写 `components/MessageList.jsx` 的单测
- [ ] **5.8** 编写集成测试：完整聊天流程
- [ ] **5.9** 在 package.json 中添加 test/build 脚本
- [ ] **5.10** 运行全部测试确认通过

### 后续（按需推进）

- [ ] **6.1** 文件上传功能（Composer + multimodal API）
- [ ] **6.2** 定时任务管理页面（需后端新增 API）
- [ ] **6.3** 技能系统管理页面（需后端新增 API）
- [ ] **6.4** 记忆系统查看页面（需后端新增 API）
- [ ] **6.5** 暗色模式支持（CSS 变量已预留 .dark class）
- [ ] **6.6** 移动端适配（侧边栏 Sheet 抽屉）

---

> **最终结论：ZBot 前端下一步应该先改 API 层抽象和 CSS 变量设计令牌（Phase 1），然后集成 SESSION_LIST_TUTORIAL 的会话列表功能并补齐空状态/错误状态（Phase 2），最后再逐步升级视觉和接入后端能力（Phase 3-5）。不要一上来就改样式，先让架构能支撑迭代。**
