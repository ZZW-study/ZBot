"""会话持久化管理。

这个模块负责管理对话会话（Session）的：
1. 内存缓存：加速频繁访问
2. 磁盘持久化：使用 JSONL 格式存储
3. 生命周期管理：创建、加载、保存、删除

文件格式：
- 每个会话存储在独立的 .jsonl 文件中
- 第一行是 metadata 元数据
- 后续每行是一条消息（JSON 格式）
- 优点：易于追加写入，适合对话历史场景

核心类：
    Session: 单个会话对象，包含消息列表和元信息
    SessionManager: 会话管理器，负责多会话的 CRUD 操作
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from ZBot.service.utils.helpers import ensure_dir, safe_filename
from ZBot.providers.base import LLMProvider

@dataclass
class Session:
    """单个会话对象。"""

    session_name: str  # 会话名称
    messages: list[dict[str, Any]] = field(default_factory=list)  # 消息列表
    # 保存时需要通过 isoformat 转为字符串。
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)  # 更新时间
    last_consolidated: int = 0  # 已归档的消息索引（用于会话记忆）
    memory_snapshot: str | None = None  # 记忆快照（归档时保存的摘要信息）

    async def get_history_by_token_budget(
        self,
        token_budget: int,
        provider: LLMProvider,
        model: str
    ) -> list[dict[str, Any]]:
        """按 token 预算返回最近历史，超出部分压缩后补充到当前上下文中。"""
        messages = self.messages[self.last_consolidated:]
        if not messages:
            return []

        selected: list[dict[str, Any]] = []
        used_tokens = 0
        is_exceed: bool = False
        message_count: int = 0

        for message in reversed(messages):
            cost = self._estimate_message_tokens(message)
            if selected and used_tokens + cost > token_budget:
                is_exceed = True
                break

            selected.append(message.copy())
            message_count += 1
            used_tokens += cost

        selected.reverse()

        if is_exceed:
            # 如果截取后的第一条不是 user，则继续删除前面的 assistant/tool 消息，
            # 保证上下文从一条完整的用户消息开始。
            selected = self.find_first_user(selected)

            if not selected:
                return []

            # selected 之前的所有消息都属于本次被裁掉、需要压缩的信息。
            first_selected_index = messages.index(selected[0])
            not_selected = messages[:first_selected_index]

            if not_selected:
                prompt: list[dict[str, Any]] = self.build_prompt(not_selected)

                response = await provider.chat(
                    messages=prompt,
                    model=model
                )

                summary = response.content

                if summary:
                    original_content = selected[0].get("content", "")
                    selected[0]["content"] = (
                        f"【前置对话摘要】\n{summary}\n\n"
                        f"【当前用户消息】\n{original_content}"
                    )
                    
        return selected

    def clear(self) -> None:
        """清空会话。"""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()
        self.memory_snapshot = None

    @staticmethod
    def _estimate_message_tokens(message: dict[str, Any]) -> int:
        """粗略估算单条消息 token，和 Agent loop 的轻量估算保持同一思路。"""
        total_chars = len(str(message.get("role", ""))) + len(str(message.get("content", "")))
        if "tool_calls" in message:
            total_chars += len(json.dumps(message["tool_calls"], ensure_ascii=False))
        if "tool_call_id" in message:
            total_chars += len(str(message["tool_call_id"]))
        return max(1, total_chars // 2)

    @staticmethod
    def build_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """构建提示词，用来压缩之前的对话，避免上下文过大，又防止信息丢失。"""

        history_text = json.dumps(
            messages,
            ensure_ascii=False,
            indent=2,
            default=str
        )

        return [
            {
                "role": "system",
                "content": (
                    "你是一个对话上下文压缩器。"
                    "你的任务是将较早的历史对话压缩成一段简洁但信息完整的摘要，"
                    "供后续对话继续使用。\n\n"
                    "要求：\n"
                    "1. 保留用户的核心问题、明确要求、限制条件和目标；\n"
                    "2. 保留已经确定的重要结论、关键参数、代码设计和修改决定；\n"
                    "3. 保留尚未完成、后续仍需继续处理的事项；\n"
                    "4. 删除重复内容、寒暄和无关细节；\n"
                    "5. 不要回答问题，不要扩展新内容，不要编造信息；\n"
                    "6. 直接输出摘要内容，不要添加“摘要如下”等开场语。"
                )
            },
            {
                "role": "user",
                "content": (
                    "请压缩下面这些较早的历史对话，使后续模型在看不到原始内容时，"
                    "仍能继续准确完成当前任务：\n\n"
                    f"{history_text}"
                )
            }
        ]


    @staticmethod
    def find_first_user(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """返回从第一条 user 消息开始的后续全部消息。"""
        for index, message in enumerate(messages):
            if message.get("role") == "user":
                return messages[index:]

        return []


class SessionManager:
    """
    会话文件管理器。
    """

    def __init__(self, workspace: Path | str):
        """初始化 SessionManager"""
        self.sessions_dir = ensure_dir(Path(workspace) / "sessions")
        # 内存缓存：key -> Session 映射，用于加速频繁访问
        self._cache: dict[str, Session] = {}

    async def get_or_create(self, session_name: str) -> tuple[Session, bool]:
        """获取或创建会话。先从缓存查找，如果没有则从磁盘加载；如果磁盘上也没有，则创建一个新的空会话。"""
        session = self._cache.get(session_name)
        if session is None:
            session = await self._load(session_name)
            if session:
                return session, True  # 加载成功，返回会话和标记
            session = Session(session_name=session_name)  # 创建新会话
            self._cache[session_name] = session
        return session, False  # 返回会话和标记，标记为False表示新创建的会话

    async def save(self, session: Session) -> None:
        """保存会话到磁盘,同一会话名字，都是追加写入。"""
        path: Path = self._session_path(session.session_name)
        lines: list[str] = [json.dumps(self._metadata_line(session), ensure_ascii=False)]
        lines.extend(json.dumps(message, ensure_ascii=False) for message in session.messages)

        # asyncio.to_thread：将同步 IO 操作放到线程池执行，避免阻塞事件循环
        # 原理：
        #   1. Python 事件循环自带默认线程池，首次使用时自动创建
        #   2. to_thread 会从线程池取一个线程，在其中执行同步函数
        #   3. 主协程 await 等待线程完成，期间事件循环可处理其他协程
        #   4. 线程完成后返回结果，主协程继续执行
        def write_file():
            """在线程池中把会话内容追加写入磁盘。"""
            with path.open("w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

        await asyncio.to_thread(write_file)
        self._cache[session.session_name] = session

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

    async def rename(self, old_name: str, new_name: str) -> bool:
        """重命名会话。

        Args:
            old_name: 原会话名称
            new_name: 新会话名称

        Returns:
            True 表示重命名成功，False 表示原会话不存在或新名称已存在
        """
        old_path: Path = self._session_path(old_name)
        new_path: Path = self._session_path(new_name)

        if not old_path.exists():
            return False
        if new_path.exists():
            return False

        def rename_file():
            old_path.rename(new_path)

        await asyncio.to_thread(rename_file)

        # 更新缓存
        session = self._cache.pop(old_name, None)
        if session:
            session.session_name = new_name
            session.updated_at = datetime.now()
            self._cache[new_name] = session

        # 更新文件内的元数据
        await self._update_metadata_name(new_path, new_name)
        return True

    async def _update_metadata_name(self, path: Path, new_name: str) -> None:
        """更新 JSONL 文件第一行的元数据名称。"""

        def _rewrite():
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                return
            try:
                metadata = json.loads(lines[0])
                if metadata.get("_type") == "metadata":
                    metadata["name"] = new_name
                    metadata["updated_at"] = datetime.now().isoformat()
                    lines[0] = json.dumps(metadata, ensure_ascii=False)
                    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except Exception:
                pass

        await asyncio.to_thread(_rewrite)

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

    async def _load(self, session_name: str) -> Session | None:
        """从磁盘加载会话。"""
        path = self._session_path(session_name)
        if not path.exists():
            return None

        try:
            # 异步读取文件内容
            content = await asyncio.to_thread(path.read_text, encoding="utf-8")
            messages: list[dict[str, Any]] = []
            created_at: datetime | None = None
            updated_at: datetime | None = None
            last_consolidated: int = 0
            memory_snapshot: str | None = None

            # 逐行解析 JSONL 文件
            for line in content.splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)

                # 第一行是元数据（_type == "metadata"）
                if data.get("_type") == "metadata":
                    created_at = self._parse_datetime(data.get("created_at"))
                    updated_at = self._parse_datetime(data.get("updated_at"))
                    last_consolidated = data.get("last_consolidated", 0)
                    memory_snapshot = data.get("memory_snapshot")
                    continue

                # 其他行是消息记录
                messages.append(data)

            # 构造 Session 对象，时间字段若无则用当前时间
            now = datetime.now()
            return Session(
                session_name=session_name,
                messages=messages,
                created_at=created_at or now,
                updated_at=updated_at or created_at or now,
                last_consolidated=last_consolidated,
                memory_snapshot=memory_snapshot,
            )
        except json.JSONDecodeError as exc:
            logger.error("加载会话失败 {}：JSON 解析错误（文件可能损坏）: {}", session_name, exc)
            return None
        except (PermissionError, OSError) as exc:
            logger.error("加载会话失败 {}：文件读取错误: {}", session_name, exc)
            return None
        except (ValueError, KeyError, TypeError) as exc:
            logger.error("加载会话失败 {}：数据格式错误: {}", session_name, exc)
            return None

    def _session_path(self, session_name: str) -> Path:
        """返回会话文件的完整路径。"""
        safe_name = safe_filename(session_name)  # 转义非法字符
        return self.sessions_dir / f"{safe_name}.jsonl"

    @staticmethod
    def _metadata_line(session: Session) -> dict[str, Any]:
        """
        构造会话导出元数据。

        导出文件仅保留记忆快照及尚未归档的消息，因此导入后消息索引将
        从 0 重新开始，`last_consolidated` 必须重置为 0；否则会误将
        部分未归档消息视为已处理消息并跳过。
        """
        return {
            "_type": "metadata",
            "name": session.session_name,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "last_consolidated": 0,
            "memory_snapshot": session.memory_snapshot,
        }


    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        """
        解析 ISO 格式的时间字符串。

        Args:
            value: ISO 格式的时间字符串（如 "2024-01-15T14:30:00"）

        Returns:
            datetime 对象，如果值为 None 则返回 None
        """
        return datetime.fromisoformat(value) if value else None
