# 长期记忆
# 就是写入一个md文档，提供读取、写入的方法，读取的话，直接读取完整的内容，写入，则调用大模型来写入。
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from loguru import logger

from ZBot.config.schema import Config
from ZBot.prompts.memory_prompts import (
    LONG_TERM_MEMORY_SYSTEM_PROMPT,
    SAVE_LONG_TERM_MEMORY_TOOL,
    build_long_term_memory_prompt,
)
from ZBot.services.formatting.tools import normalize_tool_args

if TYPE_CHECKING:
    from ZBot.providers.base import LLMProvider


class LongTermMemoryStore:
    """长期记忆，复制从日常记忆中提取召回次数多的信息"""

    _instance: Optional["LongTermMemoryStore"] = None

    def __new__(cls, workspace_path: Path):
        """创建或复用长期记忆存储单例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls.store_path = workspace_path / "memory" / "LONG_TERM_MEMORY.md"
        return cls._instance

    async def get_long_term_memory_context(self) -> str:
        """返回适合直接注入 prompt 的长期记忆文本,给上下文构造用的。"""
        long_term_memory = await self._read_long_term()
        return f"## LONG_TERM_MEMORY.md\n{long_term_memory}" if long_term_memory else ""

    async def write_long_term_memory(
        self, provider: LLMProvider, model: str, filtered_daily_memory: list[dict[str, str]]
    ) -> bool:
        """追加写入 `LONG_TERM_MEMORY.md`。Path.write_text() 方法在文件不存在时会自动创建文件"""
        merged_filtered_daily_memory = "\n---\n".join(
            f"- 会话名字:{entry['session_name']}\n- 日常记忆内容:{entry['content']}" for entry in filtered_daily_memory
        )
        long_term_memory = await self._generate_long_term_memory(provider, model, merged_filtered_daily_memory)

        # 将更新后的长期记忆内容写入文件
        try:
            await asyncio.to_thread(self.store_path.write_text, long_term_memory, encoding="utf-8")
            logger.info("长期记忆已成功更新。")
            return True

        except Exception as e:
            logger.error(f"写入长期记忆文件失败: {e}")
            return False

    async def _generate_long_term_memory(
        self, provider: LLMProvider, model: str, merged_filtered_daily_memory: str
    ) -> str:
        """调用模型生成新的长期记忆内容。"""
        old_long_term_memory = await self._read_long_term()  # 读取现有的长期记忆内容
        prompt = self._build_long_term_memory_prompt(old_long_term_memory, merged_filtered_daily_memory)

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": LONG_TERM_MEMORY_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=SAVE_LONG_TERM_MEMORY_TOOL,
                model=model,
            )
        except Exception as e:
            logger.error(f"调用模型生成长期记忆失败: {e}")
            return ""

        if not response.has_tool_calls:
            logger.error("模型响应中缺少工具调用，无法生成长期记忆。")
            return ""

        args = normalize_tool_args(response.tool_calls[0].arguments)
        if args is None or "long_term_memory" not in args:
            logger.error("工具调用参数缺失或格式不正确，无法生成长期记忆。")
            return ""

        return args["long_term_memory"]

    def _build_long_term_memory_prompt(self, old_memory: str, new_memory: str) -> str:
        """构建提示词，指导模型如何更新长期记忆。"""
        return build_long_term_memory_prompt(old_memory, new_memory)

    async def _read_long_term(self) -> str:
        """读取 `LONG_TERM_MEMORY.md` 的内容，如果文件不存在或为空，则返回空字符串。"""
        if not self.store_path.exists():
            return ""
        return await asyncio.to_thread(self.store_path.read_text, encoding="utf-8")


# 全局单例
config = Config()
long_term_memory_store = LongTermMemoryStore(config.workspace_path)
