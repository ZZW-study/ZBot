# 🤖 ZBot - 你的个人 AI 助手

ZBot 是一个本地优先的 AI 助手，提供 CLI 与 Web 双形态，支持多模型接入、工具调用、会话管理、定时任务、MCP 扩展和技能自我进化。

## ✨ 功能特性

### 💬 智能对话

- **多模型支持**：通过 LiteLLM 接入 OpenAI、DeepSeek、阿里通义千问、硅基流动、OpenRouter 等 10+ 提供商
- **会话管理**：多会话隔离，上下文与历史自动保存
- **Markdown 渲染**：代码块、表格、列表等格式正确显示
- **多模态**：支持图片与多格式文档

### 🛠️ 工具系统

- **Shell 命令执行**：在限定工作区内运行系统命令
- **文件操作**：读写、搜索、编辑
- **网页搜索与抓取**：集成第三方搜索引擎
- **定时任务**：Cron 表达式调度
- **子 Agent**：动态创建子智能体处理并行任务

### 🧠 技能进化

- 对话结束后自动回顾，提炼可复用的技能
- 技能全生命周期管理（创建/读取/更新/下线）
- 跨会话模式关联
- 健康检查与 Curator 机制

### ⏰ 定时任务

- 自然语言创建
- 标准 Cron 调度
- 执行历史与日志

### 🔌 MCP 扩展

- 原生 Model Context Protocol 协议兼容
- 运行时动态加载多个 MCP 服务

### 🌐 Web 界面

- React 19 + Vite 前端
- FastAPI 后端，REST + SSE 实时通信
- 流式输出、工具调用可视化

### 🛡️ 安全控制

- 工作区隔离
- 命令执行超时
- 任务完成度验收与重试

## 🚀 快速开始

### 环境要求

- Python 3.13.x
- `uv` 0.11+
- Node.js 18+（Web 界面需要）
- Windows / macOS / Linux

### 1. 安装依赖

```bash
git clone <repo-url>
cd ZBot
uv sync
```

> Windows 提示：如遇 `uv` 全局缓存权限问题，可在 PowerShell 中临时设置 `UV_CACHE_DIR` 到本地目录。

### 2. 初始化配置

```bash
uv run python -m ZBot onboard
```

按提示填入模型、API Key、工作区等。配置写入 `~/.ZBot/config.json`。

### 3. 开始使用

#### CLI 模式

```bash
# 交互模式
uv run python -m ZBot agent

# 单次对话
uv run python -m ZBot agent -m "用 Python 写一个快速排序"

# 指定会话
uv run python -m ZBot agent -s "work" -m "总结今天的会议要点"

# 查看状态
uv run python -m ZBot status
```

#### Web 模式

```bash
python start.py
# 或自定义
python start.py --port 9000 --reload
```

启动后访问：

- 前端界面：http://localhost:5173
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs

## 📖 使用指南

### CLI 交互模式

```
你：帮我查一下今天的天气
🤖 ZBot 正在思考…
🔧 调用工具: web_search("今天 北京 天气")
✓ 任务完成
```

### 创建定时任务

```
你：明早 9 点提醒我写周报
```

### 配置 MCP 服务

编辑 `~/.ZBot/config.json`，在 `mcp_servers` 字段添加：

```json
{
  "mcp_servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/workspace"]
    }
  }
}
```

## 🗂 项目架构

```
ZBot/
├── ZBot/
│   ├── agent/                 # Agent 核心
│   │   ├── service.py         # 主服务入口
│   │   ├── tools/             # 内置工具集
│   │   └── prompts/           # 提示词
│   │
│   ├── backend/               # Web 后端
│   │   ├── routers/           # API 路由
│   │   ├── handlers/          # SSE / WS 处理
│   │   └── models/            # Pydantic 模型
│   │
│   ├── cli/                   # CLI 入口
│   │
│   ├── config/                # 配置管理
│   │
│   ├── memory/                # 记忆系统
│   │   ├── session_memory.py  # 会话记忆
│   │   └── daily_memory.py    # 日常记忆（向量存储）
│   │
│   ├── cron/                  # 定时任务
│   │
│   ├── service/               # 服务层
│   │   ├── agent_run/         # Agent 运行
│   │   ├── heartbeat/         # 心跳
│   │   └── utils/
│   │
│   ├── skills/                # 技能库
│   │
│   ├── tasks/                 # 后台任务
│   ├── templates/
│   └── utils/
│
├── frontend/                  # React 前端
│   └── src/
│       ├── components/
│       ├── hooks/
│       ├── pages/
│       └── styles/
│
├── start.py                   # 一键启动
├── pyproject.toml
└── uv.lock
```

## 🐳 Docker 部署

```bash
docker-compose run --rm zbot
# 或
docker-compose up -d
docker exec -it zbot python -m ZBot agent
```

## 📦 依赖说明

主要依赖见 `pyproject.toml`：

- `litellm` / `pydantic` / `typer` / `rich` / `loguru` / `mcp` / `fastapi` / `uvicorn` / `croniter` / `sentence-transformers` / `sqlite-vec` / `websockets`

## ⚙️ 配置选项

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `model` | `""` | 模型名称 |
| `workspace` | `~/.ZBot/workspace` | 工作区 |
| `max_tokens` | `4396` | 输出 token 上限 |
| `temperature` | `0.1` | 采样温度 |
| `memory_window` | `25` | 记忆窗口 |
| `max_tool_iterations` | `50` | 单轮最大工具调用次数 |
| `tools.restrict_to_workspace` | `false` | 是否限制工作区 |

## 🧪 开发

```bash
uv sync --extra dev
uv run pytest
uv run pytest --cov=ZBot
uv run ruff format .
uv run ruff check .
```

## 🛣 下一步计划

下面是路线图上正在推进或计划推进的方向，按主题分组，不承诺具体时间。

### 心跳机制

- 后台周期心跳：检测 Agent 进程、SSE 连接、MCP 服务存活
- 异常自动恢复：连接断开重连、僵尸 run 清理
- 健康面板：Web 端可看当前 run / 队列 / 心跳状态

### 沙箱与安全

- 工具级权限：把 `exec` / `edit_file` / `web_fetch` 分级授权
- 文件系统沙箱：脱离 `restrict_to_workspace` 的硬边界，使用 OS 级隔离（命名空间 / container）
- 网络出站控制：白名单域名、超时与流量审计
- 凭据脱敏：日志 / 提示词中自动遮蔽 API Key、Token

### 会话与可恢复

- 断点续跑：长任务中断后能恢复到上一个稳定 turn
- 多端同步：会话、follow-up 队列、设置跨设备一致
- 会话归档与回放：把一次完整 run 序列导出 / 重放

### 工具与能力

- 工具调用可视化：折叠卡片 + 输入/输出 diff + 耗时
- 流式渲染：Markdown + 代码高亮 + 复制按钮
- 附件与多模态：Composer 支持文件 / 图片拖拽
- 工具市场：内置技能 vs 用户技能分层管理

### 评测与质量

- Agent 评测集：长程、多工具、含陷阱与歧义的真实任务
- 验证器：副作用文件 / 工具多样性 / 运行结果联合判定
- 回归保护：每轮跑评测，输出可对比报告

### 体验与可达性

- 错误 Toast / 模态：把行内红字替换为统一错误层
- 移动端响应式：Sidebar 折叠为顶部抽屉
- 键盘可达性：完整 focus 顺序、aria-label、跳转链接

### 性能与稳定性

- 长上下文：摘要 + 检索混合策略，避免纯窗口截断
- 工具调用并发：受控并行 + 限流
- 前端缓存：会话列表 / 消息 / 工具注册结果按需持久化

## 🤝 贡献

欢迎 PR 与 Issue。

## 📄 许可证

MIT License

## 📮 联系方式

GitHub Issues。