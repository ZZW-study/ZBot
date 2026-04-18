# ZBot 项目面试背诵手册

> 本手册详细整理了 ZBot 项目的核心架构、关键代码实现和面试可能问到的问题，帮助你深入理解项目并在面试中自信回答。

---

## 目录

- [一、项目概述](#一项目概述)
- [二、核心架构](#二核心架构)
- [三、AgentLoop 核心循环](#三agentloop-核心循环)
- [四、上下文构建系统](#四上下文构建系统)
- [五、工具系统](#五工具系统)
- [六、长期记忆与归档](#六长期记忆与归档)
- [七、会话管理](#七会话管理)
- [八、LLM 提供商抽象](#八llm-提供商抽象)
- [九、技能系统](#九技能系统)
- [十、配置管理](#十配置管理)
- [十一、CLI 命令行接口](#十一cli-命令行接口)
- [十二、设计模式总结](#十二设计模式总结)
- [十三、面试高频问题](#十三面试高频问题)
- [十四、深度面试问题（进阶篇）](#十四深度面试问题进阶篇)
- [十五、场景模拟面试](#十五场景模拟面试)

---

## 一、项目概述

### 1.1 项目简介

ZBot 是一个基于 Python 的 AI 助手框架，支持多种大语言模型（LLM）提供商，具备工具调用、长期记忆、技能扩展等核心能力。

**核心特性：**

- 多 LLM 提供商支持（OpenRouter、DeepSeek、通义千问、硅基流动等）
- 工具调用系统（文件操作、Shell 执行、网页搜索、定时任务）
- 长期记忆与历史归档
- MCP（Model Context Protocol）协议支持
- 技能扩展系统
- 会话持久化

### 1.2 项目目录结构

```
ZBot/
├── ZBot/
│   ├── __init__.py          # 包元信息
│   ├── __main__.py          # 程序入口
│   ├── agent/               # 核心智能体模块
│   │   ├── loop.py          # AgentLoop 主循环
│   │   ├── context.py       # 上下文构建器
│   │   ├── memory.py        # 长期记忆存储
│   │   ├── skills.py        # 技能加载器
│   │   └── tools/           # 工具模块
│   │       ├── base.py      # 工具基类
│   │       ├── registry.py  # 工具注册表
│   │       ├── filesystem.py
│   │       ├── shell.py
│   │       ├── web.py
│   │       ├── cron.py
│   │       └── mcp.py
│   ├── cli/                 # 命令行接口
│   ├── config/              # 配置管理
│   ├── providers/           # LLM 提供商
│   ├── session/             # 会话管理
│   ├── skills/              # 内置技能库
│   └── templates/           # 提示词模板
```

### 1.3 技术栈

| 技术                     | 用途                  |
| ------------------------ | --------------------- |
| **typer**          | CLI 框架              |
| **pydantic**       | 数据验证和配置模型    |
| **rich**           | 终端富文本输出        |
| **prompt_toolkit** | 高级终端输入          |
| **loguru**         | 日志记录              |
| **asyncio**        | 异步编程              |
| **LiteLLM**        | 多 LLM 提供商统一接口 |
| **httpx**          | 异步 HTTP 客户端      |

---

## 二、核心架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Layer                             │
│                    (commands.py)                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     AgentLoop                                │
│    ┌─────────────────────────────────────────────────┐      │
│    │              ContextBuilder                      │      │
│    │    ┌─────────┬─────────┬─────────┐              │      │
│    │    │ Memory  │ Skills  │Bootstrap│              │      │
│    │    │ Store   │ Loader  │ Files   │              │      │
│    │    └─────────┴─────────┴─────────┘              │      │
│    └─────────────────────────────────────────────────┘      │
│    ┌─────────────────────────────────────────────────┐      │
│    │              ToolRegistry                        │      │
│    │    ┌──────┬──────┬──────┬──────┬──────┐        │      │
│    │    │File  │Shell │ Web  │ Cron │ MCP  │        │      │
│    │    │Tools │Tool  │Tools │Tool  │Tools │        │      │
│    │    └──────┴──────┴──────┴──────┴──────┘        │      │
│    └─────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LLMProvider                               │
│                 (LiteLLMProvider)                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    SessionManager                            │
│                    (JSONL 持久化)                            │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心工作流程

```
用户消息
    │
    ▼
process_direct() → _connect_mcp()（懒连接 MCP）
    │
    ▼
_process_message()
    ├── 解析内置命令（/new, /help）
    ├── _schedule_consolidation()（触发后台归档）
    └── _run_turn()
            │
            ▼
        build_messages()（构造消息链）
            │
            ▼
        _run_agent_loop()（核心循环）
            │
            ▼
        [模型响应]
            ├── 有工具调用 → 执行工具 → 回填结果 → 继续循环
            └── 无工具调用 → 返回最终回复
            │
            ▼
        _save_turn()（保存消息到会话）
```

---

## 三、AgentLoop 核心循环

### 3.1 类定义与职责

**文件位置：** `ZBot/agent/loop.py`

AgentLoop 是 ZBot 的核心运行时类，负责：

1. 管理工具注册和执行
2. 维护会话历史
3. 执行模型-工具循环
4. 处理长期记忆归档
5. 连接 MCP 服务器

### 3.2 核心属性

```python
class AgentLoop:
    # 工具返回结果的最大字符数限制
    _TOOL_RESULT_MAX_CHARS = 2000

    def __init__(
        self,
        provider: LLMProvider,          # 大模型提供者
        workspace: Path,                # 工作区目录
        model: str | None = None,       # 使用的模型名称
        max_iterations: int = 50,       # 最大工具调用迭代次数
        temperature: float = 0.1,       # 采样温度
        max_tokens: int = 4096,         # 模型最大输出 token 数
        memory_window: int = 50,        # 记忆窗口大小
        ...
    ):
        self.provider = provider
        self.workspace = workspace
        self.context = ContextBuilder(workspace)   # 上下文构造器
        self.sessions = SessionManager(workspace)  # 会话管理器
        self.tools = ToolRegistry()                # 工具注册中心
```

### 3.3 核心方法：_run_agent_loop

这是 Agent 的"大脑"，执行模型与工具的交互循环：

```python
async def _run_agent_loop(
    self,
    initial_messages: list[dict[str, Any]],
    on_progress: Callable[..., Awaitable[None]] | None = None,
) -> tuple[str | None, list[str], list[dict[str, Any]]]:
    """
    核心方法：执行模型与工具的交互循环。

    Returns:
        (final_content, tools_used, messages) 三元组
    """
    messages = list(initial_messages)    # 深拷贝初始消息列表
    tools_used: list[str] = []           # 记录使用的工具名称
    final_content: str | None = None     # 最终返回给用户的文本

    # 主交互循环：最多执行 max_iterations 次迭代
    for _ in range(self.max_iterations):
        # 1. 调用大模型
        response = await self.provider.chat(
            messages=messages,
            tools=self.tools.get_definitions(),
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        if response.has_tool_calls:
            # 2. 模型决定调用工具
            # 将工具调用意图写入消息链
            self.context.add_assistant_message(
                messages, response.content, tool_call_dicts
            )

            # 3. 逐个执行工具调用
            for tool_call in response.tool_calls:
                tools_used.append(tool_call.name)
                result = await self.tools.execute(
                    tool_call.name, tool_call.arguments
                )
                # 将工具结果写回消息链
                self.context.add_tool_result(
                    messages, tool_call.id, tool_call.name, result
                )
            continue  # 继续下一轮迭代

        # 4. 没有工具调用，返回最终回复
        final_content = self._strip_think(response.content)
        self.context.add_assistant_message(messages, final_content)
        break

    return final_content, tools_used, messages
```

### 3.4 思考块处理

```python
# 正则表达式：匹配大模型输出中的思考块
_THINK_BLOCK_RE = re.compile(r"<thinking>[\s\S]*?</thinking>", re.IGNORECASE)

@staticmethod
def _strip_think(text: str | None) -> str | None:
    """移除模型输出中的思考块并返回清理后的文本。"""
    if not text:
        return None
    cleaned = _THINK_BLOCK_RE.sub("", text).strip()
    return cleaned or None
```

### 3.5 面试问答

**Q: 为什么需要 max_iterations 限制？**

A: 防止工具调用进入死循环。例如，模型可能不断调用同一个工具，或者工具之间形成循环依赖。设置最大迭代次数（默认 50）可以确保系统在异常情况下也能正常退出。

**Q: 为什么要深拷贝 initial_messages？**

A: 保护调用者的数据。消息链在循环中会被修改（添加 assistant 消息、tool 消息等），如果不拷贝，会污染传入的原始数据。

**Q: _strip_think 方法的作用是什么？**

A: 移除模型输出中的思考块（`<thinking>...</thinking>`）。这些是模型推理过程中的中间内容，用户通常不需要看到，反而会增加上下文长度和 token 费用。

---

## 四、上下文构建系统

### 4.1 ContextBuilder 类

**文件位置：** `ZBot/agent/context.py`

ContextBuilder 负责组装发送给模型的消息，不负责调度和持久化。

```python
class ContextBuilder:
    """
    负责构建 system prompt 与当前轮消息列表。

    这个类的职责很单一：把各种输入源（引导文件、长期记忆、技能、历史对话、当前消息）
    组装成大模型可以理解的 messages 格式。
    """

    # 引导文件列表
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
```

### 4.2 System Prompt 构建顺序

```python
def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
    """
    构建完整的 system prompt。

    拼装顺序是刻意安排过的：
    1. 先给身份、运行环境和全局准则（让模型理解"我是谁"）
    2. 再给工作区中的引导文件（让模型理解"项目规则"）
    3. 再给长期记忆（让模型理解"历史侧写"）
    4. 最后再给技能正文和技能目录（让模型理解"可用能力"）
    """
    parts = [self._identity_prompt()]

    # 从工作区读取引导文件
    bootstrap = self._bootstrap_prompt()
    if bootstrap:
        parts.append(bootstrap)

    # 插入长期记忆的摘要
    memory_context = self.memory.get_memory_context()
    if memory_context:
        parts.append(f"# 长期记忆\n\n{memory_context}")

    # 加载始终启用的技能
    always_skills = self.skills.get_always_skills()
    if always_skills:
        active_skills = self.skills.load_skills_for_context(always_skills)
        if active_skills:
            parts.append(f"# 始终启用的技能\n\n{active_skills}")

    # 构建技能目录摘要
    summary = self.skills.build_skills_summary()
    if summary:
        parts.append(f"# 技能目录\n\n{summary}")

    return "\n\n---\n\n".join(parts)
```

### 4.3 身份提示词

```python
def _identity_prompt(self) -> str:
    """生成与运行环境相关的固定 system prompt 前缀。"""
    workspace_path = str(self.workspace.expanduser().resolve())
    system = platform.system()
    runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}，Python {platform.python_version()}"

    return (
        "# ZBot\n"
        "你是 ZBot，一名可靠、直接、善于执行的 AI 助手。\n\n"
        "## 运行环境\n"
        f"{runtime}\n\n"
        "## 工作区\n"
        f"你的工作区位于：{workspace_path}\n"
        f"- 长期记忆文件：{workspace_path}/memory/MEMORY.md\n"
        f"- 历史归档文件：{workspace_path}/memory/HISTORY.md\n"
        f"- 自定义技能目录：{workspace_path}/skills/{{skill-name}}/SKILL.md\n\n"
        "## 行为准则\n"
        "- 在调用工具前先说明你准备做什么，但不要在拿到结果前声称已经完成。\n"
        "- 编辑文件前先读取文件内容。\n"
        "- 涉及准确性的改动，编辑后要重新检查关键文件。\n"
        "- 工具失败时，先分析错误原因，再决定是否换一条路径。\n"
        "- 当用户意图确实存在歧义时，再提出澄清问题。\n\n"
        "普通对话时，直接给出自然语言回复即可。"
    )
```

### 4.4 消息链结构

```python
def build_messages(
    self,
    history: list[dict[str, Any]],
    current_message: str,
    skill_names: list[str] | None = None,
    media: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    构造一轮完整请求消息。

    返回结果固定包含三部分：
    1. 第一条 `system` 消息（包含身份、规则、记忆、技能等）
    2. 若干条历史消息（之前的对话内容）
    3. 当前轮 `user` 消息（用户输入 + 运行时元信息 + 可选媒体附件）
    """
    runtime_context = self._runtime_context()
    user_content = self._user_content(current_message, media)

    if isinstance(user_content, str):
        merged_content = f"{runtime_context}\n\n{user_content}"
    else:
        merged_content = [{"type": "text", "text": runtime_context}, *user_content]

    return [
        {"role": "system", "content": self.build_system_prompt(skill_names)},
        *history,
        {"role": "user", "content": merged_content},
    ]
```

### 4.5 运行时上下文

运行时上下文只对当前轮推理有意义，保存历史时会被剥离：

```python
_RUNTIME_CONTEXT_TAG = "[运行时上下文 - 仅供元数据参考，不是用户指令]"

@classmethod
def _runtime_context(cls) -> str:
    """生成当前轮专属的运行时上下文。"""
    timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M（%A）")
    lines = [f"当前时间：{timestamp}（北京时间，UTC+8）"]
    return cls._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)
```

### 4.6 面试问答

**Q: 为什么运行时上下文要在保存历史时剥离？**

A: 运行时信息（如当前时间）只对当前轮推理有意义。如果长期保留在 session 里，会污染历史、浪费存储，而且下次对话时这些信息已经过时了。

**Q: System Prompt 的构建顺序为什么这样设计？**

A: 让模型先理解"我是谁、当前环境是什么"，再理解"项目规则"和"可用能力"。这样模型会先建立身份认知，再学习具体规则。

**Q: 引导文件（BOOTSTRAP_FILES）的作用是什么？**

A: 这些文件会被直接拼进 system prompt，作为工作区的基础规则来源。用户可以在这些文件中定义项目特定的规则和准则，让模型理解项目的特殊要求。

---

## 五、工具系统

### 5.1 工具基类设计

**文件位置：** `ZBot/agent/tools/base.py`

```python
class Tool(ABC):
    """工具抽象基类。

    说明：具体的工具应继承此类并实现 `name`、`description`、`parameters`
    以及 `execute` 方法。基础类提供了参数类型转换与校验的通用实现。
    """

    # JSON Schema 的基础类型到 Python 类型的映射
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称（唯一标识）。"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具的简短描述，用于在调用方生成帮助或提示。"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """工具参数的 JSON Schema 定义（根类型通常为 object）。"""
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """执行工具的主入口，子类实现具体业务逻辑并返回字符串结果。"""
        pass
```

### 5.2 参数类型转换

```python
def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
    """根据工具的 `parameters` schema 对传入的参数进行类型转换。"""
    schema = self.parameters
    if schema.get("type", "object") != "object":
        return params
    return self._cast_object(params, schema)

def _cast_value(self, val: Any, schema: dict[str, Any]) -> Any:
    """根据子 schema 的 type 字段把单个值转换为目标类型。"""
    target_type = schema.get("type")

    # 字符串转整数
    if target_type == "integer" and isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            return val

    # 字符串解析为布尔
    if target_type == "boolean" and isinstance(val, str):
        val_lower = val.lower()
        if val_lower in ("true", "1", "yes"):
            return True
        if val_lower in ("false", "0", "no"):
            return False
        return val

    # 数组递归处理
    if target_type == "array" and isinstance(val, list):
        item_schema = schema.get("items")
        return [self._cast_value(item, item_schema) for item in val] if item_schema else val

    # 对象类型递归转换
    if target_type == "object" and isinstance(val, dict):
        return self._cast_object(val, schema)

    return val
```

### 5.3 参数校验

```python
def validate_params(self, params: dict[str, Any]) -> list[str]:
    """验证参数是否符合 `parameters` schema，返回错误消息列表（空表示通过）。"""
    if not isinstance(params, dict):
        return [f"参数必须是对象类型，当前收到的是 {type(params).__name__}"]
    return self._validate(params, self.parameters, "")

def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
    """递归校验单个值或对象是否满足 schema。"""
    errors = []
    t = schema.get("type")

    # 枚举约束
    if "enum" in schema and val not in schema["enum"]:
        errors.append(f"{path} 必须是以下值之一：{schema['enum']}")

    # 数值边界检查
    if t in ("integer", "number"):
        if "minimum" in schema and val < schema["minimum"]:
            errors.append(f"{path} 必须大于等于 {schema['minimum']}")
        if "maximum" in schema and val > schema["maximum"]:
            errors.append(f"{path} 必须小于等于 {schema['maximum']}")

    # 字符串长度约束
    if t == "string":
        if "minLength" in schema and len(val) < schema["minLength"]:
            errors.append(f"{path} 长度不能少于 {schema['minLength']} 个字符")
        if "maxLength" in schema and len(val) > schema["maxLength"]:
            errors.append(f"{path} 长度不能超过 {schema['maxLength']} 个字符")

    # 对象的必填项检查
    if t == "object":
        for k in schema.get("required", []):
            if k not in val:
                errors.append(f"缺少必填字段：{path + '.' + k if path else k}")

    return errors
```

### 5.4 工具注册中心

**文件位置：** `ZBot/agent/tools/registry.py`

```python
_RETRY_HINT = "\n\n[工具执行失败。请分析错误原因，然后继续尝试其他方法完成任务，不要停下来。]"

class ToolRegistry:
    """保存工具实例并提供统一执行入口。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具（同名覆盖）。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名称取回工具实例。"""
        return self._tools.get(name, None)

    def get_definitions(self) -> list[dict[str, Any]]:
        """返回所有工具 schema，供大模型决定是否进行函数调用。"""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """执行指定工具并统一包装错误。"""
        tool = self._tools.get(name)
        if tool is None:
            available = "、".join(self._tools)
            return f"错误：找不到工具"{name}"。当前可用工具：{available}"

        try:
            # 1. 参数类型转换
            cast_params = tool.cast_params(params)
            # 2. 参数校验
            errors = tool.validate_params(cast_params)
            if errors:
                return f"错误：工具"{name}"的参数不合法：{'；'.join(errors)}{_RETRY_HINT}"

            # 3. 执行工具
            result = await tool.execute(**cast_params)
            # 4. 错误包装
            if isinstance(result, str) and result.startswith("错误："):
                return result + _RETRY_HINT
            return result
        except Exception as exc:
            return f"错误：执行工具"{name}"时发生异常：{exc}{_RETRY_HINT}"
```

### 5.5 ExecTool 安全机制

**文件位置：** `ZBot/agent/tools/shell.py`

Shell 执行工具是整个系统风险最高的工具，实现了三层安全防护：

```python
class ExecTool(Tool):
    """执行 shell 命令，并在执行前做安全拦截。"""

    _MAX_TIMEOUT = 600   # 最大超时 10 分钟
    _MAX_OUTPUT = 10_000 # 最大输出 10KB

    def __init__(self, ...):
        # 默认危险命令黑名单
        self.deny_patterns = [
            r"\brm\s+-[rf]{1,2}\b",           # rm -rf
            r"\bdel\s+/[fq]\b",               # del /f /q (Windows)
            r"\brmdir\s+/s\b",                # rmdir /s (Windows)
            r"(?:^|[;&|]\s*)format\b",        # format
            r"\b(mkfs|diskpart)\b",           # 磁盘分区工具
            r"\bdd\s+if=",                    # dd if= (磁盘复制)
            r">\s*/dev/sd",                   # 写入磁盘设备
            r"\b(shutdown|reboot|poweroff)\b", # 关机命令
            r":\(\)\s*\{.*\};\s*:",           # Fork bomb
        ]

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """执行前的安全检查（三层防护）。"""
        cmd = command.strip()
        lower = cmd.lower()

        # 第一层：黑名单检查
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "错误：命令被安全策略拦截，检测到高风险模式。"

        # 第二层：白名单检查（可选）
        if self.allow_patterns and not any(
            re.search(pattern, lower) for pattern in self.allow_patterns
        ):
            return "错误：命令被安全策略拦截，不在允许执行的白名单中。"

        # 第三层：路径限制检查
        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "错误：命令被安全策略拦截，检测到路径穿越。"

            # 检查绝对路径是否越界
            for raw in self._extract_absolute_paths(cmd):
                path = Path(raw.strip()).expanduser().resolve()
                if path.is_absolute() and (cwd_path not in path.parents and path != cwd_path):
                    return "错误：命令被安全策略拦截，访问路径超出了当前工作目录。"

        return None  # 检查通过
```

### 5.6 文件系统工具

**文件位置：** `ZBot/agent/tools/filesystem.py`

```python
class ReadFileTool(Tool):
    """读取文件内容。"""
    _MAX_CHARS = 128_000  # 返回内容的最大字符数
    _DEFAULT_LIMIT = 2000  # 默认读取行数

    async def execute(self, path: str, offset: int = 1, limit: int | None = None, **kwargs) -> str:
        fp = _resolve_path(path, self._workspace, self._allowed_dir)
        if not fp.exists():
            return f"错误：文件不存在：{path}"

        all_lines = fp.read_text(encoding="utf-8").splitlines()
        # ... 分页读取逻辑 ...

class WriteFileTool(Tool):
    """写入文件。"""
    async def execute(self, path: str, content: str, **kwargs) -> str:
        fp = _resolve_path(path, self._workspace, self._allowed_dir)
        fp.parent.mkdir(parents=True, exist_ok=True)  # 自动创建父目录
        fp.write_text(content, encoding="utf-8")
        return f"已成功写入文件：{fp}"

class EditFileTool(Tool):
    """编辑文件（查找并替换文本）。"""
    async def execute(self, path: str, old_text: str, new_text: str, replace_all: bool = False, **kwargs) -> str:
        # 支持宽松匹配（忽略缩进差异）
        match, count = _find_match(content, old_text.replace("\r\n", "\n"))
        if match is None:
            return self._not_found_msg(old_text, content, path)
        # ... 替换逻辑 ...
```

### 5.7 面试问答

**Q: 为什么要设计 Tool 基类？**

A:

1. **统一接口**：所有工具都有相同的 name、description、parameters、execute 属性/方法
2. **参数处理复用**：类型转换和校验逻辑在基类中实现，子类无需重复
3. **扩展性好**：新增工具只需继承基类并实现抽象方法

**Q: 工具执行的完整流程是什么？**

A:

1. 从注册表获取工具实例
2. `cast_params()` 参数类型转换（如字符串"123"转整数123）
3. `validate_params()` 参数校验（检查必填、枚举、边界等）
4. `tool.execute()` 执行工具
5. 错误包装（自动附加重试提示）

**Q: Shell 工具的安全机制有哪些？**

A:

1. **黑名单检查**：阻止 rm -rf、shutdown 等危险命令
2. **白名单检查**：可选，只允许特定命令
3. **路径限制**：阻止访问工作区外的路径
4. **超时限制**：防止命令无限运行（默认 60 秒，最大 600 秒）
5. **输出截断**：防止超大输出占用内存（最大 10KB）

---

## 六、长期记忆与归档

### 6.1 MemoryStore 类

**文件位置：** `ZBot/agent/memory.py`

管理两个关键文件：

- `MEMORY.md`：长期记忆文件（可被模型读取和更新）
- `HISTORY.md`：历史归档文件（只追加不回写）

```python
class MemoryStore:
    """封装 `memory/` 目录中的读写与归档逻辑。"""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        """读取长期记忆全文。"""
        return self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""

    def write_long_term(self, content: str) -> None:
        """覆盖写入 MEMORY.md。"""
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        """向 HISTORY.md 追加一条阶段性摘要。"""
        with open(self.history_file, "a", encoding="utf-8") as handle:
            handle.write(entry.strip() + "\n\n")
```

### 6.2 归档工具定义

```python
_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "保存一条压缩后的历史摘要，并返回更新后的长期记忆内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "用 2 到 5 句话总结本次归档内容，并以 [YYYY-MM-DD HH:MM] 时间戳开头",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "更新后的完整 MEMORY.md 内容。",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]
```

### 6.3 归档流程

```python
async def consolidate(
    self,
    session: Session,
    provider: LLMProvider,
    model: str,
    *,
    archive_all: bool = False,
    memory_window: int = 50,
) -> bool:
    """把会话中的旧消息归档进长期记忆。"""
    # 1. 确定归档范围
    messages, keep_count = self._messages_to_archive(session, archive_all, memory_window)
    if not messages:
        return True

    # 2. 构造提示词
    current_memory = self.read_long_term()
    prompt = self._build_prompt(current_memory, messages)

    # 3. 调用大模型压缩历史
    response = await provider.chat(
        messages=[
            {"role": "system", "content": "你负责压缩对话历史，且必须调用 save_memory 工具返回结构化结果。"},
            {"role": "user", "content": prompt},
        ],
        tools=_SAVE_MEMORY_TOOL,
        model=model,
    )

    # 4. 处理结果
    if not response.has_tool_calls:
        return False

    args = self._normalize_tool_args(response.tool_calls[0].arguments)

    # 追加到 HISTORY.md
    history_entry = args.get("history_entry")
    if history_entry:
        self.append_history(history_entry)

    # 更新 MEMORY.md
    memory_update = args.get("memory_update")
    if memory_update and memory_update != current_memory:
        self.write_long_term(memory_update)

    # 更新会话的归档标记
    session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
    return True
```

### 6.4 归档范围计算

```python
@staticmethod
def _messages_to_archive(
    session: Session,
    archive_all: bool,
    memory_window: int,
) -> tuple[list[dict[str, Any]], int]:
    """确定本次要归档的消息区间。"""
    if archive_all:
        return list(session.messages), 0

    # 默认保留最近一半窗口的消息
    keep_count = max(1, memory_window // 2)
    if len(session.messages) <= keep_count:
        return [], keep_count

    start = session.last_consolidated
    end = len(session.messages) - keep_count
    if end <= start:
        return [], keep_count

    return session.messages[start:end], keep_count
```

### 6.5 归档触发机制

```python
def _schedule_consolidation(self, session: Session) -> None:
    """当未归档消息达到阈值时，安排后台归档任务。"""
    unconsolidated = len(session.messages) - session.last_consolidated

    # 未归档消息不足阈值，或会话已在归档中
    if unconsolidated < self.memory_window or session.key in self._consolidating:
        return

    # 标记为正在归档
    self._consolidating.add(session.key)

    # 创建后台任务
    task = asyncio.create_task(self._run_consolidation(session))
    self._consolidation_tasks.add(task)
    task.add_done_callback(self._consolidation_tasks.discard)
```

### 6.6 面试问答

**Q: 为什么用两个文件（MEMORY.md 和 HISTORY.md）？**

A:

- **MEMORY.md**：长期记忆，会被注入到 system prompt 中供模型参考。内容是压缩后的关键信息，需要持续更新。
- **HISTORY.md**：历史归档，只追加不修改，用于人工查阅和调试。保留完整的对话摘要。

**Q: 归档为什么是后台异步执行？**

A: 归档涉及调用大模型压缩历史，可能需要几秒钟。如果在主线程执行会阻塞用户对话，影响体验。后台执行可以让用户继续对话，归档完成后自动更新记忆。

**Q: 如何防止并发归档冲突？**

A:

1. `_consolidating` 集合标记正在归档的会话
2. 每个会话有独立的 `_consolidation_locks` 异步锁
3. 同一会话不会被同时归档多次

**Q: 归档时为什么要保留最近一半窗口的消息？**

A: 这样下一轮模型还能看到足够新的上下文，而老消息不会无限膨胀。保留的消息不会被归档，确保对话的连续性。

---

## 七、会话管理

### 7.1 Session 类

**文件位置：** `ZBot/session/manager.py`

```python
@dataclass
class Session:
    """单个会话对象。"""

    key: str                                        # 会话的唯一标识符
    messages: list[dict[str, Any]] = field(default_factory=list)    # 消息列表
    created_at: datetime = field(default_factory=datetime.now)      # 创建时间
    updated_at: datetime = field(default_factory=datetime.now)      # 更新时间
    last_consolidated: int = 0                                      # 已归档的消息索引

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """向会话追加消息。"""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        })
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """返回历史消息列表（用于构造模型上下文）。"""
        # 从上次归档位置到末尾，再取最近的 max_messages 条
        messages = self.messages[self.last_consolidated :][-max_messages:]

        # 找到第一条 user 消息的位置
        first_user = next((i for i, m in enumerate(messages) if m.get("role") == "user"), None)
        if first_user is not None:
            messages = messages[first_user:]

        return messages

    def clear(self) -> None:
        """清空会话。"""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()
```

### 7.2 SessionManager 类

```python
class SessionManager:
    """会话文件管理器。

    文件布局：
    sessions/
      cli_default.jsonl   # CLI 默认会话
      user_123.jsonl      # 用户 123 的会话
    """

    def __init__(self, workspace: Path | str):
        self.sessions_dir = ensure_dir(Path(workspace) / "sessions")
        self._cache: dict[str, Session] = {}

    def get_or_create(self, key: str) -> Session:
        """获取或创建会话（先查缓存，再查磁盘）。"""
        session = self._cache.get(key)
        if session is None:
            session = self._load(key) or Session(key=key)
            self._cache[key] = session
        return session

    def save(self, session: Session) -> None:
        """保存会话到磁盘。"""
        path = self._session_path(session.key)
        lines = [json.dumps(self._metadata_line(session), ensure_ascii=False)]
        lines.extend(json.dumps(message, ensure_ascii=False) for message in session.messages)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._cache[session.key] = session
```

### 7.3 JSONL 持久化格式

```
文件格式：
Line 1: {"_type": "metadata", "key": "cli:default", "created_at": "2024-01-15T14:30:00", ...}
Line 2: {"role": "user", "content": "你好", "timestamp": "2024-01-15T14:30:05"}
Line 3: {"role": "assistant", "content": "你好！有什么可以帮你的？", "timestamp": "2024-01-15T14:30:10"}
Line 4: {"role": "user", "content": "帮我写个 Python 脚本", ...}
...
```

### 7.4 面试问答

**Q: 为什么用 JSONL 格式而不是 JSON？**

A:

1. **追加友好**：新消息只需在文件末尾追加一行，不需要重写整个文件
2. **内存效率**：可以逐行读取，不需要一次性加载整个文件
3. **容错性好**：某一行损坏不影响其他行

**Q: get_history 方法为什么要从第一个 user 消息开始？**

A: 避免 assistant/tool 消息作为上下文的起点。对话应该从用户发起开始，否则模型会困惑"这是谁说的"。

**Q: 缓存机制是如何工作的？**

A:

1. 首次访问时从磁盘加载会话，存入 `_cache` 字典
2. 后续访问直接从缓存返回
3. 保存时同时更新缓存和磁盘
4. `invalidate()` 方法可以强制重新加载

---

## 八、LLM 提供商抽象

### 8.1 数据结构定义

**文件位置：** `ZBot/providers/base.py`

```python
@dataclass
class ToolCallRequest:
    """大模型返回的工具调用请求。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """大模型返回的标准化响应。"""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    reasoning_content: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        """判断响应中是否包含工具调用。"""
        return len(self.tool_calls) > 0
```

### 8.2 抽象基类

```python
class LLMProvider(ABC):
    """LLM 提供商抽象基类。"""

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """清洗空内容消息，避免部分厂商因空字符串直接报错。"""
        # ... 清洗逻辑 ...

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """发送聊天请求并返回标准化响应。"""
        raise NotImplementedError

    @abstractmethod
    def get_default_model(self) -> str:
        """返回当前提供商默认模型名。"""
        raise NotImplementedError
```

### 8.3 LiteLLM 实现

**文件位置：** `ZBot/providers/litellm_provider.py`

```python
class LiteLLMProvider(LLMProvider):
    """通过 LiteLLM 统一调用所有大模型 API。"""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "",
        provider_name: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._gateway = find_gateway(provider_name)
        self._std_provider = find_by_model(default_model)

        litellm.api_key = api_key
        litellm.api_base = api_base
        litellm.suppress_debug_info = True
        litellm.drop_params = True

    def _resolve_model(self, model: str) -> str:
        """模型名称标准化：根据注册表自动添加前缀。"""
        if self._gateway:
            return f"{self._gateway.litellm_prefix}/{model}"
        elif self._std_provider:
            return f"{self._std_provider.litellm_prefix}/{model}"
        return model
```

### 8.4 提示词缓存策略

```python
def _apply_cache_control(
    self,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """注入提示词缓存控制标记。

    缓存策略：
    - system 消息：整个系统提示词缓存
    - tools 定义：工具列表缓存

    为什么只缓存这两个？
    - 它们在多轮对话中几乎不变，缓存命中率最高
    - 用户消息每轮都变，缓存无意义

    ephemeral 含义：
    - 短时缓存（约 5 分钟），适合单次会话场景
    """
    new_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg["content"]
            if isinstance(content, str):
                new_content = [{
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"}
                }]
            else:
                new_content = list(content)
                new_content[-1] = {**new_content[-1], "cache_control": {"type": "ephemeral"}}
            new_messages.append({**msg, "content": new_content})
        else:
            new_messages.append(msg)

    # 处理 tools 定义
    new_tools = tools
    if tools:
        new_tools = list(tools)
        new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

    return new_messages, new_tools
```

### 8.5 响应解析

```python
def _parse_response(self, response: Any) -> LLMResponse:
    """解析 LiteLLM 响应 → 标准化 LLMResponse。"""
    choice = response.choices[0]
    message = choice.message
    content = message.content
    finish_reason = choice.finish_reason

    # 合并多 Choice 的工具调用
    raw_tool_calls = []
    for ch in response.choices:
        msg = ch.message
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            raw_tool_calls.extend(msg.tool_calls)

    # 构造工具调用列表
    tool_calls = []
    for tc in raw_tool_calls:
        args = tc.function.arguments
        if isinstance(args, str):
            args = json_repair.loads(args)
        tool_calls.append(ToolCallRequest(
            id=_short_tool_id(),
            name=tc.function.name,
            arguments=args,
        ))

    # Token 统计
    usage = {}
    if hasattr(response, "usage") and response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        finish_reason=finish_reason or "stop",
        usage=usage,
        reasoning_content=getattr(message, "reasoning_content", None),
    )
```

### 8.6 面试问答

**Q: 为什么要设计 LLMProvider 抽象基类？**

A:

1. **解耦**：上层代码只面向统一接口编程，不依赖具体厂商
2. **可扩展**：新增提供商只需实现抽象方法
3. **可测试**：可以轻松 Mock 提供商进行单元测试

**Q: LiteLLM 的作用是什么？**

A: LiteLLM 是一个统一的大模型调用库，支持 OpenAI、Anthropic、国内厂商等多种 API。通过它，我们不需要为每个厂商写独立代码，所有逻辑由注册表驱动。

**Q: ephemeral 缓存是什么意思？**

A: 短时缓存（约 5 分钟），适合单次会话场景。区别于 persistent（持久缓存），后者适合跨会话复用。

**Q: 为什么要对 system 消息和 tools 定义做缓存？**

A: 它们在多轮对话中几乎不变，缓存命中率最高。用户消息每轮都变，缓存无意义。

---

## 九、技能系统

### 9.1 SkillsLoader 类

**文件位置：** `ZBot/agent/skills.py`

```python
# 内置技能目录路径
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# Frontmatter 正则表达式
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)

class SkillsLoader:
    """统一管理工作区技能和内置技能。"""

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
```

### 9.2 技能发现

```python
def _discover_skills(self) -> dict[str, dict[str, str]]:
    """扫描内置目录和工作区目录，收集技能清单。

    工作区技能可覆盖内置技能（同名时工作区优先）。
    """
    skills: dict[str, dict[str, str]] = {}

    # 扫描顺序：先内置，再工作区（工作区覆盖内置）
    for source, root in (("builtin", self.builtin_skills), ("workspace", self.workspace_skills)):
        if not root or not root.exists():
            continue
        for skill_dir in root.iterdir():
            skill_file = skill_dir / "SKILL.md"
            if skill_dir.is_dir() and skill_file.exists():
                skills[skill_dir.name] = {
                    "name": skill_dir.name,
                    "path": str(skill_file),
                    "source": source,
                }
    return skills
```

### 9.3 技能格式

```yaml
---
name: web_search
description: 网络搜索工具
requires:
  bins: [curl, jq]
  env: [API_KEY]
always: true
---

技能正文内容...
```

### 9.4 依赖检查

```python
def _requirements_status(
    self,
    name: str,
    metadata: dict[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """判断技能当前是否满足运行依赖。"""
    skill_meta = self._skill_meta(metadata or self.get_skill_metadata(name) or {})
    missing: list[str] = []

    requires = skill_meta.get("requires", {})

    # 检查命令行工具依赖
    for binary in requires.get("bins", []):
        if not shutil.which(binary):
            missing.append(f"缺少命令行工具：{binary}")

    # 检查环境变量依赖
    for env_name in requires.get("env", []):
        if not os.environ.get(env_name):
            missing.append(f"缺少环境变量：{env_name}")

    return not missing, missing
```

### 9.5 技能摘要构建

```python
def build_skills_summary(self) -> str:
    """构建一份紧凑的技能目录摘要（XML 格式）。"""
    skills = self.list_skills(filter_unavailable=False)
    if not skills:
        return ""

    lines = ["<skills>"]
    for skill in skills:
        metadata = self.get_skill_metadata(skill["name"]) or {}
        available, missing = self._requirements_status(skill["name"], metadata)

        lines.append(f'  <skill available="{str(available).lower()}">')
        lines.append(f"    <name>{skill['name']}</name>")
        lines.append(f"    <description>{self._skill_description(skill['name'], metadata)}</description>")
        lines.append(f"    <location>{skill['path']}</location>")
        if missing:
            lines.append(f"    <requires>{'，'.join(missing)}</requires>")
        lines.append("  </skill>")
    lines.append("</skills>")
    return "\n".join(lines)
```

### 9.6 面试问答

**Q: 技能系统的作用是什么？**

A: 技能是一种轻量级的能力扩展机制。通过 SKILL.md 文件定义，可以：

1. 扩展 AI 的能力边界（如 GitHub 操作、天气查询）
2. 注入领域知识（如代码规范、业务规则）
3. 声明依赖（命令行工具、环境变量）

**Q: 为什么工作区技能可以覆盖内置技能？**

A: 让用户可以自定义或升级技能，而不需要修改项目源码。这是"约定优于配置"的设计思想。

**Q: 技能的依赖检查是如何实现的？**

A:

1. 命令行工具：通过 `shutil.which()` 检查是否在 PATH 中
2. 环境变量：通过 `os.environ.get()` 检查是否设置

---

## 十、配置管理

### 10.1 Pydantic 配置模型

**文件位置：** `ZBot/config/schema.py`

```python
class Base(BaseModel):
    """配置基类：支持驼峰/下划线两种键名风格。"""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True
    )


class ProviderConfig(Base):
    """单个 LLM 提供商的配置。"""
    api_key: str = ""
    api_base: str = ""


class ProvidersConfig(Base):
    """所有 LLM 提供商的集合配置。"""
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)


class WebSearchConfig(Base):
    """网页搜索配置。"""
    provider: str = "bocha"
    api_key: str = ""
    max_results: int = 5


class ExecToolConfig(Base):
    """Shell 命令执行工具配置。"""
    timeout: int = 60
    path_append: str = ""


class MCPServerConfig(Base):
    """MCP 服务器连接配置。"""
    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    tool_timeout: int = 30
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])


class Config(BaseModel):
    """ZBot 根配置。"""
    workspace: str = "~/.ZBot/workspace"
    model: str = ""
    provider: str = "auto"
    max_tokens: int = 4396
    temperature: float = 0.1
    max_tool_iterations: int = 50
    memory_window: int = 50
    reasoning_effort: str | None = None

    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @property
    def workspace_path(self) -> Path:
        """将工作区路径中的 ~ 展开为实际家目录后返回。"""
        return Path(self.workspace).expanduser()
```

### 10.2 提供商匹配

```python
def get_provider(
    self,
    model: str | None = None,
) -> tuple[ProviderConfig | None, str | None, bool | None]:
    """根据模型名称查找对应的提供商配置。"""
    from ZBot.providers.registry import find_by_model, find_gateway

    # 1. 优先使用强制指定的提供商
    if self.provider != "auto":
        forced_spec = next((spec for spec in PROVIDERS if spec.name == self.provider), None)
        forced_config = getattr(self.providers, self.provider, None)
        if forced_spec and forced_config:
            return forced_config, forced_spec.name, forced_spec.is_gateway
        return None, None, None

    model = model or self.model
    if not model:
        return None, None, None

    # 2. 提取模型前缀，检查是否是网关
    model_prefix = model.split("/", 1)[0] if model else ""
    gateway_spec = find_gateway(model_prefix)
    if gateway_spec:
        gateway_config = getattr(self.providers, gateway_spec.name, None)
        return (gateway_config, gateway_spec.name, True) if gateway_config else (None, None, None)

    # 3. 检查是否是标准厂商
    std_spec = find_by_model(model)
    if std_spec:
        std_config = getattr(self.providers, std_spec.name, None)
        return (std_config, std_spec.name, False) if std_config else (None, None, None)

    return None, None, None
```

### 10.3 面试问答

**Q: 为什么用 Pydantic 定义配置？**

A:

1. **自动校验**：字段类型、必填项、格式自动校验
2. **序列化/反序列化**：轻松把 JSON 转成对象，也能把对象转回字典
3. **IDE 支持**：类型提示完善，IDE 自动补全
4. **别名支持**：配置文件中驼峰和下划线命名都能识别

**Q: 配置中的 `populate_by_name=True` 是什么意思？**

A: 允许同时用原名和别名赋值。例如 `api_key` 和 `apiKey` 都能识别。

---

## 十一、CLI 命令行接口

### 11.1 Typer CLI 框架

**文件位置：** `ZBot/cli/commands.py`

```python
# 创建 Typer CLI 应用实例
app = typer.Typer(name="ZBot", help="ZBot -- 你的个人 AI 助手", no_args_is_help=True)
console = Console()

# 退出指令集合
EXIT_COMMAND = {"exit", "quit", "/exit", "/quit", ":q", "退出", "再见"}


@app.command()
def onboard():
    """初始化配置文件和工作区。"""
    config_path = get_path_config()
    if config_path.exists():
        if typer.confirm("是否覆盖现有配置？"):
            config = Config()
            save_config(config)
        else:
            config = load_config(config_path=config_path)
            save_config(config)
    else:
        config = Config()
        save_config(config)

    ensure_workspace_dirs(workspace=config.workspace_path)


@app.command()
def agent(
    message: Optional[str] = typer.Option(None, "--message", "-m", help="发送给智能体的单次消息"),
    session_id: str = typer.Option("default", "--session", "-s", help="会话 ID"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="是否按 Markdown 渲染回复"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="是否显示调试日志"),
):
    """启动与 ZBot 的对话。"""
    # ...
```

### 11.2 交互模式实现

```python
def _init_prompt_session() -> None:
    """初始化交互式输入会话。"""
    global _PROMPT_SESSION
    history_file = get_cli_history_path()
    ensure_dir(history_file.parent)

    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),  # 文件持久化的输入历史
        multiline=False,                         # 单行输入模式
    )


async def _read_interactive_input_async() -> str:
    """异步读取用户输入。"""
    with patch_stdout():  # 修复异步输出与终端输入的冲突
        return await _PROMPT_SESSION.prompt_async(HTML("<b fg='ansiblue'>你：</b> "))


async def run_interactive() -> None:
    """持续读取用户输入 → 发送给 AI → 打印回复。"""
    while True:
        user_input = await _read_interactive_input_async()
        command = user_input.strip()

        if not command:
            continue
        if _is_exit_command(command):
            break

        with _thinking_ctx():  # 显示思考状态
            response = await agent_loop.process_direct(
                command, session_id, on_progress=_cli_progress
            )

        _print_agent_response(response, render_markdown=markdown)
```

### 11.3 思考状态显示

```python
def _thinking_ctx():
    """返回思考状态上下文。"""
    return console.status("[bold green] 🤖 ZBot 正在思考...[/bold green]", spinner="dots")


async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
    """进度回调函数：在 CLI 中显示工具调用进度。"""
    prefix = "正在调用工具：" if tool_hint else "进度："
    console.print(f"[bold green]↳ {prefix}{content}[/bold green]")
```

### 11.4 面试问答

**Q: 为什么用 prompt_toolkit 而不是 input()？**

A:

1. **历史记录**：上下键翻阅之前输入的内容
2. **异步支持**：`prompt_async()` 不会阻塞事件循环
3. **富文本提示**：支持彩色、加粗等格式
4. **更好的编辑体验**：支持 Emacs/Vi 快捷键

**Q: patch_stdout() 的作用是什么？**

A: 修复异步输出与终端输入的冲突。当 AI 在思考过程中输出进度信息时，不会干扰用户正在输入的内容，而是显示在输入行上方。

**Q: 为什么需要 _flush_pending_tty_input()？**

A: 在某些情况下（如信号中断后），终端输入缓冲区中可能残留未处理的字符。使用 `select` + `os.read` 手动读取并丢弃，防止这些残留字符影响后续输入。

---

## 十二、设计模式总结

### 12.1 适配器模式

**应用场景：** MCPToolWrapper

将 MCP 工具适配为框架原生 Tool 接口：

```python
class MCPToolWrapper(Tool):
    def __init__(self, session: ClientSession, server_name: str, tool_def):
        self._name = f"mcp_{server_name}_{tool_def.name}"  # 包装后的唯一名称
        self._session = session
        self._tool_def = tool_def

    async def execute(self, **kwargs) -> str:
        # 调用 MCP 工具
        result = await self._session.call_tool(self._tool_def.name, arguments=kwargs)
        return str(result.content)
```

### 12.2 模板方法模式

**应用场景：** Tool 基类

基类定义流程，子类实现具体逻辑：

```python
class Tool(ABC):
    # 基类实现的方法
    def cast_params(self, params): ...
    def validate_params(self, params): ...
    def to_schema(self): ...

    # 子类必须实现的抽象方法
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def description(self) -> str: ...
    @abstractmethod
    def parameters(self) -> dict: ...
    @abstractmethod
    async def execute(self, **kwargs) -> str: ...
```

### 12.3 注册中心模式

**应用场景：** ToolRegistry

统一管理工具的注册和执行：

```python
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool): ...
    def get(self, name: str): ...
    def get_definitions(self): ...
    async def execute(self, name: str, params: dict): ...
```

### 12.4 懒加载模式

**应用场景：** MCP 连接

只在首次需要时建立连接：

```python
async def _connect_mcp(self) -> None:
    # 如果已经连接、正在连接、或者没有配置 MCP，则直接返回
    if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
        return

    self._mcp_connecting = True
    try:
        self._mcp_stack = AsyncExitStack()
        await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
        self._mcp_connected = True
    finally:
        self._mcp_connecting = False
```

### 12.5 后台任务模式

**应用场景：** 记忆归档

使用 `asyncio.create_task()` 异步执行：

```python
def _schedule_consolidation(self, session: Session) -> None:
    # 标记为正在归档
    self._consolidating.add(session.key)

    # 创建后台任务
    task = asyncio.create_task(self._run_consolidation(session))

    # 跟踪任务
    self._consolidation_tasks.add(task)
    task.add_done_callback(self._consolidation_tasks.discard)
```

### 12.6 策略模式

**应用场景：** LLM 提供商选择

根据配置动态选择提供商：

```python
def get_provider(self, model: str | None = None):
    if self.provider != "auto":
        # 强制指定提供商
        return forced_config, forced_name, is_gateway

    if find_gateway(model_prefix):
        # 网关模式
        return gateway_config, gateway_name, True

    if find_by_model(model):
        # 标准厂商
        return std_config, std_name, False
```

---

## 十三、面试高频问题

### Q1: 请介绍一下 ZBot 项目的整体架构

**回答要点：**

ZBot 是一个 AI 助手框架，采用分层架构设计：

1. **CLI 层**：使用 Typer 框架实现命令行接口，支持单次模式和交互模式
2. **Agent 层**：核心是 AgentLoop 类，负责模型-工具循环、上下文管理、记忆归档
3. **工具层**：基于抽象基类 Tool 的可扩展工具系统，包含文件、Shell、Web、Cron 等工具
4. **提供商层**：通过 LiteLLM 统一调用多种 LLM API，支持 OpenRouter、DeepSeek 等
5. **持久化层**：JSONL 格式的会话存储，Markdown 格式的长期记忆

**核心流程：** 用户消息 → 构建上下文 → 调用模型 → [工具调用] → 返回回复

---

### Q2: AgentLoop 的核心循环是如何工作的？

**回答要点：**

`_run_agent_loop` 是核心方法，执行流程：

1. **调用大模型**：发送消息历史和工具定义
2. **判断响应类型**：
   - 有工具调用：执行工具，将结果写回消息链，继续循环
   - 无工具调用：返回最终回复，结束循环
3. **安全保护**：设置 `max_iterations` 防止死循环

```python
for _ in range(self.max_iterations):
    response = await self.provider.chat(messages, tools=...)

    if response.has_tool_calls:
        for tool_call in response.tool_calls:
            result = await self.tools.execute(tool_call.name, tool_call.arguments)
            self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
        continue

    return response.content  # 最终回复
```

---

### Q3: 工具系统是如何设计的？

**回答要点：**

采用**抽象基类 + 注册中心**的设计：

1. **Tool 基类**：定义 name、description、parameters、execute 四个核心属性/方法
2. **参数处理**：基类提供 cast_params（类型转换）和 validate_params（参数校验）
3. **ToolRegistry**：统一管理工具注册、获取定义、执行入口

**执行流程：**

```
ToolRegistry.execute(name, params)
    → tool.cast_params(params)      # 类型转换
    → tool.validate_params(params)  # 参数校验
    → tool.execute(**params)        # 执行工具
    → 错误包装返回
```

**安全机制（Shell 工具为例）：**

- 黑名单：阻止 rm -rf、shutdown 等危险命令
- 白名单：可选，只允许特定命令
- 路径限制：阻止访问工作区外的路径

---

### Q4: 长期记忆是如何实现的？

**回答要点：**

维护两个文件：

- **MEMORY.md**：长期记忆，注入到 system prompt，持续更新
- **HISTORY.md**：历史归档，只追加不修改

**归档流程：**

1. 当未归档消息达到阈值（默认 50 条）时触发
2. 后台异步执行，不阻塞主流程
3. 调用大模型压缩历史，生成摘要
4. 使用 `save_memory` 工具返回结构化结果

**并发控制：**

- `_consolidating` 集合标记正在归档的会话
- 每个会话有独立的异步锁

---

### Q5: 如何支持多种 LLM 提供商？

**回答要点：**

采用**抽象基类 + LiteLLM**的设计：

1. **LLMProvider 抽象基类**：定义统一的 chat 方法
2. **LiteLLMProvider 实现**：通过 LiteLLM 库调用多种 API
3. **提供商注册表**：根据模型名称自动匹配提供商

**提示词缓存：**

- 支持 Anthropic/OpenRouter 的缓存功能
- 对 system 消息和 tools 定义注入 `cache_control` 标记
- 使用 ephemeral（短时缓存，约 5 分钟）

---

### Q6: 会话持久化是如何实现的？

**回答要点：**

采用 **JSONL 格式 + 内存缓存**：

**文件格式：**

```
Line 1: {"_type": "metadata", "key": "cli:default", ...}
Line 2: {"role": "user", "content": "你好"}
Line 3: {"role": "assistant", "content": "你好！有什么可以帮你的？"}
```

**为什么用 JSONL：**

1. 追加友好：新消息只需追加一行
2. 内存效率：可逐行读取
3. 容错性好：某行损坏不影响其他行

**缓存机制：**

```python
def get_or_create(self, key: str) -> Session:
    session = self._cache.get(key)
    if session is None:
        session = self._load(key) or Session(key=key)
        self._cache[key] = session
    return session
```

---

### Q7: 技能系统是如何工作的？

**回答要点：**

技能是一种轻量级的能力扩展机制：

**技能格式（SKILL.md）：**

```yaml
---
name: web_search
description: 网络搜索工具
requires:
  bins: [curl, jq]
  env: [API_KEY]
always: true
---
技能正文内容...
```

**发现机制：**

- 扫描内置目录和工作区目录
- 工作区技能可覆盖内置技能

**依赖检查：**

- 命令行工具：通过 `shutil.which()` 检查
- 环境变量：通过 `os.environ` 检查

---

### Q8: 项目中使用了哪些设计模式？

**回答要点：**

1. **适配器模式**：MCPToolWrapper 将 MCP 工具适配为原生 Tool 接口
2. **模板方法模式**：Tool 基类定义流程，子类实现具体逻辑
3. **注册中心模式**：ToolRegistry 统一管理工具
4. **懒加载模式**：MCP 连接只在首次需要时建立
5. **后台任务模式**：记忆归档使用 `asyncio.create_task()` 异步执行
6. **策略模式**：根据配置动态选择 LLM 提供商

---

### Q9: Shell 工具的安全机制有哪些？

**回答要点：**

三层安全防护：

1. **黑名单检查**：

   ```python
   deny_patterns = [
       r"\brm\s+-[rf]{1,2}\b",     # rm -rf
       r"\b(shutdown|reboot)\b",   # 关机命令
       r":\(\)\s*\{.*\};\s*:",     # Fork bomb
   ]
   ```
2. **白名单检查**（可选）：只允许特定命令
3. **路径限制**：

   - 检查 `../` 和 `..\\` 路径穿越
   - 验证访问路径是否在工作区内
4. **执行限制**：

   - 超时限制（默认 60 秒，最大 600 秒）
   - 输出截断（最大 10KB）

---

### Q10: 如何处理异步编程中的并发问题？

**回答要点：**

1. **异步锁（asyncio.Lock）**：

   ```python
   async with self._get_consolidation_lock(session.key):
       await self._consolidate_memory(session)
   ```
2. **状态标记**：

   ```python
   self._consolidating.add(session.key)  # 标记正在归档
   # ... 归档操作 ...
   self._consolidating.discard(session.key)  # 清除标记
   ```
3. **任务跟踪**：

   ```python
   task = asyncio.create_task(self._run_consolidation(session))
   self._consolidation_tasks.add(task)
   task.add_done_callback(self._consolidation_tasks.discard)
   ```

---

### Q11: 上下文构建的顺序为什么这样设计？

**回答要点：**

System Prompt 的构建顺序：

1. **身份与运行环境**：让模型先理解"我是谁、当前环境是什么"
2. **引导文件**：让模型理解"项目规则"
3. **长期记忆**：让模型理解"历史侧写"
4. **技能**：让模型理解"可用能力"

这样模型会先建立身份认知，再学习具体规则，最后了解可用能力。

---

### Q12: 为什么运行时上下文要剥离？

**回答要点：**

运行时信息（如当前时间）只对当前轮推理有意义：

1. **避免污染历史**：长期保留在 session 里会污染历史
2. **节省存储**：运行时信息每轮都变，长期保存浪费空间
3. **避免过时**：下次对话时这些信息已经过时了

剥离方法：

```python
def _strip_runtime_context(content: Any) -> str | None:
    if content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
        parts = content.split("\n\n", 1)
        return parts[1] if len(parts) > 1 else None
    return content
```

---

## 附录：关键代码速查

### A. 工具基类完整实现

```python
class Tool(ABC):
    _TYPE_MAP = {
        "string": str, "integer": int, "number": (int, float),
        "boolean": bool, "array": list, "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str: pass

    @property
    @abstractmethod
    def description(self) -> str: pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]: pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str: pass

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
```

### B. 消息链结构

```python
messages = [
    {"role": "system", "content": "完整 system prompt"},
    {"role": "user", "content": "历史用户消息"},
    {"role": "assistant", "content": "历史助手回复", "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "xxx", "name": "web_search", "content": "结果"},
    {"role": "user", "content": "当前用户消息"},
]
```

### C. 工具调用格式

```python
tool_call = {
    "id": "call_abc123",
    "type": "function",
    "function": {
        "name": "web_search",
        "arguments": '{"query": "Python 教程", "count": 5}'
    }
}
```

### D. 正则表达式速查

```python
# 思考块匹配
_THINK_BLOCK_RE = re.compile(r"<thinking>[\s\S]*?</thinking>", re.IGNORECASE)

# Frontmatter 匹配
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)

# 危险命令匹配
r"\brm\s+-[rf]{1,2}\b"  # rm -rf
r"\b(shutdown|reboot)\b"  # 关机命令
```

---

## 十四、深度面试问题（进阶篇）

本章节包含更多面试官可能会深入追问的问题，涵盖架构设计、性能优化、安全性、扩展性等多个维度。

---

### Q13: 如果让你重新设计这个项目，你会做哪些改进？

**回答要点：**

这是一个考察架构思维和反思能力的问题，可以从以下几个维度回答：

**1. 架构层面：**

```
当前设计 → 改进方向
─────────────────────────────────────────────────
单体 AgentLoop → 拆分为更细粒度的组件
   - MessageHandler：专门处理消息解析和路由
   - ToolOrchestrator：专门管理工具调用流程
   - MemoryManager：专门管理记忆和归档
```

**改进代码示例：**

```python
# 当前设计：AgentLoop 承担了太多职责
class AgentLoop:
    def process_message(self): ...
    def run_agent_loop(self): ...
    def consolidate_memory(self): ...
    def connect_mcp(self): ...
    def save_turn(self): ...

# 改进设计：职责分离
class AgentOrchestrator:
    """编排器：协调各个组件"""
    def __init__(self):
        self.message_handler = MessageHandler()
        self.tool_orchestrator = ToolOrchestrator()
        self.memory_manager = MemoryManager()
        self.mcp_connector = MCPConnector()

class MessageHandler:
    """专门处理消息解析和路由"""
    def parse(self, content: str) -> ParsedMessage: ...
    def route(self, message: ParsedMessage) -> Route: ...

class ToolOrchestrator:
    """专门管理工具调用流程"""
    def plan(self, tool_calls: list) -> ExecutionPlan: ...
    def execute(self, plan: ExecutionPlan) -> list[ToolResult]: ...
```

**2. 性能层面：**

```python
# 当前问题：每次都完整构建 system prompt
def build_system_prompt(self):
    parts = [self._identity_prompt()]
    parts.append(self._bootstrap_prompt())  # 每次都读文件
    parts.append(self.memory.get_memory_context())  # 每次都读文件
    # ...

# 改进：增量更新 + 缓存
class CachedContextBuilder:
    def __init__(self):
        self._identity_cache: str | None = None
        self._bootstrap_cache: str | None = None
        self._bootstrap_mtime: float = 0
        self._memory_cache: str | None = None
        self._memory_mtime: float = 0

    def build_system_prompt(self):
        # 身份信息基本不变，直接缓存
        if self._identity_cache is None:
            self._identity_cache = self._identity_prompt()

        # 引导文件检查修改时间，按需更新
        if self._should_refresh_bootstrap():
            self._bootstrap_cache = self._bootstrap_prompt()

        # 记忆文件检查修改时间
        if self._should_refresh_memory():
            self._memory_cache = self.memory.get_memory_context()

        return self._assemble_prompt()
```

**3. 扩展性层面：**

```python
# 当前问题：工具硬编码注册
def _register_default_tools(self):
    for tool_cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
        self.tools.register(tool_cls(...))
    self.tools.register(ExecTool(...))
    # ...

# 改进：插件化架构
class ToolPluginManager:
    """工具插件管理器"""

    def __init__(self, plugin_dir: Path):
        self.plugin_dir = plugin_dir
        self._plugins: dict[str, type[Tool]] = {}

    def discover(self):
        """自动发现插件目录下的工具"""
        for plugin_path in self.plugin_dir.glob("**/plugin.py"):
            module = importlib.import_module(plugin_path.stem)
            for name, obj in inspect.getmembers(module):
                if isinstance(obj, type) and issubclass(obj, Tool) and obj is not Tool:
                    self._plugins[obj.name] = obj

    def register_all(self, registry: ToolRegistry, **kwargs):
        """注册所有发现的工具"""
        for name, tool_cls in self._plugins.items():
            registry.register(tool_cls(**kwargs))
```

**4. 可观测性层面：**

```python
# 当前问题：日志分散，难以追踪
logger.info("调用工具：{}", tool_call.name)
logger.debug("模型回复: {}", response.content[:100])

# 改进：结构化日志 + 链路追踪
import structlog

class AgentTracer:
    """Agent 执行链路追踪"""

    def __init__(self):
        self.logger = structlog.get_logger()
        self.trace_id: str = ""
        self.span_id: str = ""

    def start_trace(self, user_message: str) -> str:
        self.trace_id = str(uuid.uuid4())
        self.logger.info("trace_started", trace_id=self.trace_id, message=user_message[:100])
        return self.trace_id

    def start_span(self, operation: str) -> str:
        span_id = str(uuid.uuid4())
        self.logger.info("span_started", trace_id=self.trace_id, span_id=span_id, operation=operation)
        return span_id

    def log_tool_call(self, tool_name: str, arguments: dict, result: str):
        self.logger.info(
            "tool_called",
            trace_id=self.trace_id,
            tool=tool_name,
            arguments=arguments,
            result_length=len(result),
            duration_ms=self._get_duration()
        )
```

**总结：**

| 维度     | 当前设计                  | 改进方向              |
| -------- | ------------------------- | --------------------- |
| 架构     | 单一 AgentLoop 承担多职责 | 职责分离，组件化设计  |
| 性能     | 每次完整构建 prompt       | 增量更新 + 缓存       |
| 扩展性   | 工具硬编码注册            | 插件化架构，自动发现  |
| 可观测性 | 日志分散                  | 结构化日志 + 链路追踪 |

---

### Q14: 工具调用失败时如何处理？有没有重试机制？

**回答要点：**

这是一个考察系统健壮性和错误处理能力的问题。

**1. 当前的错误处理机制：**

```python
# ToolRegistry.execute 方法
async def execute(self, name: str, params: dict[str, Any]) -> str:
    tool = self._tools.get(name)
    if tool is None:
        available = "、".join(self._tools)
        return f"错误：找不到工具"{name}"。当前可用工具：{available}"

    try:
        # 参数转换和校验
        cast_params = tool.cast_params(params)
        errors = tool.validate_params(cast_params)
        if errors:
            return f"错误：工具"{name}"的参数不合法：{'；'.join(errors)}{_RETRY_HINT}"

        # 执行工具
        result = await tool.execute(**cast_params)

        # 工具返回错误
        if isinstance(result, str) and result.startswith("错误："):
            return result + _RETRY_HINT

        return result
    except Exception as exc:
        return f"错误：执行工具"{name}"时发生异常：{exc}{_RETRY_HINT}"

# 重试提示
_RETRY_HINT = "\n\n[工具执行失败。请分析错误原因，然后继续尝试其他方法完成任务，不要停下来。]"
```

**2. 设计理念：让模型自己决定是否重试**

```
传统做法：代码层面自动重试
─────────────────────────────
try:
    result = await tool.execute()
except Exception:
    await asyncio.sleep(1)
    result = await tool.execute()  # 自动重试

ZBot 做法：返回错误信息，让模型决策
─────────────────────────────────────
1. 工具执行失败 → 返回带重试提示的错误信息
2. 模型看到错误 → 分析原因 → 决定是否重试/换方法
3. 模型可能：
   - 重试同一个工具（修正参数）
   - 换一个工具（如 read_file 失败，改用 exec cat）
   - 放弃并告知用户
```

**3. 为什么不让代码自动重试？**

```python
# 场景1：参数错误 - 重试无意义
read_file(path="不存在的文件.txt")
# 错误：文件不存在
# 模型应该：修正路径，而不是盲目重试

# 场景2：权限错误 - 需要用户干预
exec(command="rm -rf /")
# 错误：命令被安全策略拦截
# 模型应该：告知用户需要权限，而不是重试

# 场景3：网络错误 - 可以重试
web_search(query="Python 教程")
# 错误：网络超时
# 模型应该：等待后重试，或告知用户稍后再试
```

**4. 如果要增加自动重试机制，可以这样设计：**

```python
@dataclass
class RetryPolicy:
    """重试策略"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    retryable_errors: set[str] = field(default_factory=lambda: {
        "timeout", "network_error", "rate_limit"
    })


class ToolExecutorWithRetry:
    """带重试机制的工具执行器"""

    def __init__(self, registry: ToolRegistry, policy: RetryPolicy):
        self.registry = registry
        self.policy = policy

    async def execute_with_retry(
        self,
        name: str,
        params: dict[str, Any],
        policy: RetryPolicy | None = None
    ) -> str:
        policy = policy or self.policy
        last_error: str = ""

        for attempt in range(policy.max_retries + 1):
            result = await self.registry.execute(name, params)

            # 成功则返回
            if not result.startswith("错误："):
                return result

            # 检查是否可重试的错误
            error_type = self._classify_error(result)
            if error_type not in policy.retryable_errors:
                return result  # 不可重试，直接返回

            last_error = result

            # 计算延迟（指数退避）
            if attempt < policy.max_retries:
                delay = min(
                    policy.base_delay * (policy.exponential_base ** attempt),
                    policy.max_delay
                )
                await asyncio.sleep(delay)

        return f"{last_error}\n[已重试 {policy.max_retries} 次，仍然失败]"

    def _classify_error(self, error_msg: str) -> str:
        """分类错误类型"""
        if "超时" in error_msg:
            return "timeout"
        if "网络" in error_msg or "connection" in error_msg.lower():
            return "network_error"
        if "rate limit" in error_msg.lower() or "频率限制" in error_msg:
            return "rate_limit"
        return "unknown"
```

**5. 面试总结：**

| 问题                   | 回答要点                          |
| ---------------------- | --------------------------------- |
| 当前有重试吗？         | 没有，返回错误让模型决策          |
| 为什么这样设计？       | 不同错误需要不同处理，模型更智能  |
| 什么场景适合自动重试？ | 网络超时、限流等临时性错误        |
| 如何实现？             | RetryPolicy + 指数退避 + 错误分类 |

---

### Q15: 如何保证工具调用的安全性？如果模型要执行 rm -rf 怎么办？

**回答要点：**

这是一个考察安全意识和防护设计的问题。

**1. 多层安全防护架构：**

```
用户输入 → AgentLoop → ToolRegistry → ExecTool
                              │
                              ▼
                    ┌─────────────────────┐
                    │   第一层：黑名单检查  │
                    │   阻止已知危险命令    │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   第二层：白名单检查  │
                    │   只允许特定命令(可选)│
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   第三层：路径限制    │
                    │   阻止访问工作区外    │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   第四层：执行限制    │
                    │   超时/输出截断      │
                    └─────────────────────┘
```

**2. 黑名单实现详解：**

```python
class ExecTool(Tool):
    def __init__(self, ...):
        # 危险命令黑名单
        self.deny_patterns = [
            # 文件删除类
            r"\brm\s+-[rf]{1,2}\b",           # rm -rf / rm -fr
            r"\bdel\s+/[fq]\b",               # del /f /q (Windows)
            r"\brmdir\s+/s\b",                # rmdir /s (Windows)

            # 磁盘操作类
            r"(?:^|[;&|]\s*)format\b",        # format
            r"\b(mkfs|diskpart)\b",           # 磁盘分区工具
            r"\bdd\s+if=",                    # dd if= (磁盘复制)
            r">\s*/dev/sd",                   # 写入磁盘设备

            # 系统控制类
            r"\b(shutdown|reboot|poweroff)\b", # 关机命令
            r"\b(init\s+[06])\b",             # init 0/6

            # 权限提升类
            r"\b(sudo|su|doas)\b",            # 权限提升
            r"\b(chmod|chown)\b",             # 权限修改

            # 网络危险类
            r">\s*/dev/tcp/",                 # bash 反弹 shell
            r">\s*/dev/udp/",                 # UDP 反弹

            # Fork bomb
            r":\(\)\s*\{.*\};\s*:",           # :(){ :|:& };:
        ]

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """执行前的安全检查"""
        cmd = command.strip()
        lower = cmd.lower()

        # 黑名单检查
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "错误：命令被安全策略拦截，检测到高风险模式。"

        return None
```

**3. 如果模型尝试执行 rm -rf：**

```
场景：模型生成工具调用
─────────────────────────────────────────
{
    "name": "exec",
    "arguments": {"command": "rm -rf /"}
}

执行流程：
─────────────────────────────────────────
1. ToolRegistry.execute("exec", {"command": "rm -rf /"})
2. ExecTool._guard_command("rm -rf /", cwd)
3. 正则匹配：r"\brm\s+-[rf]{1,2}\b" 匹配成功
4. 返回："错误：命令被安全策略拦截，检测到高风险模式。"
5. 模型收到错误，无法执行

模型看到的响应：
─────────────────────────────────────────
"错误：命令被安全策略拦截，检测到高风险模式。

[工具执行失败。请分析错误原因，然后继续尝试其他方法完成任务，不要停下来。]"

模型可能的反应：
─────────────────────────────────────────
1. 告知用户：这个命令太危险，无法执行
2. 提供替代方案：可以逐个删除文件
3. 询问用户：是否确定要删除？请手动执行
```

**4. 白名单模式（更严格）：**

```python
class StrictExecTool(ExecTool):
    """严格模式的执行工具：只允许白名单命令"""

    def __init__(self, ...):
        super().__init__(...)
        # 白名单：只允许这些命令
        self.allow_patterns = [
            r"\bls\b",           # 列出文件
            r"\bcat\s+",         # 查看文件
            r"\bgit\s+",         # Git 操作
            r"\bnpm\s+",         # NPM 操作
            r"\bpython\s+",      # Python 执行
            r"\bpip\s+",         # Pip 安装
        ]

    def _guard_command(self, command: str, cwd: str) -> str | None:
        # 先检查黑名单
        result = super()._guard_command(command, cwd)
        if result:
            return result

        # 再检查白名单
        lower = command.strip().lower()
        if not any(re.search(pattern, lower) for pattern in self.allow_patterns):
            return "错误：命令被安全策略拦截，不在允许执行的白名单中。"

        return None
```

**5. 路径穿越防护：**

```python
def _guard_command(self, command: str, cwd: str) -> str | None:
    # ... 黑名单检查 ...

    # 路径限制检查
    if self.restrict_to_workspace:
        # 检查路径穿越
        if "..\\" in command or "../" in command:
            return "错误：命令被安全策略拦截，检测到路径穿越。"

        # 检查绝对路径是否越界
        for raw in self._extract_absolute_paths(command):
            try:
                path = Path(raw.strip()).expanduser().resolve()
                cwd_path = Path(cwd).resolve()

                # path 必须是 cwd_path 的子路径
                if path.is_absolute() and (
                    cwd_path not in path.parents and path != cwd_path
                ):
                    return "错误：命令被安全策略拦截，访问路径超出了当前工作目录。"
            except Exception:
                continue

    return None

@staticmethod
def _extract_absolute_paths(command: str) -> list[str]:
    """从命令中提取绝对路径"""
    # Windows 风格：C:\path\to\file
    win_paths = re.findall(r"[A-Za-z]:\\[^\s\"\'|><;]+", command)
    # POSIX 风格：/path/to/file
    posix_paths = re.findall(r"(?:^|[\s|>\'\"])(/[^\s\"\'>;|<]+)", command)
    # 用户目录：~/path
    home_paths = re.findall(r"(?:^|[\s|>\'\"])(~[^\s\"\'>;|<]*)", command)

    return win_paths + posix_paths + home_paths
```

**6. 面试总结：**

| 安全层   | 作用             | 示例                        |
| -------- | ---------------- | --------------------------- |
| 黑名单   | 阻止已知危险命令 | rm -rf, shutdown, fork bomb |
| 白名单   | 只允许特定命令   | ls, cat, git, npm           |
| 路径限制 | 阻止访问工作区外 | ../, /etc/passwd            |
| 执行限制 | 防止资源滥用     | 超时 60s，输出 10KB         |

---

### Q16: 长期记忆的归档策略是什么？为什么这样设计？

**回答要点：**

这是一个考察系统设计和性能优化能力的问题。

**1. 归档策略概述：**

```
记忆窗口策略
─────────────────────────────────────────
                    记忆窗口 (memory_window = 50)
                    ├────────────────────────────┤
[已归档消息] ────────┤                            ├────── [最新消息]
                    │      保留最近 25 条         │
                    └────────────────────────────┘
                              ↓
                        归档前 25 条
```

**2. 归档范围计算：**

```python
@staticmethod
def _messages_to_archive(
    session: Session,
    archive_all: bool,
    memory_window: int,
) -> tuple[list[dict[str, Any]], int]:
    """确定本次要归档的消息区间。"""
    if archive_all:
        # 强制归档所有消息（/new 命令）
        return list(session.messages), 0

    # 默认保留最近一半窗口的消息
    keep_count = max(1, memory_window // 2)  # 保留 25 条

    if len(session.messages) <= keep_count:
        # 消息总数不超过保留数量，无需归档
        return [], keep_count

    start = session.last_consolidated  # 从上次归档位置开始
    end = len(session.messages) - keep_count  # 到倒数第 25 条

    if end <= start:
        return [], keep_count

    # 返回要归档的消息片段
    return session.messages[start:end], keep_count
```

**3. 为什么保留一半而不是全部归档？**

```
场景分析：假设 memory_window = 50
─────────────────────────────────────────

方案A：全部归档
─────────────────────────────────────────
优点：节省上下文空间
缺点：
  1. 下一轮模型看不到任何历史，可能重复问用户
  2. 对话连贯性差，用户体验不好
  3. 如果归档失败，历史完全丢失

方案B：保留最近一半（ZBot 采用）
─────────────────────────────────────────
优点：
  1. 下一轮模型还能看到最近 25 条消息
  2. 对话连贯性好
  3. 即使归档失败，最近的消息还在
缺点：
  1. 上下文略长，但可控

方案C：保留最近全部
─────────────────────────────────────────
优点：对话连贯性最好
缺点：
  1. 上下文无限增长
  2. Token 消耗大
  3. 可能超出模型上下文限制
```

**4. 归档触发条件：**

```python
def _schedule_consolidation(self, session: Session) -> None:
    """当未归档消息达到阈值时，安排后台归档任务。"""
    # 计算未归档的消息数量
    unconsolidated = len(session.messages) - session.last_consolidated

    # 触发条件：未归档消息 >= memory_window
    if unconsolidated < self.memory_window:
        return  # 不足阈值，不触发

    # 检查是否已在归档中
    if session.key in self._consolidating:
        return  # 避免重复归档

    # 创建后台任务
    self._consolidating.add(session.key)
    task = asyncio.create_task(self._run_consolidation(session))
    self._consolidation_tasks.add(task)
```

**5. 归档流程详解：**

```python
async def consolidate(self, session: Session, provider: LLMProvider, model: str, ...) -> bool:
    """
    归档流程：
    1. 确定归档范围
    2. 构造归档提示词
    3. 调用大模型压缩
    4. 处理结果
    """
    # Step 1: 确定归档范围
    messages, keep_count = self._messages_to_archive(session, archive_all, memory_window)
    if not messages:
        return True

    # Step 2: 构造提示词
    current_memory = self.read_long_term()
    prompt = self._build_prompt(current_memory, messages)

    # Step 3: 调用大模型
    response = await provider.chat(
        messages=[
            {"role": "system", "content": "你负责压缩对话历史，且必须调用 save_memory 工具返回结构化结果。"},
            {"role": "user", "content": prompt},
        ],
        tools=_SAVE_MEMORY_TOOL,
        model=model,
    )

    # Step 4: 处理结果
    args = self._normalize_tool_args(response.tool_calls[0].arguments)

    # 追加到 HISTORY.md
    history_entry = args.get("history_entry")
    if history_entry:
        self.append_history(history_entry)

    # 更新 MEMORY.md
    memory_update = args.get("memory_update")
    if memory_update and memory_update != current_memory:
        self.write_long_term(memory_update)

    # 更新归档标记
    session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count

    return True
```

**6. 归档提示词结构：**

```python
def _build_prompt(self, current_memory: str, messages: list[dict[str, Any]]) -> str:
    """把长期记忆和待归档对话整理成提示词。"""
    transcript = "\n".join(self._format_messages(messages))
    return (
        "请整理下面这些旧对话，把需要长期保留的信息写入 MEMORY.md，"
        "并把本段历史压缩成一条可检索的摘要。\n\n"
        "## 当前 MEMORY.md\n"
        f"{current_memory or '(当前为空)'}\n\n"
        "## 待归档对话\n"
        f"{transcript}"
    )

@staticmethod
def _format_messages(messages: list[dict[str, Any]]) -> list[str]:
    """格式化消息列表。"""
    lines = []
    for message in messages:
        content = message.get("content")
        if not content:
            continue
        tools = message.get("tools_used") or []
        tool_suffix = f" [使用工具: {', '.join(tools)}]" if tools else ""
        timestamp = str(message.get("timestamp", "?"))[:16]
        lines.append(f"[{timestamp}] {message['role'].upper()}{tool_suffix}: {content}")
    return lines
```

**7. 面试总结：**

| 问题             | 回答要点                               |
| ---------------- | -------------------------------------- |
| 归档策略是什么？ | 保留最近一半窗口，归档更早的消息       |
| 为什么保留一半？ | 保证对话连贯性，避免归档失败丢失历史   |
| 触发条件？       | 未归档消息 >= memory_window（默认 50） |
| 为什么后台执行？ | 不阻塞主流程，用户体验好               |
| 并发如何处理？   | 状态标记 + 异步锁                      |

---

### Q17: 如何处理多轮对话中的上下文长度限制？

**回答要点：**

这是一个考察性能优化和资源管理能力的问题。

**1. 问题分析：**

```
上下文长度问题
─────────────────────────────────────────
用户消息1 → 助手回复1 → 用户消息2 → 助手回复2 → ... → 用户消息N
    │                                                        │
    └────────────────────────────────────────────────────────┘
                              ↓
                    上下文越来越长，可能超出模型限制

例如：Claude 3.5 Sonnet 上下文限制 200K tokens
     - 每轮对话约 1000-5000 tokens
     - 100 轮对话可能达到 100K-500K tokens
     - 超出限制会报错或截断
```

**2. ZBot 的多层解决方案：**

```
解决方案架构
─────────────────────────────────────────
                    ┌─────────────────────┐
                    │  Layer 1: 记忆窗口   │
                    │  限制历史消息数量    │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Layer 2: 长期记忆   │
                    │  压缩旧消息到文件    │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Layer 3: 工具结果截断│
                    │  限制单条消息大小    │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │  Layer 4: 提示词缓存 │
                    │  减少重复传输        │
                    └─────────────────────┘
```

**3. Layer 1: 记忆窗口：**

```python
class AgentLoop:
    def __init__(self, memory_window: int = 50, ...):
        self.memory_window = memory_window  # 默认保留 50 条历史消息

    async def _run_turn(self, session: Session, ...):
        # 从会话中获取历史消息（最多 memory_window 条）
        history = session.get_history(max_messages=self.memory_window)

        # 构造消息链
        initial_messages = self.context.build_messages(
            history=history,          # 限制后的历史
            current_message=content,
        )
```

**4. Layer 2: 长期记忆归档：**

```python
# 当未归档消息达到阈值时，自动归档
def _schedule_consolidation(self, session: Session):
    unconsolidated = len(session.messages) - session.last_consolidated
    if unconsolidated >= self.memory_window:
        # 后台归档，压缩旧消息
        asyncio.create_task(self._run_consolidation(session))

# 归档后，历史从 last_consolidated 开始
def get_history(self, max_messages: int = 500) -> list[dict]:
    messages = self.messages[self.last_consolidated :][-max_messages:]
    # ...
```

**5. Layer 3: 工具结果截断：**

```python
class AgentLoop:
    _TOOL_RESULT_MAX_CHARS = 2000  # 工具结果最大 2000 字符

    def _save_turn(self, session: Session, messages: list, skip: int, tools_used: list):
        for entry in messages[skip:]:
            role = entry.get("role")
            content = entry.get("content")

            # tool 结果截断
            if role == "tool" and isinstance(content, str):
                if len(content) > self._TOOL_RESULT_MAX_CHARS:
                    entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n……（内容已截断）"

# ExecTool 也有输出限制
class ExecTool(Tool):
    _MAX_OUTPUT = 10_000  # 最大输出 10KB

    async def execute(self, command: str, ...):
        # ... 执行命令 ...

        # 输出过长时截断中间部分
        if len(result) > self._MAX_OUTPUT:
            half = self._MAX_OUTPUT // 2
            result = (
                result[:half]
                + f"\n\n......（已截断 {len(result) - self._MAX_OUTPUT:,} 个字符）......\n\n"
                + result[-half:]
            )
```

**6. Layer 4: 提示词缓存：**

```python
class LiteLLMProvider(LLMProvider):
    def _apply_cache_control(self, messages, tools):
        """
        对 system 消息和 tools 定义注入缓存标记。
        这样多轮对话中，system prompt 只传输一次。
        """
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                new_content = [{
                    "type": "text",
                    "text": msg["content"],
                    "cache_control": {"type": "ephemeral"}  # 缓存 5 分钟
                }]
                new_messages.append({**msg, "content": new_content})
            else:
                new_messages.append(msg)

        return new_messages, tools
```

**7. 如果要增加 Token 计数和预警：**

```python
import tiktoken

class TokenCounter:
    """Token 计数器"""

    def __init__(self, model: str = "claude-3-5-sonnet-20241022"):
        self.encoding = tiktoken.encoding_for_model(model)
        self.max_tokens = 200_000  # Claude 3.5 Sonnet 上下文限制

    def count(self, text: str) -> int:
        """计算文本的 token 数量"""
        return len(self.encoding.encode(text))

    def count_messages(self, messages: list[dict]) -> int:
        """计算消息链的总 token 数量"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += self.count(part.get("text", ""))
        return total

class ContextManager:
    """上下文管理器：自动处理上下文长度"""

    def __init__(self, max_tokens: int = 180_000, token_counter: TokenCounter = None):
        self.max_tokens = max_tokens  # 留 20K 给输出
        self.counter = token_counter or TokenCounter()

    def truncate_history(
        self,
        messages: list[dict],
        system_prompt: str
    ) -> list[dict]:
        """截断历史消息以适应上下文限制"""
        system_tokens = self.counter.count(system_prompt)
        available = self.max_tokens - system_tokens - 10_000  # 留 10K 给用户消息和输出

        truncated = []
        current_tokens = 0

        # 从最新的消息开始，倒序添加
        for msg in reversed(messages):
            msg_tokens = self.counter.count_messages([msg])
            if current_tokens + msg_tokens > available:
                break
            truncated.insert(0, msg)
            current_tokens += msg_tokens

        return truncated
```

**8. 面试总结：**

| 层级    | 策略       | 效果                                   |
| ------- | ---------- | -------------------------------------- |
| Layer 1 | 记忆窗口   | 限制历史消息数量（默认 50 条）         |
| Layer 2 | 长期记忆   | 压缩旧消息到文件，注入摘要             |
| Layer 3 | 结果截断   | 限制单条消息大小（工具结果 2000 字符） |
| Layer 4 | 提示词缓存 | 减少重复传输，节省 token               |

---

### Q18: MCP 协议是什么？为什么要在项目中支持它？

**回答要点：**

这是一个考察技术视野和扩展性设计的问题。

**1. MCP 协议简介：**

```
MCP (Model Context Protocol)
─────────────────────────────────────────
Anthropic 推出的开放协议，用于连接 AI 助手和外部工具/数据源。

核心概念：
┌─────────────┐     MCP Protocol     ┌─────────────┐
│   AI 助手    │ ◄──────────────────► │  MCP 服务器  │
│  (Client)   │                      │  (Server)   │
└─────────────┘                      └─────────────┘
      │                                    │
      │                                    ▼
      │                           ┌───────────────┐
      │                           │  外部工具/数据  │
      │                           │  - 文件系统    │
      │                           │  - 数据库      │
      │                           │  - API 服务    │
      │                           │  - 搜索引擎    │
      └───────────────────────────┴───────────────┘
```

**2. MCP 的优势：**

```
传统方式：每个工具单独集成
─────────────────────────────────────────
┌─────────┐    ┌─────────┐    ┌─────────┐
│ 工具 A   │    │ 工具 B   │    │ 工具 C   │
│ 自定义API│    │ 自定义API│    │ 自定义API│
└────┬────┘    └────┬────┘    └────┬────┘
     │              │              │
     └──────────────┼──────────────┘
                    ▼
              需要写 3 套集成代码

MCP 方式：统一协议
─────────────────────────────────────────
┌─────────┐    ┌─────────┐    ┌─────────┐
│ MCP 服务器│    │ MCP 服务器│    │ MCP 服务器│
│   A      │    │   B      │    │   C      │
└────┬────┘    └────┬────┘    └────┬────┘
     │              │              │
     └──────────────┼──────────────┘
                    ▼
              只需要实现 MCP Client
```

**3. ZBot 中的 MCP 实现：**

```python
# 支持三种连接方式
class MCPServerConfig(Base):
    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str = ""      # stdio 模式：启动命令
    args: list[str] = []   # stdio 模式：命令参数
    url: str = ""          # sse/http 模式：服务器 URL
    env: dict[str, str] = {}  # 环境变量

# MCP 工具包装器
class MCPToolWrapper(Tool):
    """将 MCP 工具适配为 ZBot 的 Tool 接口"""

    def __init__(self, session: ClientSession, server_name: str, tool_def):
        self._name = f"mcp_{server_name}_{tool_def.name}"  # 唯一名称
        self._session = session
        self._tool_def = tool_def

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._tool_def.description or ""

    @property
    def parameters(self) -> dict:
        return self._tool_def.inputSchema or {}

    async def execute(self, **kwargs) -> str:
        # 调用 MCP 工具
        result = await self._session.call_tool(
            self._tool_def.name,
            arguments=kwargs
        )
        return str(result.content)
```

**4. MCP 连接流程：**

```python
async def connect_mcp_servers(
    mcp_servers: dict[str, MCPServerConfig],
    registry: ToolRegistry,
    stack: AsyncExitStack
) -> None:
    """连接 MCP 服务器并注册工具"""

    for server_name, config in mcp_servers.items():
        if config.type == "stdio":
            # 启动本地子进程
            server = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env,
            )
            session = await stack.enter_async_context(
                stdio_client(server)
            )

        elif config.type == "sse":
            # 连接远程 SSE 服务器
            session = await stack.enter_async_context(
                sse_client(config.url)
            )

        elif config.type == "streamableHttp":
            # HTTP 流式连接
            session = await stack.enter_async_context(
                streamablehttp_client(config.url)
            )

        # 获取工具列表
        tools = await session.list_tools()

        # 注册到工具注册表
        for tool_def in tools.tools:
            wrapper = MCPToolWrapper(session, server_name, tool_def)
            registry.register(wrapper)
```

**5. 懒连接机制：**

```python
class AgentLoop:
    def __init__(self, ...):
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False

    async def _connect_mcp(self) -> None:
        """懒连接：只在首次需要时连接"""
        # 已经连接、正在连接、或没有配置 → 直接返回
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return

        self._mcp_connecting = True
        try:
            self._mcp_stack = AsyncExitStack()
            await connect_mcp_servers(
                self._mcp_servers,
                self.tools,
                self._mcp_stack
            )
            self._mcp_connected = True
        except Exception as exc:
            logger.error("连接 MCP 服务器失败：{}", exc)
        finally:
            self._mcp_connecting = False

    async def process_direct(self, content: str, ...):
        # 在处理消息前连接 MCP
        await self._connect_mcp()
        return await self._process_message(content, ...)
```

**6. MCP 配置示例：**

```json
{
  "tools": {
    "mcp_servers": {
      "filesystem": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"]
      },
      "github": {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
          "GITHUB_TOKEN": "your-token"
        }
      },
      "postgres": {
        "type": "stdio",
        "command": "uvx",
        "args": ["mcp-server-postgres"],
        "env": {
          "DATABASE_URL": "postgresql://user:pass@localhost/db"
        }
      }
    }
  }
}
```

**7. 面试总结：**

| 问题           | 回答要点                                     |
| -------------- | -------------------------------------------- |
| MCP 是什么？   | Anthropic 推出的开放协议，连接 AI 和外部工具 |
| 为什么支持？   | 统一协议，减少集成成本，生态丰富             |
| 支持哪些连接？ | stdio（本地）、sse（远程）、streamableHttp   |
| 如何集成？     | MCPToolWrapper 适配器 + 懒连接               |

---

### Q19: 异步编程在项目中是如何应用的？有什么注意事项？

**回答要点：**

这是一个考察 Python 异步编程能力的问题。

**1. 项目中的异步应用场景：**

```
异步应用场景
─────────────────────────────────────────
1. LLM API 调用        → await provider.chat()
2. 工具执行            → await tool.execute()
3. HTTP 请求           → await httpx.AsyncClient().get()
4. 子进程执行          → await asyncio.create_subprocess_shell()
5. 后台任务            → asyncio.create_task()
6. 异步锁              → async with asyncio.Lock()
7. 上下文管理器        → async with AsyncExitStack()
```

**2. 核心异步方法：**

```python
# AgentLoop 的异步方法
class AgentLoop:
    async def process_direct(self, content: str, ...) -> str:
        """CLI 调用入口"""
        await self._connect_mcp()
        return await self._process_message(content, ...)

    async def _run_agent_loop(self, initial_messages: list, ...) -> tuple:
        """核心循环"""
        for _ in range(self.max_iterations):
            # 异步调用大模型
            response = await self.provider.chat(messages=messages, ...)

            if response.has_tool_calls:
                for tool_call in response.tool_calls:
                    # 异步执行工具
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    self.context.add_tool_result(messages, ...)

    async def _consolidate_memory(self, session: Session) -> bool:
        """异步归档"""
        response = await provider.chat(messages=[...], tools=_SAVE_MEMORY_TOOL, ...)
```

**3. 工具执行的异步实现：**

```python
# Shell 工具
class ExecTool(Tool):
    async def execute(self, command: str, ...) -> str:
        # 异步创建子进程
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            # 异步等待进程完成
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            return f"错误：命令执行超时（{effective_timeout} 秒）"

        return self._format_output(stdout, stderr, process.returncode)

# Web 工具
class WebSearchTool(Tool):
    async def execute(self, query: str, ...) -> str:
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            r = await client.post(
                "https://api.bocha.cn/v1/web-search",
                json={"query": query, "count": n, "summary": True},
                timeout=30.0,
            )
            r.raise_for_status()
            return self._format_results(r.json())
```

**4. 后台任务模式：**

```python
class AgentLoop:
    def __init__(self):
        self._consolidating: set[str] = set()
        self._consolidation_tasks: set[asyncio.Task] = set()
        self._consolidation_locks: dict[str, asyncio.Lock] = {}

    def _schedule_consolidation(self, session: Session) -> None:
        """安排后台归档任务"""
        if session.key in self._consolidating:
            return

        self._consolidating.add(session.key)

        # 创建后台任务（不阻塞主流程）
        task = asyncio.create_task(self._run_consolidation(session))
        self._consolidation_tasks.add(task)

        # 任务完成后自动清理
        task.add_done_callback(self._consolidation_tasks.discard)

    async def _run_consolidation(self, session: Session) -> None:
        """后台归档任务"""
        try:
            async with self._get_consolidation_lock(session.key):
                await self._consolidate_memory(session)
        finally:
            self._consolidating.discard(session.key)
```

**5. 异步锁的使用：**

```python
def _get_consolidation_lock(self, session_key: str) -> asyncio.Lock:
    """获取会话专属的异步锁"""
    lock = self._consolidation_locks.get(session_key)
    if lock is None:
        lock = asyncio.Lock()
        self._consolidation_locks[session_key] = lock
    return lock

# 使用异步锁保护临界区
async with self._get_consolidation_lock(session.key):
    await self._consolidate_memory(session)
```

**6. AsyncExitStack 管理异步资源：**

```python
from contextlib import AsyncExitStack

async def _connect_mcp(self) -> None:
    """使用 AsyncExitStack 管理 MCP 连接生命周期"""
    self._mcp_stack = AsyncExitStack()

    # 连接 MCP 服务器
    await connect_mcp_servers(
        self._mcp_servers,
        self.tools,
        self._mcp_stack
    )

async def close_mcp(self) -> None:
    """关闭 MCP 连接"""
    if self._mcp_stack:
        await self._mcp_stack.aclose()  # 自动清理所有资源
        self._mcp_stack = None
```

**7. 异步编程注意事项：**

```python
# ❌ 错误：在异步函数中使用同步阻塞操作
async def bad_example():
    time.sleep(5)  # 阻塞整个事件循环！
    result = requests.get(url)  # 阻塞！

# ✅ 正确：使用异步库
async def good_example():
    await asyncio.sleep(5)  # 不阻塞，让出控制权
    async with httpx.AsyncClient() as client:
        result = await client.get(url)  # 异步请求

# ❌ 错误：忘记 await
async def bad_example():
    task = asyncio.create_task(some_async_function())  # 创建任务
    # 忘记 await，任务可能还没完成就退出了

# ✅ 正确：确保等待任务完成
async def good_example():
    task = asyncio.create_task(some_async_function())
    # ... 做其他事情 ...
    await task  # 确保任务完成

# ❌ 错误：在异步上下文中使用同步锁
import threading
lock = threading.Lock()  # 同步锁

async def bad_example():
    with lock:  # 会阻塞事件循环
        await some_async_function()

# ✅ 正确：使用异步锁
lock = asyncio.Lock()

async def good_example():
    async with lock:  # 不阻塞事件循环
        await some_async_function()
```

**8. 面试总结：**

| 场景     | 异步方法                                    | 注意事项             |
| -------- | ------------------------------------------- | -------------------- |
| API 调用 | `await provider.chat()`                   | 使用异步 HTTP 库     |
| 子进程   | `await asyncio.create_subprocess_shell()` | 设置超时             |
| 后台任务 | `asyncio.create_task()`                   | 跟踪任务，确保完成   |
| 并发控制 | `asyncio.Lock()`                          | 用异步锁，不用同步锁 |
| 资源管理 | `AsyncExitStack`                          | 自动清理资源         |

---

### Q20: 如果用户量增大，这个架构有什么瓶颈？如何优化？

**回答要点：**

这是一个考察系统设计和扩展性思维的问题。

**1. 当前架构的潜在瓶颈：**

```
瓶颈分析
─────────────────────────────────────────
                    ┌─────────────────────┐
                    │     单进程架构       │  ← 瓶颈1：无法利用多核
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   内存缓存会话数据   │  ← 瓶颈2：内存有限
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   本地文件存储       │  ← 瓶颈3：IO 瓶颈
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │   同步归档阻塞       │  ← 瓶颈4：CPU 密集
                    └─────────────────────┘
```

**2. 瓶颈1：单进程架构 → 多进程/分布式：**

```python
# 当前：单进程处理所有请求
async def run_interactive():
    while True:
        user_input = await read_input()
        response = await agent_loop.process_direct(user_input)
        print(response)

# 优化：多 Worker 进程
# 使用 uvicorn + FastAPI 提供 HTTP API
from fastapi import FastAPI
from concurrent.futures import ProcessPoolExecutor

app = FastAPI()
executor = ProcessPoolExecutor(max_workers=4)

@app.post("/chat")
async def chat(request: ChatRequest):
    # 将请求分发到 Worker 进程
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        executor,
        process_chat_sync,
        request.message
    )
    return {"response": response}
```

**3. 瓶颈2：内存缓存 → 分布式缓存：**

```python
# 当前：内存缓存
class SessionManager:
    def __init__(self):
        self._cache: dict[str, Session] = {}  # 内存缓存

    def get_or_create(self, key: str) -> Session:
        session = self._cache.get(key)
        # ...

# 优化：Redis 分布式缓存
import redis.asyncio as redis

class DistributedSessionManager:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
        self._local_cache = TTLCache(maxsize=1000, ttl=300)  # 本地 L1 缓存

    async def get_or_create(self, key: str) -> Session:
        # 先查本地缓存
        if key in self._local_cache:
            return self._local_cache[key]

        # 再查 Redis
        data = await self.redis.get(f"session:{key}")
        if data:
            session = Session(**json.loads(data))
            self._local_cache[key] = session
            return session

        # 创建新会话
        session = Session(key=key)
        await self._save(session)
        return session

    async def _save(self, session: Session):
        await self.redis.set(
            f"session:{session.key}",
            json.dumps(session.dict()),
            ex=3600  # 1 小时过期
        )
```

**4. 瓶颈3：本地文件存储 → 分布式存储：**

```python
# 当前：本地 JSONL 文件
class SessionManager:
    def save(self, session: Session):
        path = self._session_path(session.key)
        path.write_text(json.dumps(session.messages))

# 优化：对象存储（如 S3）或数据库
import boto3

class S3SessionStorage:
    def __init__(self, bucket: str):
        self.s3 = boto3.client('s3')
        self.bucket = bucket

    async def save(self, session: Session):
        # 并行上传到 S3
        await asyncio.to_thread(
            self.s3.put_object,
            Bucket=self.bucket,
            Key=f"sessions/{session.key}.json",
            Body=json.dumps(session.dict()),
        )

    async def load(self, key: str) -> Session | None:
        try:
            response = await asyncio.to_thread(
                self.s3.get_object,
                Bucket=self.bucket,
                Key=f"sessions/{key}.json",
            )
            data = json.loads(response['Body'].read())
            return Session(**data)
        except self.s3.exceptions.NoSuchKey:
            return None
```

**5. 瓶颈4：归档阻塞 → 消息队列：**

```python
# 当前：后台任务归档
def _schedule_consolidation(self, session: Session):
    task = asyncio.create_task(self._run_consolidation(session))

# 优化：消息队列 + 独立归档服务
import aio_pika

class ConsolidationQueue:
    def __init__(self, amqp_url: str):
        self.amqp_url = amqp_url
        self.connection = None

    async def publish(self, session_key: str, messages: list):
        if not self.connection:
            self.connection = await aio_pika.connect_robust(self.amqp_url)

        channel = await self.connection.channel()
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps({
                    "session_key": session_key,
                    "messages": messages,
                }).encode()
            ),
            routing_key="consolidation"
        )

# 独立的归档 Worker
async def consolidation_worker():
    connection = await aio_pika.connect_robust("amqp://localhost")
    channel = await connection.channel()
    queue = await channel.declare_queue("consolidation")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                data = json.loads(message.body)
                await do_consolidation(data["session_key"], data["messages"])
```

**6. 架构演进路线图：**

```
阶段1：单机优化
─────────────────────────────────────────
- 异步 I/O（已实现）
- 后台任务（已实现）
- 内存缓存优化

阶段2：水平扩展
─────────────────────────────────────────
┌─────────┐     ┌─────────┐     ┌─────────┐
│ API网关  │────►│ Worker 1 │     │ Worker 2 │
└─────────┘     └────┬────┘     └────┬────┘
                     │               │
                     └───────┬───────┘
                             ▼
                    ┌─────────────────┐
                    │  Redis 缓存      │
                    └─────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  PostgreSQL     │
                    └─────────────────┘

阶段3：微服务化
─────────────────────────────────────────
┌─────────┐     ┌─────────┐     ┌─────────┐
│ API网关  │────►│ 会话服务 │     │ 归档服务 │
└─────────┘     └─────────┘     └─────────┘
                     │               │
                     ▼               ▼
              ┌───────────┐   ┌───────────┐
              │ Redis     │   │ 消息队列   │
              └───────────┘   └───────────┘
                     │               │
                     ▼               ▼
              ┌───────────┐   ┌───────────┐
              │ PostgreSQL│   │ 向量数据库 │
              └───────────┘   └───────────┘
```

**7. 面试总结：**

| 瓶颈     | 当前方案       | 优化方案             |
| -------- | -------------- | -------------------- |
| 单进程   | asyncio 单进程 | 多 Worker + 负载均衡 |
| 内存缓存 | dict 内存存储  | Redis 分布式缓存     |
| 文件存储 | JSONL 本地文件 | S3/PostgreSQL        |
| 归档阻塞 | 后台任务       | 消息队列 + 独立服务  |

---

### Q21: 如何测试这个项目？单元测试和集成测试怎么写？

**回答要点：**

这是一个考察测试能力和代码质量意识的问题。

**1. 测试策略概览：**

```
测试金字塔
─────────────────────────────────────────
                    ┌─────────┐
                    │  E2E    │  ← 端到端测试（少量）
                    │  测试   │
                    ├─────────┤
                   ╱│ 集成测试 │  ← 集成测试（适量）
                  ╱ └─────────┘
                 ╱
                ╱  ┌─────────────┐
               ╱   │   单元测试   │  ← 单元测试（大量）
              ╱    └─────────────┘
             ╱
```

**2. 单元测试：工具类测试：**

```python
# tests/test_tools.py
import pytest
from ZBot.agent.tools.base import Tool
from ZBot.agent.tools.registry import ToolRegistry

class MockTool(Tool):
    """测试用的 Mock 工具"""
    @property
    def name(self) -> str:
        return "mock_tool"

    @property
    def description(self) -> str:
        return "A mock tool for testing"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["input"],
        }

    async def execute(self, input: str, count: int = 1, **kwargs) -> str:
        return input * count


class TestToolBase:
    """测试 Tool 基类"""

    @pytest.fixture
    def tool(self):
        return MockTool()

    def test_name(self, tool):
        assert tool.name == "mock_tool"

    def test_description(self, tool):
        assert tool.description == "A mock tool for testing"

    def test_to_schema(self, tool):
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "mock_tool"
        assert "input" in schema["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_execute(self, tool):
        result = await tool.execute(input="hello", count=3)
        assert result == "hellohellohello"


class TestToolCastParams:
    """测试参数类型转换"""

    @pytest.fixture
    def tool(self):
        return MockTool()

    def test_cast_string_to_integer(self, tool):
        """字符串转整数"""
        params = {"input": "test", "count": "5"}
        casted = tool.cast_params(params)
        assert casted["count"] == 5
        assert isinstance(casted["count"], int)

    def test_cast_string_to_boolean(self, tool):
        """字符串转布尔"""
        # 需要一个有布尔参数的工具
        class BoolTool(Tool):
            @property
            def name(self): return "bool_tool"
            @property
            def description(self): return ""
            @property
            def parameters(self):
                return {
                    "type": "object",
                    "properties": {"flag": {"type": "boolean"}},
                }
            async def execute(self, **kwargs): return ""

        tool = BoolTool()
        assert tool.cast_params({"flag": "true"})["flag"] == True
        assert tool.cast_params({"flag": "false"})["flag"] == False
        assert tool.cast_params({"flag": "yes"})["flag"] == True
        assert tool.cast_params({"flag": "no"})["flag"] == False


class TestToolValidateParams:
    """测试参数校验"""

    @pytest.fixture
    def tool(self):
        return MockTool()

    def test_validate_missing_required(self, tool):
        """缺少必填参数"""
        errors = tool.validate_params({})
        assert len(errors) > 0
        assert "缺少必填字段" in errors[0]

    def test_validate_out_of_range(self, tool):
        """参数超出范围"""
        errors = tool.validate_params({"input": "test", "count": 100})
        assert len(errors) > 0
        assert "必须小于等于" in errors[0]

    def test_validate_valid_params(self, tool):
        """有效参数"""
        errors = tool.validate_params({"input": "test", "count": 5})
        assert len(errors) == 0


class TestToolRegistry:
    """测试工具注册中心"""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def tool(self):
        return MockTool()

    def test_register(self, registry, tool):
        registry.register(tool)
        assert registry.get("mock_tool") == tool

    def test_get_definitions(self, registry, tool):
        registry.register(tool)
        definitions = registry.get_definitions()
        assert len(definitions) == 1
        assert definitions[0]["function"]["name"] == "mock_tool"

    @pytest.mark.asyncio
    async def test_execute(self, registry, tool):
        registry.register(tool)
        result = await registry.execute("mock_tool", {"input": "hi", "count": 2})
        assert result == "hihi"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, registry):
        result = await registry.execute("unknown", {})
        assert "错误" in result
        assert "找不到工具" in result
```

**3. 单元测试：ExecTool 安全测试：**

```python
# tests/test_exec_tool.py
import pytest
from ZBot.agent.tools.shell import ExecTool

class TestExecToolSecurity:
    """测试 ExecTool 安全机制"""

    @pytest.fixture
    def tool(self):
        return ExecTool(
            working_dir="/tmp",
            restrict_to_workspace=True
        )

    @pytest.mark.asyncio
    async def test_block_rm_rf(self, tool):
        """阻止 rm -rf"""
        result = await tool.execute("rm -rf /")
        assert "错误" in result
        assert "安全策略拦截" in result

    @pytest.mark.asyncio
    async def test_block_shutdown(self, tool):
        """阻止关机命令"""
        result = await tool.execute("shutdown -h now")
        assert "错误" in result
        assert "安全策略拦截" in result

    @pytest.mark.asyncio
    async def test_block_fork_bomb(self, tool):
        """阻止 Fork bomb"""
        result = await tool.execute(":(){ :|:& };:")
        assert "错误" in result
        assert "安全策略拦截" in result

    @pytest.mark.asyncio
    async def test_block_path_traversal(self, tool):
        """阻止路径穿越"""
        result = await tool.execute("cat ../../../etc/passwd")
        assert "错误" in result
        assert "路径穿越" in result

    @pytest.mark.asyncio
    async def test_allow_safe_command(self, tool):
        """允许安全命令"""
        result = await tool.execute("echo hello")
        assert "hello" in result
        assert "退出码：0" in result

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        """超时测试"""
        result = await tool.execute("sleep 100", timeout=1)
        assert "超时" in result
```

**4. 集成测试：AgentLoop 测试：**

```python
# tests/test_agent_loop.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from ZBot.agent.loop import AgentLoop
from ZBot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

class TestAgentLoop:
    """测试 AgentLoop"""

    @pytest.fixture
    def mock_provider(self):
        """Mock LLM 提供商"""
        provider = MagicMock(spec=LLMProvider)
        provider.chat = AsyncMock()
        return provider

    @pytest.fixture
    def agent(self, mock_provider, tmp_path):
        """创建 AgentLoop 实例"""
        return AgentLoop(
            provider=mock_provider,
            workspace=Path(tmp_path),
            model="test-model",
        )

    @pytest.mark.asyncio
    async def test_simple_response(self, agent, mock_provider):
        """测试简单回复（无工具调用）"""
        mock_provider.chat.return_value = LLMResponse(
            content="Hello! How can I help you?",
            tool_calls=[],
            finish_reason="stop",
        )

        response = await agent.process_direct("Hello", session_key="test")

        assert "Hello" in response
        mock_provider.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_call_flow(self, agent, mock_provider):
        """测试工具调用流程"""
        # 第一次调用：模型请求调用工具
        mock_provider.chat.side_effect = [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "/tmp/test.txt"}
                    )
                ],
                finish_reason="tool_calls",
            ),
            # 第二次调用：模型返回最终回复
            LLMResponse(
                content="The file contains: hello world",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]

        response = await agent.process_direct("Read the file /tmp/test.txt", session_key="test")

        assert "file" in response.lower()
        assert mock_provider.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_max_iterations(self, agent, mock_provider):
        """测试最大迭代次数"""
        agent.max_iterations = 3

        # 模型一直请求工具调用
        mock_provider.chat.return_value = LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="read_file",
                    arguments={"path": "/tmp/test.txt"}
                )
            ],
            finish_reason="tool_calls",
        )

        response = await agent.process_direct("Test", session_key="test")

        assert "最大" in response
        assert mock_provider.chat.call_count == 3
```

**5. 集成测试：记忆归档测试：**

```python
# tests/test_memory.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from ZBot.agent.memory import MemoryStore
from ZBot.session.manager import Session

class TestMemoryStore:
    """测试记忆存储"""

    @pytest.fixture
    def memory_store(self, tmp_path):
        return MemoryStore(Path(tmp_path))

    def test_read_write_long_term(self, memory_store):
        """测试读写长期记忆"""
        memory_store.write_long_term("# Test Memory\n\nThis is a test.")
        content = memory_store.read_long_term()
        assert "Test Memory" in content

    def test_append_history(self, memory_store):
        """测试追加历史"""
        memory_store.append_history("[2024-01-15 14:30] Test entry")
        memory_store.append_history("[2024-01-15 15:00] Another entry")

        content = memory_store.history_file.read_text()
        assert "Test entry" in content
        assert "Another entry" in content

    @pytest.mark.asyncio
    async def test_consolidate(self, memory_store):
        """测试归档流程"""
        # 创建模拟会话
        session = Session(
            key="test",
            messages=[
                {"role": "user", "content": "Hello", "timestamp": "2024-01-15T14:30:00"},
                {"role": "assistant", "content": "Hi!", "timestamp": "2024-01-15T14:30:05"},
            ]
        )

        # Mock 提供商
        provider = MagicMock()
        provider.chat = AsyncMock(return_value=MagicMock(
            has_tool_calls=True,
            tool_calls=[
                MagicMock(
                    arguments={
                        "history_entry": "[2024-01-15 14:30] User greeted assistant",
                        "memory_update": "# Memory\n\nUser likes to say hello."
                    }
                )
            ]
        ))

        result = await memory_store.consolidate(
            session,
            provider,
            "test-model",
            memory_window=1,
        )

        assert result == True
        assert session.last_consolidated > 0
```

**6. 测试配置：**

```python
# tests/conftest.py
import pytest
import asyncio

@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

**7. 面试总结：**

| 测试类型 | 覆盖范围                      | 工具                    |
| -------- | ----------------------------- | ----------------------- |
| 单元测试 | 工具类、参数校验、安全检查    | pytest + pytest-asyncio |
| 集成测试 | AgentLoop、记忆归档、会话管理 | pytest + Mock           |
| E2E 测试 | 完整对话流程                  | 手动测试 / Playwright   |

---

### Q22: 项目中用到了哪些 Python 高级特性？

**回答要点：**

这是一个考察 Python 语言功底的问题。

**1. 异步编程（asyncio）：**

```python
# 异步函数
async def process_direct(self, content: str) -> str:
    await self._connect_mcp()
    return await self._process_message(content)

# 异步上下文管理器
async with httpx.AsyncClient() as client:
    response = await client.get(url)

# 异步子进程
process = await asyncio.create_subprocess_shell(command, ...)

# 后台任务
task = asyncio.create_task(self._run_consolidation(session))
```

**2. 抽象基类（ABC）：**

```python
from abc import ABC, abstractmethod

class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        pass

# 子类必须实现所有抽象方法
class ReadFileTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"

    async def execute(self, path: str, **kwargs) -> str:
        # 具体实现
        pass
```

**3. 数据类（dataclass）：**

```python
from dataclasses import dataclass, field

@dataclass
class Session:
    key: str
    messages: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_consolidated: int = 0

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
```

**4. 类型注解（Type Hints）：**

```python
from typing import Any, Callable, Awaitable

# 联合类型
def __init__(self, model: str | None = None): ...

# 可调用类型
on_progress: Callable[..., Awaitable[None]] | None = None

# 泛型
def get[T](self, name: str) -> T | None: ...

# 类型别名
Messages = list[dict[str, Any]]
```

**5. 上下文管理器：**

```python
from contextlib import AsyncExitStack

# 异步上下文管理器
async def _connect_mcp(self):
    self._mcp_stack = AsyncExitStack()
    await connect_mcp_servers(..., self._mcp_stack)

async def close_mcp(self):
    if self._mcp_stack:
        await self._mcp_stack.aclose()

# 使用 with 语句
with console.status("Thinking..."):
    response = await agent.process_direct(message)
```

**6. 属性装饰器（@property）：**

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

class LLMResponse:
    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
```

**7. 正则表达式（re）：**

```python
import re

# 编译正则表达式（性能优化）
_THINK_BLOCK_RE = re.compile(r"<thinking>[\s\S]*?</thinking>", re.IGNORECASE)

# 使用正则
cleaned = _THINK_BLOCK_RE.sub("", text)

# 危险命令匹配
deny_patterns = [
    r"\brm\s+-[rf]{1,2}\b",
    r"\b(shutdown|reboot)\b",
]
```

**8. Pydantic 数据验证：**

```python
from pydantic import BaseModel, Field
from pydantic.alias_generators import to_camel

class Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True
    )

class Config(BaseModel):
    workspace: str = "~/.ZBot/workspace"
    model: str = ""
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
```

**9. 列表推导式和生成器表达式：**

```python
# 列表推导式
messages = [dict(message) for message in messages[skip:]]

# 生成器表达式
first_user = next(
    (i for i, m in enumerate(messages) if m.get("role") == "user"),
    None
)

# 字典推导式
result = {k: v for k, v in msg.items() if k in allowed_keys}
```

**10. 魔术方法：**

```python
# __init__: 初始化
def __init__(self, workspace: Path): ...

# __str__: 字符串表示
def __str__(self) -> str:
    return f"Session({self.key})"

# __enter__ / __exit__: 上下文管理器
def __enter__(self): ...
def __exit__(self, *args): ...
```

**11. 面试总结：**

| 特性       | 应用场景   | 示例                         |
| ---------- | ---------- | ---------------------------- |
| asyncio    | 异步 I/O   | `await provider.chat()`    |
| ABC        | 抽象基类   | `class Tool(ABC)`          |
| dataclass  | 数据类     | `@dataclass class Session` |
| Type Hints | 类型注解   | `def foo(x: str) -> int`   |
| contextlib | 上下文管理 | `AsyncExitStack`           |
| @property  | 属性装饰器 | `@property def name(self)` |
| re         | 正则表达式 | `re.compile(r"...")`       |
| Pydantic   | 数据验证   | `class Config(BaseModel)`  |

---

## 十五、场景模拟面试

本章节模拟真实的面试场景，提供问题、追问和完整回答。

---

### 场景1：项目介绍

**面试官：** 请简单介绍一下你做的这个 ZBot 项目。

**回答：**

ZBot 是一个基于 Python 的 AI 助手框架，我设计它的目标是创建一个可扩展、易维护的智能对话系统。

**核心功能方面：**

- 支持多种大语言模型提供商，包括 OpenRouter、DeepSeek、通义千问等
- 实现了完整的工具调用系统，支持文件操作、Shell 执行、网页搜索等
- 设计了长期记忆机制，可以自动归档和压缩对话历史
- 支持 MCP 协议，可以接入外部工具服务

**技术架构方面：**

- 采用分层架构设计，CLI 层、Agent 层、工具层、提供商层职责清晰
- 全异步实现，使用 asyncio 提高并发性能
- 使用 Pydantic 做配置管理和数据验证
- 会话持久化采用 JSONL 格式，便于追加和容错

**面试官追问：** 你觉得这个项目最大的技术难点是什么？

**回答：**

我认为最大的技术难点是**长期记忆的设计和实现**。

**难点在于：**

1. **何时触发归档**：不能太频繁（影响性能），也不能太晚（上下文爆炸）
2. **归档多少**：归档太多会影响对话连贯性，归档太少没有意义
3. **如何压缩**：需要调用大模型，但要保证压缩后的信息有用
4. **并发控制**：多个会话可能同时触发归档，需要防止冲突

**我的解决方案：**

1. 设置 `memory_window`（默认 50 条），当未归档消息达到阈值时触发
2. 保留最近一半窗口的消息，确保对话连贯性
3. 使用 `save_memory` 工具让模型返回结构化结果
4. 使用状态标记 + 异步锁防止并发冲突
5. 后台异步执行，不阻塞主流程

---

### 场景2：工具系统设计

**面试官：** 你提到工具调用系统，能详细说说你是怎么设计的吗？

**回答：**

我采用了**抽象基类 + 注册中心**的设计模式。

**首先是抽象基类 Tool：**

```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict: ...

    @abstractmethod
    async def execute(self, **kwargs) -> str: ...
```

这样设计的好处是：

1. 统一接口：所有工具都有相同的属性和方法
2. 参数处理复用：基类提供 `cast_params` 和 `validate_params`
3. 扩展性好：新增工具只需继承并实现抽象方法

**然后是注册中心 ToolRegistry：**

```python
class ToolRegistry:
    def register(self, tool: Tool): ...
    def get_definitions(self) -> list[dict]: ...
    async def execute(self, name: str, params: dict) -> str: ...
```

注册中心负责：

1. 管理工具实例
2. 输出工具 schema 给模型
3. 统一执行入口，包含参数转换、校验、错误包装

**面试官追问：** Shell 工具很危险，你是怎么保证安全的？

**回答：**

我实现了三层安全防护：

**第一层：黑名单检查**

```python
deny_patterns = [
    r"\brm\s+-[rf]{1,2}\b",     # rm -rf
    r"\b(shutdown|reboot)\b",   # 关机命令
    r":\(\)\s*\{.*\};\s*:",     # Fork bomb
]
```

**第二层：白名单检查（可选）**
只允许特定命令执行，适合严格场景。

**第三层：路径限制**
检查命令中的路径是否在工作区内，阻止 `../` 路径穿越。

**另外还有执行限制：**

- 超时限制：默认 60 秒，最大 600 秒
- 输出截断：最大 10KB，防止内存溢出

---

### 场景3：性能优化

**面试官：** 如果用户量增大，你的系统会有什么瓶颈？怎么优化？

**回答：**

我分析过当前架构的几个潜在瓶颈：

**瓶颈1：单进程架构**

- 问题：无法利用多核 CPU
- 优化：使用多 Worker 进程 + 负载均衡

**瓶颈2：内存缓存**

- 问题：会话数据存在内存中，容量有限
- 优化：引入 Redis 分布式缓存，支持多实例共享

**瓶颈3：本地文件存储**

- 问题：JSONL 文件在高并发下有 IO 瓶颈
- 优化：改用 PostgreSQL 或对象存储

**瓶颈4：归档阻塞**

- 问题：虽然后台执行，但大量归档仍消耗资源
- 优化：引入消息队列，独立归档服务

**演进路线：**

```
单机优化 → 水平扩展 → 微服务化
```

---

### 场景4：异步编程

**面试官：** 你项目中大量使用了异步编程，有什么注意事项？

**回答：**

异步编程有几个关键注意事项：

**1. 不要阻塞事件循环**

```python
# ❌ 错误
time.sleep(5)  # 阻塞整个事件循环

# ✅ 正确
await asyncio.sleep(5)  # 让出控制权
```

**2. 使用异步库**

```python
# ❌ 错误
import requests
response = requests.get(url)  # 同步请求

# ✅ 正确
import httpx
async with httpx.AsyncClient() as client:
    response = await client.get(url)  # 异步请求
```

**3. 使用异步锁**

```python
# ❌ 错误
import threading
lock = threading.Lock()  # 同步锁

# ✅ 正确
lock = asyncio.Lock()  # 异步锁
async with lock:
    await some_async_function()
```

**4. 确保任务完成**

```python
task = asyncio.create_task(some_function())
# ... 做其他事情 ...
await task  # 确保任务完成
```

---

### 场景5：设计模式

**面试官：** 你项目中用到了哪些设计模式？

**回答：**

我主要用到了以下几种设计模式：

**1. 适配器模式**
用于 MCP 工具适配：

```python
class MCPToolWrapper(Tool):
    """将 MCP 工具适配为 ZBot 的 Tool 接口"""
    def __init__(self, session, server_name, tool_def):
        self._name = f"mcp_{server_name}_{tool_def.name}"
```

**2. 模板方法模式**
Tool 基类定义流程，子类实现具体逻辑。

**3. 注册中心模式**
ToolRegistry 统一管理工具的注册和执行。

**4. 懒加载模式**
MCP 连接只在首次需要时建立：

```python
async def _connect_mcp(self):
    if self._mcp_connected:
        return
    # 建立连接...
```

**5. 后台任务模式**
记忆归档使用 `asyncio.create_task()` 异步执行。

---

**祝面试顺利！**
