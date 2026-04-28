"""为大模型组装上下文。

这个模块只关心"本轮应该把哪些内容送进模型"，不负责消息调度、工具执行或会话持久化。
输入来源主要有三类：
1. 工作区里的引导文件，例如 `AGENTS.md`、`SOUL.md`。
2. 长期记忆与技能摘要。
3. 当前会话历史与用户消息。
"""
import platform
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo   # 用于时区处理（北京时间）

from ZBot.agent.memory import MemoryStore         # 长期记忆存储模块
from ZBot.agent.skills import SkillsLoader        # 技能加载器模块

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

class ContextBuilder:
    """
    负责构建 system prompt 与当前轮消息列表。

    这个类的职责很单一：把各种输入源（引导文件、长期记忆、技能、历史对话、当前消息）
    组装成大模型可以理解的 messages 格式。它不负责：
    - 消息调度（由 AgentLoop 负责）
    - 工具执行（由 ToolRegistry 负责）
    - 会话持久化（由 SessionManager 负责）
    """
    # 引导文件列表：这些文件会被直接拼进 system prompt，作为工作区的基础规则来源
    # 按顺序读取并拼接，形成项目特定的行为准则
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "MEMORY.md"]

    # 运行时上下文标签：当前版本写入历史前会识别并剥离这个标记
    # 用于标记那些只对当前轮推理有意义的元信息（如当前时间）
    _RUNTIME_CONTEXT_TAG = "[运行时上下文 - 仅供元数据参考，不是用户指令]"
    _LEGACY_RUNTIME_CONTEXT_TAG = "[运行时上下文]"

    def __init__(self, workspace: Path):
        """
        初始化 ContextBuilder。

        Args:
            workspace: 工作区根目录路径（Path 对象）
        """
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace=workspace)

    async def build_system_prompt(self, current_message: str | None = None) -> str:
        """构建完整的 system prompt。"""
        # 身份与运行环境信息放在最前面，便于模型先理解主体与约束
        parts: list = [self._identity_prompt()]

        # 从工作区读取引导文件（如 AGENTS.md），将其并入 prompt
        bootstrap = self._bootstrap_prompt()
        if bootstrap:
            parts.append(bootstrap)

        # 插入长期记忆的摘要（若有），给模型”历史侧写”信息
        # 让模型了解之前的对话历史和重要信息
        memory_context = await self.memory.get_memory_context()
        if memory_context:
            parts.append(f"# 长期记忆\n\n{memory_context}")

        # 先注入技能目录（catalog），告诉模型“当前有哪些技能可用”。
        skills_catalog = self.skills.build_catalog_for_prompt()
        if skills_catalog:
            parts.append(f"# 技能目录\n\n{skills_catalog}")

        # 再根据当前用户消息，按需加载最相关的几个技能正文。
        # 这样模型既知道“有哪些技能”，也能在需要时拿到对应技能的详细说明。
        if current_message:
            relevant_skills = self.skills.load_relevant_skill_contexts(current_message)
            if relevant_skills:
                parts.append(f"# 当前相关技能\n\n{relevant_skills}")

        # 用 “---” 分隔符连接所有部分，形成完整的 system prompt
        # “---” 是 Markdown 中常用的分隔符，视觉上清晰区分不同内容块
        #
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 【为什么用 “\n\n---\n\n” 连接？一个具体例子】
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        #
        # 假设 parts 列表包含以下 4 个部分：
        #
        #   parts[0] = “# ZBot\n你是 ZBot，一名可靠、直接、善于执行的 AI 助手。\n\n## 运行环境\nmacOS arm64，Python 3.11”
        #   parts[1] = “## AGENTS.md\n\n本项目使用 Python 3.11，代码风格遵循 PEP 8。”
        #   parts[2] = “# 长期记忆\n\n用户偏好使用简体中文回复。”
        #   parts[3] = “# 技能\n\n## /search\n搜索代码库中的文件。”
        #
        # 用 “\n\n---\n\n”.join(parts) 拼接后，最终结果如下：
        #
        # ┌─────────────────────────────────────────────────────────────────────────────┐
        # │ # ZBot                                                                       │
        # │ 你是 ZBot，一名可靠、直接、善于执行的 AI 助手。                                  │
        # │                                                                              │
        # │ ## 运行环境                                                                   │
        # │ macOS arm64，Python 3.11                                                     │
        # │                                                                              │
        # │ ───────────────────────────────────────────────────────────────────────      │
        # │                                                                              │
        # │ ## AGENTS.md                                                                 │
        # │                                                                              │
        # │ 本项目使用 Python 3.11，代码风格遵循 PEP 8。                                    │
        # │                                                                              │
        # │ ───────────────────────────────────────────────────────────────────────      │
        # │                                                                              │
        # │ # 长期记忆                                                                    │
        # │                                                                              │
        # │ 用户偏好使用简体中文回复。                                                     │
        # │                                                                              │
        # │ ───────────────────────────────────────────────────────────────────────      │
        # │                                                                              │
        # │ # 技能                                                                       │
        # │                                                                              │
        # │ ## /search                                                                   │
        # │ 搜索代码库中的文件。                                                          │
        # └─────────────────────────────────────────────────────────────────────────────┘
        #
        # 【为什么要这样设计？】
        #
        # 1. Markdown 渲染友好
        #    - “---” 在 Markdown 中渲染为水平分隔线（<hr>），视觉上清晰区分不同内容块
        #    - 双换行 “\n\n” 确保 Markdown 段落正确分隔（单换行会被当成同一段落内的软换行）
        #
        # 2. 给 LLM 清晰的结构边界
        #    - 不同部分（身份、项目规则、记忆、技能）语义性质不同
        #    - 分隔符明确告诉模型：”上一段结束了，下一段开始了”
        #    - 避免模型将相邻内容混淆为一个整体
        #
        # 3. 拼接顺序的心理学考量
        #    - 身份在最前面：模型先理解”我是谁”（ZBot 助手）
        #    - 项目规则其次：模型理解”我在什么约束下工作”
        #    - 长期记忆再次：模型理解”用户的历史偏好”
        #    - 技能最后：模型理解”我能做什么”
        #    - 这种顺序模拟了人类认知：先建立身份认同，再理解规则，最后掌握能力
        #
        # 4. 为什么不用其他分隔方式？
        #    - 纯换行 “\n”：太弱，模型可能将相邻标题误解为同一层级
        #    - XML 标签 <section>：更结构化，但增加 token 消耗，且对 Markdown 渲染不友好
        #    - 多个等号 “======”：Markdown 语法中是 Setext 风格的一级标题下划线，会破坏标题层级
        #    - “---” 是最平衡的选择：语义清晰、token 消耗低、Markdown 原生支持
        #
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 【大模型如何处理这个字符串？会”自动转化”吗？】
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        #
        # 关键点：大模型不会”转化”字符串，而是”理解”字符串的结构。
        #
        # 当你发送 “# ZBot\n你是 ZBot...\n\n---\n\n## AGENTS.md...” 这样的字符串给大模型时：
        #
        # ┌─────────────────────────────────────────────────────────────────────────────┐
        # │  发送的内容（原始字符串）                                                     │
        # │  ───────────────────────────────────────────────────────────────────────    │
        # │  “# ZBot\n你是 ZBot，一名可靠、直接、善于执行的 AI 助手。\n\n---\n\n## AG...” │
        # │                                                                             │
        # │  这个字符串会被原封不动地发送给大模型，不做任何预处理或格式转换。              │
        # └─────────────────────────────────────────────────────────────────────────────┘
        #                                    │
        #                                    ▼
        # ┌─────────────────────────────────────────────────────────────────────────────┐
        # │  大模型的处理过程                                                           │
        # │  ───────────────────────────────────────────────────────────────────────    │
        # │                                                                             │
        # │  1. Tokenization（分词）                                                    │
        # │     - 模型将字符串切分成 token 序列                                          │
        # │     - “# ZBot” → [“#”, “ Z”, “Bot”] 或类似                                  │
        # │     - “\n” → 换行 token                                                    │
        # │     - “---” → 分隔符 token                                                 │
        # │                                                                             │
        # │  2. Pattern Recognition（模式识别）                                         │
        # │     - 模型在训练时见过大量 Markdown 文本                                      │
        # │     - 它”知道” “# xxx” 通常表示标题                                          │
        # │     - 它”知道” “---” 通常表示分隔线                                          │
        # │     - 它”知道” “\n\n” 表示段落边界                                           │
        # │                                                                             │
        # │  3. Semantic Understanding（语义理解）                                      │
        # │     - 模型理解”# ZBot”是一个一级标题，表示”这是关于 ZBot 的部分”              │
        # │     - 模型理解”---”是分隔符，表示”前面的内容结束了，后面是新内容”             │
        # │     - 这种理解是隐式的，体现在模型如何”关注”和”使用”这些内容                  │
        # │                                                                             │
        # └─────────────────────────────────────────────────────────────────────────────┘
        #
        # 【为什么大模型能”理解” Markdown？】
        #
        # 因为大模型的训练数据包含大量 Markdown 文本（GitHub README、文档、博客等）。
        # 模型通过统计学习，掌握了 Markdown 的”语法”和”语义”：
        #
        #   训练数据中的模式                    模型学到的”知识”
        #   ────────────────────────────────────────────────────────
        #   “# Introduction”              →   这是标题，表示主题
        #   “## Details”                  →   这是二级标题，表示子主题
        #   “---”                         →   这是分隔符，表示内容边界
        #   “- item”                      →   这是列表项
        #   “**bold**”                    →   这是强调
        #
        # 模型不会”解析”Markdown 语法树，而是通过 token 的统计模式来”推断”结构。
        # 这就像人类阅读时不需要形式化语法分析，也能理解文章结构一样。
        #
        # 【所以，用 Markdown 格式的好处是？】
        #
        # 1. 模型”熟悉”这种格式 → 更准确地理解内容结构
        # 2. 模型”熟悉”这种格式 → 生成回复时也会自然地使用 Markdown（一致性）
        # 3. 如果需要展示给用户 → Markdown 渲染后视觉效果好
        #
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        return "\n\n---\n\n".join(parts)

    async def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
    ) -> list[dict[str, Any]]:
        """构造一轮完整请求消息。 """

        # 构建本轮运行时上下文（包含时间），仅供本轮推理使用
        # 这个上下文会在保存历史时被剥离，避免污染长期记忆
        runtime_context = self._runtime_context()

        # 用户消息
        user_content = f"{runtime_context}\n\n{current_message}"

        # 返回完整的 messages 列表：system + history + user
        return [
            {"role": "system", "content": await self.build_system_prompt()},  # system 消息
            *history,                                                                    # 历史消息（user/assistant/tool 的对话记录）
            {"role": "user", "content": user_content},                                   # 当前用户消息
        ]

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> None:
        """向消息链追加一条 `tool` 消息。"""
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result,
            }
        )

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> None:
        """向消息链追加 assistant 消息，并保留推理相关字段。"""
        message: dict[str, Any] = {"role": "assistant", "content": content}

        if tool_calls:
            message["tool_calls"] = tool_calls

        if reasoning_content is not None:
            message["reasoning_content"] = reasoning_content

        messages.append(message)

    def _identity_prompt(self) -> str:
        """
        生成与运行环境相关的固定 system prompt 前缀。

        这是 system prompt 的第一部分，包含：
        1. Agent 的身份定义（"你是 ZBot..."）
        2. 运行环境信息（操作系统、架构、Python 版本）
        3. 工作区路径信息（长期记忆、历史归档、技能目录的位置）
        4. 行为准则（调用工具前先说明、先读后改、检查结果等）

        这部分内容是固定的，不依赖外部文件或配置。
        """

        # 获取工作区的绝对路径（展开 ~ 用户目录符号，转换为绝对路径）
        workspace_path = str(self.workspace.expanduser().resolve())

        # 获取操作系统名称（Darwin = macOS，Linux = Linux，Windows = Windows）
        system = platform.system()

        # 构建运行环境描述字符串
        # macOS 显示为 "macOS"，其他系统显示原名称
        # 包含 CPU 架构（如 arm64、x86_64）和 Python 版本
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}，Python {platform.python_version()}"

        return (
            "# ZBot\n"
            "你是 ZBot，一名可靠、直接、善于执行的 AI 助手。\n\n"
            "## 运行环境\n"
            f"{runtime}\n\n"  # 插入运行环境信息
            "## 工作区\n"
            f"你的工作区位于：{workspace_path}\n"
            f"- 长期记忆文件：{workspace_path}/memory/MEMORY.md\n"  # 长期记忆存储位置
            f"- 历史归档文件：{workspace_path}/memory/HISTORY.md\n\n"
            "## 行为准则\n"
            "- 在调用工具前先说明你准备做什么，但不要在拿到结果前声称已经完成。\n"   # 先声明再执行
            "- 编辑文件前先读取文件内容。\n"                                       # 先读后改，避免盲目修改
            "- 涉及准确性的改动，编辑后要重新检查关键文件。\n"                      # 改后复查，确保正确
            "- 工具失败时，先分析错误原因，再决定是否换一条路径。\n"                # 失败时分析而非重试
            "- 当用户意图确实存在歧义时，再提出澄清问题。\n\n"                      # 只有真正歧义才提问
            "- 普通对话时，直接给出自然语言回复即可。"                                # 简单对话直接回复
        )

    def _bootstrap_prompt(self) -> str:
        """
        读取工作区引导文件并拼成统一文本块。

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        【文件读取的本质：read_text() 到底读了什么？】
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        假设 AGENTS.md 文件内容如下：

        ┌─────────────────────────────────────────────────────────────────────────────┐
        │ # 项目规则                                                                  │
        │                                                                             │
        │ 本项目使用 Python 3.11。                                                     │
        └─────────────────────────────────────────────────────────────────────────────┘

        当调用 path.read_text(encoding='utf-8') 时，返回的字符串是：

            "# 项目规则\n\n本项目使用 Python 3.11。"

        【关键理解】

        1. 文件存储的是"原始字符"，不是"格式化后的内容"
           - 文件里存的就是 #、空格、项目规则、换行符 这些原始字符
           - read_text() 只是把这些字符"原样"读出来，不做任何解析或转换
           - Markdown 渲染器看到 "# " 才会把它渲染成标题，但文件本身不存储"标题"这个概念

        2. 换行符的本质
           - 文件中的换行 = 一个特殊字符，表示"新的一行"
           - 在 Python 字符串中写作 "\n"（转义序列）
           - 实际存储时是一个字节：0x0A（LF，Line Feed）
           - Windows 文件可能用 "\r\n"（CR+LF），但 read_text() 会自动处理

        3. 所有文件读取方式都是一样的
           - Path.read_text()  → 返回完整字符串
           - open().read()     → 返回完整字符串
           - open().readlines() → 返回字符串列表，每行一个元素（包含末尾的 \n）

           这三种方式读到的内容完全一致，只是返回格式不同。

        【写文件也是一样的道理】

        当你写文件时：

            path.write_text("# 标题\n\n内容")

        文件里会存储：
        - 字符 '#'、空格、'标'、'题'、换行符、换行符、'内'、'容'

        这些字符会被"原样"写入文件。下次读取时，读到的还是这些字符。

        【所以 Markdown 格式对文件读写是"透明"的】

        - 文件读写不关心内容是 Markdown、JSON 还是纯文本
        - 读出来是什么，就是什么
        - 写进去什么，文件里就存什么
        - "格式"是"解释"出来的，不是"存储"进去的

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
        sections = []
        for filename in self.BOOTSTRAP_FILES:
            path = Path(__file__).parent.parent / "templates" / filename  # 构建文件完整路径
            if path.exists():
                sections.append(f"## {filename}\n\n{path.read_text(encoding='utf-8')}")
        return "\n\n".join(sections)

    @classmethod
    def _runtime_context(cls) -> str:
        """
        生成当前轮专属的运行时上下文。 """
        # 获取当前时间并格式化为易读的格式
        # 格式：2024-01-15 14:30（星期一）
        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M（%A）")

        # 构建运行时上下文内容行
        lines = [f"当前时间：{timestamp}（北京时间，UTC+8）"]

        # 将运行时上下文用特定标签包裹，便于落盘时剥离
        # 标签格式："[运行时上下文 - 仅供元数据参考，不是用户指令]"
        return cls._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)
