"""会话记忆与历史归档。

这个模块处理的是"会话太长之后，如何把旧消息压缩成长期可用的信息"。
目标不是做复杂知识库，而是维护两份简单但稳定的文件：
1. `SESSION_MEMORY.md`：持续演进的会话记忆（可被模型读取和更新）
2. `HISTORY.md`：只追加不回写的历史摘要（用于人工查阅和调试）

核心类：
    SessionMemoryStore: 封装 memory/ 目录中的读写与归档逻辑
"""

from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from loguru import logger

if TYPE_CHECKING:
    from ZBot.providers.base import LLMProvider
    from ZBot.session.manager import Session


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "保存一条压缩后的历史摘要，并返回更新后的会话记忆内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": (
                            "用 2 到 5 句话总结本次归档内容，并以 [YYYY-MM-DD HH:MM] 时间戳开头，"
                            "方便后续用 grep 或关键字检索。"
                        ),
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "更新后的完整 SESSION_MEMORY.md 内容，Markdown 格式。",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class SessionMemoryStore:
    """
    封装 `memory/` 目录中的读写与归档逻辑。
    """

    def __init__(self, workspace: Path):
        """
        Args:
            workspace: 工作区根目录路径
        """
        self.memory_dir = workspace / "memory"
        self.memory_file = self.memory_dir / "SESSION_MEMORY.md"     # 会话记忆文件路径
        self.history_file = self.memory_dir / "HISTORY.md"   # 历史归档文件路径


    async def read_long_term(self) -> str:
        """读取会话记忆全文；文件不存在时返回空字符串。"""
        if not self.memory_file.exists():
            return ""
        return await asyncio.to_thread(self.memory_file.read_text, encoding="utf-8")


    async def write_session_memory(self, content: str) -> None:
        """覆盖写入 `SESSION_MEMORY.md`。Path.write_text() 方法在文件不存在时会自动创建文件"""
        await asyncio.to_thread(self.memory_file.write_text, content, encoding="utf-8")


    async def append_history(self, entry: str) -> None:
        """向 `HISTORY.md` 追加一条阶段性摘要。"""
        def _append():
            with open(self.history_file, "a", encoding="utf-8") as handle:
                handle.write(entry.strip() + "\n\n")
        await asyncio.to_thread(_append)


    async def get_memory_context(self) -> str:
        """
        返回适合直接注入 prompt 的会话记忆文本。

        如果 SESSION_MEMORY.md 有内容，则返回格式化的文本块；
        如果为空，则返回空字符串。
        """
        memory = await self.read_long_term()
        return f"## SESSION_MEMORY.md\n{memory}" if memory else ""



    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        memory_window: int = 25,
        consolidate_all: bool = False,
    ) -> bool:
        """
        把会话中的旧消息归档进会话记忆。

        这是会话记忆的核心方法，执行流程：
        1. 确定要归档的消息范围（_messages_to_archive）
        2. 构造归档提示词（_build_prompt）
        3. 调用大模型压缩历史并生成更新建议
        4. 处理模型返回的结果并更新文件
        5. 更新会话的 last_consolidated 标记

        Args:
            session: 当前会话对象
            provider: LLM 提供商实例
            model: 使用的模型名称
            memory_window: 记忆窗口大小（决定保留多少最新消息）

        Returns:
            True 表示归档成功，False 表示失败
        """
        # 确定本次要归档的消息区间和需要保留的尾部消息数量
        messages, keep_count = self._messages_to_archive(session, memory_window,consolidate_all)
        if not messages:
            return True  # 没有消息需要归档，直接返回成功

        # 读取当前的会话记忆内容
        current_memory = await self.read_long_term()
        # 构造归档提示词（包含当前记忆和待归档消息）
        prompt = self._build_prompt(current_memory, messages)

        try:
            # 调用大模型进行历史压缩
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你负责从旧对话中提取值得长期保留的知识，更新 SESSION_MEMORY.md。"
                            "只记事实和决策，不记过程；只记长期有效的，不记临时的。"
                            "必须调用 save_memory 工具返回结构化结果。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,  # 强制模型使用 save_memory 工具
                model=model,
            )
        except Exception:
            logger.exception("会话记忆归档失败")
            return False

        # 检查模型是否调用了 save_memory 工具
        if not response.has_tool_calls:
            logger.warning("会话记忆归档被跳过：模型没有调用 save_memory 工具")
            return False

        # 规范化工具参数（处理不同格式的返回值）
        args = self._normalize_tool_args(response.tool_calls[0].arguments)
        if args is None:
            logger.warning("会话记忆归档失败：模型返回的工具参数格式不正确")
            return False

        # 处理历史摘要（追加到 HISTORY.md）
        history_entry = self._coerce_text(args.get("history_entry"))
        if history_entry:
            await self.append_history(history_entry)


        # 处理会话记忆更新（覆盖写入 SESSION_MEMORY.md）
        memory_update = self._coerce_text(args.get("memory_update"))
        if memory_update is not None and memory_update != current_memory:
            await self.write_session_memory(memory_update)


        # 更新会话的归档标记和记忆快照
        session.last_consolidated = len(session.messages) - keep_count

        session.memory_snapshot = memory_update

        logger.info(
            "会话记忆归档完成：本次归档 {} 条消息，last_consolidated={}",
            len(messages),
            session.last_consolidated,
        )
        return True

    @staticmethod
    def _messages_to_archive(
        session: Session,
        memory_window: int,
        consolidate_all: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        确定本次归档的消息区间，以及本轮需要保留多少尾部消息。
        """
        if consolidate_all:
            return session.messages[session.last_consolidated :], 0  # 归档所有剩余消息，不保留尾部
            
        # 保留最近 memory_window 条消息
        # 这样下一轮 get_history(max_messages=memory_window) 能返回完整的历史
        keep_count = memory_window
        if len(session.messages) <= keep_count:
            # 消息总数不超过保留数量，无需归档
            return [], keep_count

        # 计算归档范围：从上次归档位置到倒数 keep_count 条消息
        start = session.last_consolidated  # 上次归档结束的位置
        end = len(session.messages) - keep_count  # 保留尾部 keep_count 条
        if end <= start:
            # 归档范围无效（已经归档过了），无需归档
            return [], keep_count

        # 返回要归档的消息片段和保留数量
        return session.messages[start:end], keep_count

    def _build_prompt(self, current_memory: str, messages: list[dict[str, Any]]) -> str:
        """把会话记忆和待归档对话整理成提示词。1. 当前 SESSION_MEMORY.md 的内容。2. 待归档的对话历史（格式化后的转录文本）"""
        # 格式化消息列表为转录文本
        transcript = "\n".join(self._format_messages(messages))
        return (
            "请整理下面的旧对话，提取值得长期保留的信息，更新 SESSION_MEMORY.md。\n\n"
            "## 操作指引\n"
            "1. 阅读「待归档对话」，提取以下类型的信息：\n"
            "   - 用户的长期偏好（语言、风格、工具选择等）\n"
            "   - 项目事实（技术栈、架构、目录结构、部署方式等）\n"
            "   - 重要决策及其原因（为什么选 A 不选 B）\n"
            "   - 环境配置（关键路径、账号、服务地址等）\n"
            "   - 持续有效的约定和规则\n"
            "2. 跳过以下内容：\n"
            "   - 临时状态、一次性任务、短期计划\n"
            "   - 可以从代码或文件重新推导的信息\n"
            "   - 已经过时或被推翻的旧决策\n"
            "3. 与「当前 SESSION_MEMORY.md」合并：\n"
            "   - 已有的事实如果没有变化就保留\n"
            "   - 有变化就原地更新，不要保留历史版本\n"
            "   - 新增的内容插入对应分区\n"
            "4. 输出格式：Markdown，按 ## 分区组织（用户偏好、项目、关键决策、环境等），"
            "每个分区下用简洁条目记录，不写长段落。\n\n"
            "## 当前 SESSION_MEMORY.md\n"
            f"{current_memory or '(当前为空)'}\n\n"
            "## 待归档对话\n"
            f"{transcript}"
        )

    @staticmethod
    def _format_messages(messages: list[dict[str, Any]]) -> list[str]:
        """把消息列表格式化成适合归档模型阅读的转录文本。每条消息的格式：[timestamp] ROLE[tools_used]: content"""
        lines: list[str] = []
        for message in messages:
            content = message.get("content")
            if not content:
                continue  # 跳过空内容消息
            # 获取使用的工具列表（如果有）
            tools = message.get("tools_used") or []
            tool_suffix = f" [使用工具: {','.join(tools)}]" if tools else ""
            # 截取时间戳的前 16 个字符（YYYY-MM-DD HH:MM）
            timestamp = str(message.get("timestamp", "?"))[:16]
            # 构造格式化行：[2024-01-15 14:30] USER [使用工具: web_search]: 用户消息内容
            lines.append(f"[{timestamp}] {message.get('role', 'unknown').upper()}{tool_suffix}: {content}")
        return lines

    @staticmethod
    def _normalize_tool_args(arguments: Any) -> dict[str, Any] | None:
        """把模型返回的工具参数统一规整成字典。"""
        # 如果是字符串，尝试 JSON 解析
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return None

        # 如果是列表，取第一个字典元素
        if isinstance(arguments, list):
            arguments = arguments[0] if arguments and isinstance(arguments[0], dict) else None

        # 确保返回字典类型
        return arguments if isinstance(arguments, dict) else None

    @staticmethod
    def _coerce_text(value: Any) -> str | None:
        """把工具结果字段规范成字符串，便于直接写文件。"""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        # 其他类型（如数字、布尔值、列表、字典）转换为 JSON 字符串
        return json.dumps(value, ensure_ascii=False)
