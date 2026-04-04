"""长期记忆与历史归档。

这个模块处理的是“会话太长之后，如何把旧消息压缩成长期可用的信息”。
目标不是做复杂知识库，而是维护两份简单但稳定的文件：
1. `MEMORY.md`：持续演进的长期记忆。
2. `HISTORY.md`：只追加不回写的历史摘要。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


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
                        "description": (
                            "用 2 到 5 句话总结本次归档内容，并以 [YYYY-MM-DD HH:MM] 时间戳开头，"
                            "方便后续用 grep 或关键字检索。"
                        ),
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


class MemoryStore:
    """封装 `memory/` 目录中的读写与归档逻辑。"""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        """读取长期记忆全文；文件不存在时返回空字符串。"""
        return self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""

    def write_long_term(self, content: str) -> None:
        """覆盖写入 `MEMORY.md`。"""
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        """向 `HISTORY.md` 追加一条阶段性摘要。"""
        with open(self.history_file, "a", encoding="utf-8") as handle:
            handle.write(entry.strip() + "\n\n")

    def get_memory_context(self) -> str:
        """返回适合直接注入 prompt 的长期记忆文本。"""
        memory = self.read_long_term()
        return f"## MEMORY.md\n{memory}" if memory else ""

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
        messages, keep_count = self._messages_to_archive(session, archive_all, memory_window)
        if not messages:
            return True

        current_memory = self.read_long_term()
        prompt = self._build_prompt(current_memory, messages)

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "你负责压缩对话历史，且必须调用 save_memory 工具返回结构化结果。",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )
        except Exception:
            logger.exception("长期记忆归档失败")
            return False

        if not response.has_tool_calls:
            logger.warning("长期记忆归档被跳过：模型没有调用 save_memory 工具")
            return False

        args = self._normalize_tool_args(response.tool_calls[0].arguments)
        if args is None:
            logger.warning("长期记忆归档失败：模型返回的工具参数格式不正确")
            return False

        history_entry = self._coerce_text(args.get("history_entry"))
        if history_entry:
            self.append_history(history_entry)

        memory_update = self._coerce_text(args.get("memory_update"))
        if memory_update is not None and memory_update != current_memory:
            self.write_long_term(memory_update)

        session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
        logger.info(
            "长期记忆归档完成：本次归档 {} 条消息，last_consolidated={}",
            len(messages),
            session.last_consolidated,
        )
        return True

    @staticmethod
    def _messages_to_archive(
        session: Session,
        archive_all: bool,
        memory_window: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """确定本次要归档的消息区间，以及本轮需要保留多少尾部消息。

        默认策略是“保留最近一半窗口，归档更早的部分”，
        这样下一轮模型还能看到足够新的上下文，而老消息不会无限膨胀。
        """
        if archive_all:
            return list(session.messages), 0

        keep_count = max(1, memory_window // 2)
        if len(session.messages) <= keep_count:
            return [], keep_count

        start = session.last_consolidated
        end = len(session.messages) - keep_count
        if end <= start:
            return [], keep_count

        return session.messages[start:end], keep_count

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
        """把消息列表格式化成适合归档模型阅读的转录文本。"""
        lines: list[str] = []
        for message in messages:
            content = message.get("content")
            if not content:
                continue
            tools = message.get("tools_used") or []
            tool_suffix = f" [使用工具: {', '.join(tools)}]" if tools else ""
            timestamp = str(message.get("timestamp", "?"))[:16]
            lines.append(f"[{timestamp}] {message['role'].upper()}{tool_suffix}: {content}")
        return lines

    @staticmethod
    def _normalize_tool_args(arguments: Any) -> dict[str, Any] | None:
        """把模型返回的工具参数统一规整成字典。"""
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return None

        if isinstance(arguments, list):
            arguments = arguments[0] if arguments and isinstance(arguments[0], dict) else None

        return arguments if isinstance(arguments, dict) else None

    @staticmethod
    def _coerce_text(value: Any) -> str | None:
        """把工具结果字段规范成字符串，便于直接写文件。"""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)
