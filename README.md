# 🤖 ZBot - 你的个人 AI 助手

ZBot 是一个功能强大的 AI 助手，提供 CLI 交互和 Web 界面双模式，支持多模型切换、工具调用、技能进化、定时任务、MCP 扩展等能力。

## ✨ 功能特性

### 💬 智能对话

- **多模型支持**：通过 LiteLLM 统一接入 OpenAI、DeepSeek、阿里通义千问、硅基流动、OpenRouter 等 10+ 提供商
- **会话管理**：多会话隔离，自动保存对话上下文和历史记录
- **上下文压缩**：智能记忆窗口 + 后台会话归档，避免上下文溢出
- **Markdown 渲染**：优雅显示代码、表格等格式化内容
- **多模态支持**：支持图片上传和多文档格式处理和理解

### 🛠️ 工具系统

- **Shell 命令**：AI 可以帮你执行系统命令
- **文件操作**：读写、搜索、编辑、管理工作区文件
- **网页搜索**：联网搜索获取最新信息（支持 Bocha 等搜索引擎）
- **网页内容提取**：智能提取网页正文
- **定时任务**：Cron 表达式调度，自然语言创建提醒
- **子 Agent**：动态创建子智能体处理并行任务

### 🧠 技能进化

- **自动技能学习**：会话结束后自动回顾对话，提炼可复用的技能
- **技能管理**：创建、读取、更新技能的完整生命周期
- **复杂度评估**：只对复杂任务触发技能进化，避免噪声
- **跨会话模式**：通过日常记忆关联跨会话的重复模式
- **Curator 机制**：自动健康检查与生命周期转换

### ⏰ 定时任务

- **自然语言创建**：用日常语言描述即可创建定时任务
- **Cron 调度**：支持标准 Cron 表达式
- **执行历史**：查看任务执行结果和日志

### 🔌 MCP 扩展

- **协议兼容**：原生支持 Model Context Protocol (MCP) 标准
- **动态加载**：运行时连接多个 MCP 服务器
- **工具扩展**：接入官方或社区提供的 MCP 工具

### 🌐 Web 界面

- **React 前端**：基于 React 19 + Vite 的现代 Web UI
- **FastAPI 后端**：提供 REST API + WebSocket 实时通信
- **多模态支持**：前端支持图片上传、多格式文档上传等多模态交互

### 🛡️ 安全控制

- **工作区限制**：AI 只能访问指定目录
- **超时控制**：防止命令无限执行
- **代理配置**：支持 HTTP/SOCKS 代理
- **任务验收**：自动验证任务完成度，未完成任务自动重试

## 🚀 快速开始

### 环境要求

- Python 3.13.x
- `uv` 0.11+（推荐，用于依赖管理）
- Node.js 18+（Web 界面需要）
- 支持的系统：Windows、macOS、Linux

### 1. 安装依赖

```bash
# 克隆项目
git clone <repo-url>
cd ZBot

# 安装 Python 依赖
uv sync
```

> **Windows 提示**：如果 `uv run` 因全局缓存目录权限报错，可先在 PowerShell 中执行：
>
> ```powershell
> $env:UV_CACHE_DIR = "$PWD\.uv-cache"
> ```

### 2. 初始化配置

```bash
# 首次运行，自动创建配置文件
uv run python -m ZBot onboard
```

### 3. 配置模型

编辑生成的配置文件 `~/.ZBot/config.json`：

```json
{
  "model": "deepseek/deepseek-chat",
  "providers": {
    "deepseek": {
      "api_key": "your_deepseek_api_key",
      "api_base": "https://api.deepseek.com/v1"
    }
  },
  "workspace": "~/.ZBot/workspace"
}
```

**常用模型配置参考**：

| 提供商     | 模型名称                                | API Base                                              |
| ---------- | --------------------------------------- | ----------------------------------------------------- |
| DeepSeek   | `deepseek/deepseek-chat`              | `https://api.deepseek.com/v1`                       |
| 阿里通义   | `dashscope/qwen-turbo`                | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 硅基流动   | `siliconflow/DeepSeek-V2.5`           | `https://api.siliconflow.cn/v1`                     |
| OpenAI     | `openai/gpt-4o-mini`                  | `https://api.openai.com/v1`                         |
| OpenRouter | `openrouter/anthropic/claude-3-haiku` | `https://openrouter.ai/api/v1`                      |

### 4. 开始使用

#### CLI 模式

```bash
# 交互模式
uv run python -m ZBot agent

# 单次对话
uv run python -m ZBot agent -m "你好，请帮我写一个 Python 快速排序"

# 指定会话
uv run python -m ZBot agent -s "work" -m "总结今天的会议要点"

# 查看配置状态
uv run python -m ZBot status
```

#### Web 模式

```bash
# 一键启动前后端服务
python start.py

# 自定义端口和热重载
python start.py --port 9000 --reload
```

启动后访问：

- **前端界面**：http://localhost:5173
- **后端 API**：http://localhost:8000
- **API 文档**：http://localhost:8000/docs

## 📖 使用指南

### CLI 交互模式

```
你：帮我查询今天的天气
🤖 ZBot 正在思考...
↳ 正在调用工具：网页搜索
↳ 进度：天气查询完成
ZBot
今天北京天气：晴转多云，22-30℃，空气质量优。

你：/new           # 开始新会话
你：exit           # 退出程序
```

### 创建定时任务

```bash
# 每天早上 9 点提醒我写日报
uv run python -m ZBot agent -m "每天早上 9 点提醒我写日报"

# 每周一检查项目更新
uv run python -m ZBot agent -m "每周一早上 10 点检查 GitHub 项目更新"
```

### 配置 MCP 服务器

在 `config.json` 中添加：

```json
{
  "tools": {
    "mcp_servers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"]
      }
    }
  }
}
```

### 配置网页搜索

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "bocha",
        "api_key": "your_bocha_api_key",
        "max_results": 5
      },
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

### Shell 执行配置

```json
{
  "tools": {
    "exec": {
      "timeout": 60,
      "path_append": "/usr/local/bin"
    }
  }
}
```

## 🏗️ 项目架构

```
ZBot/
├── ZBot/
│   ├── __main__.py            # CLI 入口
│   ├── __init__.py            # 包元信息
│   │
│   ├── cli/                   # 命令行界面
│   │   └── commands.py        # Typer 命令定义 (onboard, agent)
│   │
│   ├── agent/                 # Agent 核心
│   │   ├── core_agent.py      # 主 Agent：会话、记忆、工具调度
│   │   ├── base_agent.py      # Agent 基类：消息循环、工具执行
│   │   ├── context.py         # 上下文构建（系统提示、记忆注入）
│   │   ├── skills_load.py     # 技能加载
│   │   ├── evolution/         # 技能进化机制
│   │   │   ├── complexity.py  # 任务复杂度评估
│   │   │   ├── curator.py     # 技能生命周期管理
│   │   │   ├── lifecycle.py   # 状态转换规则
│   │   │   ├── metrics.py     # 进化事件记录
│   │   │   ├── trajectory.py  # 会话轨迹提取
│   │   │   └── usage_tracker.py # 技能使用追踪
│   │   ├── subagent/          # 子 Agent 系统
│   │   │   ├── subagent.py    # 子 Agent 实现
│   │   │   └── subagent_pool.py # 子 Agent 池管理
│   │   └── tools/             # 工具实现
│   │       ├── base.py        # 工具基类
│   │       ├── shell.py       # Shell 命令
│   │       ├── filesystem.py  # 文件操作
│   │       ├── web.py         # 网页搜索
│   │       ├── search.py      # 搜索工具
│   │       ├── cron.py        # 定时任务
│   │       ├── mcp.py         # MCP 集成
│   │       ├── skills.py      # 技能管理工具
│   │       ├── create_sub_agent.py # 子 Agent 创建
│   │       └── registry.py    # 工具注册表
│   │
│   ├── backend/               # FastAPI Web 后端
│   │   ├── app.py             # FastAPI 应用入口 + CORS
│   │   ├── parse.py           # 请求解析
│   │   └── routers/           # API 路由
│   │       ├── agent.py       # Agent 交互 API
│   │       ├── config.py      # 配置管理 API
│   │       └── multimodal.py  # 多模态 API
│   │
│   ├── frontend/              # React Web 前端
│   │   ├── src/
│   │   │   ├── components/    # React 组件
│   │   │   ├── pages/         # 页面
│   │   │   ├── hooks/         # 自定义 Hooks
│   │   │   └── utils/         # 前端工具函数
│   │   └── package.json       # 前端依赖
│   │
│   ├── config/                # 配置模块
│   │   ├── schema.py          # 配置结构定义
│   │   ├── loader.py          # 配置加载器
│   │   └── paths.py           # 路径工具
│   │
│   ├── providers/             # LLM 提供商
│   │   ├── base.py            # 提供商基类
│   │   └── litellm_provider.py # LiteLLM 实现
│   │
│   ├── session/               # 会话管理
│   │   └── manager.py         # 会话管理器
│   │
│   ├── memory/                # 记忆系统
│   │   └── daily_memory.py    # 日常记忆（向量存储）
│   │
│   ├── cron/                  # 定时任务
│   │   ├── service.py         # 任务服务
│   │   └── types.py           # 类型定义
│   │
│   ├── service/               # 服务层
│   │   ├── agent_run/         # Agent 运行服务
│   │   ├── heartbeat/         # 心跳服务
│   │   └── utils/             # 服务工具（hooks、helpers）
│   │
│   ├── skills/                # 内置技能库
│   │   ├── clawhub/           # ClawHub 集成
│   │   ├── cron/              # 定时任务技能
│   │   ├── docker-compose-python/ # Docker Compose
│   │   ├── fastapi-sqlalchemy-alembic/ # Web 框架
│   │   ├── github/            # GitHub 操作
│   │   ├── image-generation/  # 图片生成
│   │   ├── long-goal/         # 长期目标
│   │   ├── memory/            # 记忆管理
│   │   ├── skill-creator/     # 技能创建
│   │   ├── summarize/         # 摘要生成
│   │   ├── tmux/              # Tmux 管理
│   │   └── weather/           # 天气查询
│   │
│   ├── tasks/                 # 后台任务
│   ├── templates/             # 模板文件
│   ├── test/                  # 测试文件
│   └── utils/                 # 通用工具函数
│
├── start.py                   # 一键启动脚本（前后端）
├── Dockerfile                 # Docker 构建
├── docker-compose.yml         # Docker Compose
├── pyproject.toml             # 项目元数据与依赖声明
└── uv.lock                    # uv 锁定依赖
```

## 🐳 Docker 部署

```bash
# 交互模式运行
docker-compose run --rm zbot

# 或启动容器后进入交互
docker-compose up -d
docker exec -it zbot python -m ZBot agent
```

## 📦 依赖说明

项目依赖由 `pyproject.toml` 和 `uv.lock` 管理。

| 依赖                      | 用途                   |
| ------------------------- | ---------------------- |
| `typer`                 | CLI 命令行框架         |
| `prompt_toolkit`        | 高级终端输入           |
| `rich`                  | 富文本/Markdown 输出   |
| `litellm`               | 多模型统一接口         |
| `pydantic`              | 数据验证与配置         |
| `loguru`                | 日志管理               |
| `mcp`                   | Model Context Protocol |
| `fastapi` + `uvicorn` | Web API 后端           |
| `websockets`            | WebSocket 实时通信     |
| `croniter`              | Cron 表达式解析        |
| `sentence-transformers` | 向量嵌入（记忆系统）   |
| `sqlite-vec`            | 向量数据库             |
| `ruff`                  | 代码格式化             |

## ⚙️ 配置选项

| 配置项                          | 默认值                | 说明              |
| ------------------------------- | --------------------- | ----------------- |
| `model`                       | `""`                | 使用的模型名称    |
| `workspace`                   | `~/.ZBot/workspace` | 工作区目录        |
| `max_tokens`                  | `4396`              | 最大输出 token 数 |
| `temperature`                 | `0.1`               | 采样温度          |
| `memory_window`               | `25`                | 记忆窗口大小      |
| `max_tool_iterations`         | `50`                | 工具调用最大次数  |
| `tools.restrict_to_workspace` | `false`             | 是否限制工作区    |

## 🧪 开发

```bash
# 安装开发依赖
uv sync --extra dev

# 运行测试
uv run pytest

# 运行测试 + 覆盖率
uv run pytest --cov=ZBot --cov-report=term-missing

# 代码格式化
uv run ruff format .

# 代码检查
uv run ruff check .
```

## 📝 技术亮点

1. **多提供商集成**：通过 LiteLLM 统一接入 10+ LLM 提供商
2. **工具注册系统**：灵活的 Tool Registry 设计模式
3. **Agent 架构**：基于消息循环的智能体，支持子 Agent 并行
4. **技能进化**：自动从对话中提炼可复用技能，跨会话模式关联
5. **MCP 协议**：原生支持 Model Context Protocol
6. **记忆系统**：会话记忆 + 日常记忆（向量存储）双层架构
7. **任务验收**：自动验证完成度，未完成任务自动重试（最多 3 次）
8. **跨平台兼容**：Windows/macOS/Linux 全平台支持
9. **双模式**：CLI + Web 界面，满足不同使用场景
10. **安全控制**：工作区隔离、超时保护

## 🤝 贡献指南

欢迎贡献代码！请提交 Pull Request 或 Issue。

## 📄 许可证

MIT License

## 📮 联系方式

如有问题，请提交 GitHub Issue。
