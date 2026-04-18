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

from ZBot.utils.helpers import ensure_dir, safe_filename

# 历史消息中需要特别保留的字段
# 这些字段在转换历史记录时需要特殊处理
_HISTORY_FIELDS = ("tool_calls", "tool_call_id", "name")


@dataclass
class Session:
    """单个会话对象。"""

    session_name: str                                               # 会话名称
    messages: list[dict[str, Any]] = field(default_factory=list)    # 消息列表
    created_at: datetime = field(default_factory=datetime.now)      # 创建时间，打印才是年-月-日-时-分-秒，不然就是datatime对象，如果要保存不能用这个，必须在后面加isoformat（），变成字符串对象，保存
    updated_at: datetime = field(default_factory=datetime.now)      # 更新时间
    last_consolidated: int = 0                                      # 已归档的消息索引（用于长期记忆）

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """
        向会话追加消息。
        Args:
            role: 消息角色（"user"、"assistant"、"tool"）
            content: 消息内容
            **kwargs: 其他可选字段（如 tool_calls、tool_call_id 等）
        """
        self.messages.append(
            {
                "role": role,                              
                "content": content,                         
                "timestamp": datetime.now().isoformat(),    # 时间戳
                **kwargs,                                  
            }
        )
        # 更新最后修改时间
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 25) -> list[dict[str, Any]]:
        """返回历史消息列表（用于构造模型上下文）。"""
        # 从上次归档位置到末尾，再取最近的 max_messages 条
        messages = self.messages[self.last_consolidated :][-max_messages:]

        # 找到第一条 user 消息的位置,  next(..., None)：取生成器的第一个结果；没找到就返回 None，不抛异常。--生成器表达式，生成器函数
        first_user = next((index for index, message in enumerate(messages) if message.get("role") == "user"), None)
        if first_user is not None:
            # 从第一条 user 消息开始截断
            messages = messages[first_user:]

        history: list[dict[str, Any]] = []
        for message in messages:
            # 构造标准格式的消息条目
            entry = {"role": message["role"], "content": message.get("content", "")}
            # 额外保留特殊字段（如工具调用信息）
            for f in _HISTORY_FIELDS:
                if f in message:
                    entry[f] = message[f]
            history.append(entry)
        return history

    def clear(self) -> None:
        """清空会话。"""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    会话文件管理器。
    """

    def __init__(self, workspace: Path | str):
        """初始化 SessionManager"""
        self.sessions_dir = ensure_dir(Path(workspace) / "sessions")
        # 内存缓存：key -> Session 映射，用于加速频繁访问
        self._cache: dict[str, Session] = {}


    async def get_or_create(self, session_name: str) -> Session:
        """获取或创建会话。先从缓存查找，如果没有则从磁盘加载；如果磁盘上也没有，则创建一个新的空会话。"""
        session = self._cache.get(session_name)
        if session is None:
            session = await self._load(session_name) or Session(session_name=session_name)
            self._cache[session_name] = session
        return session


    async def save(self, session: Session) -> None:
        """保存会话到磁盘。"""
        path: Path = self._session_path(session.session_name)
        lines: list[str] = [json.dumps(self._metadata_line(session), ensure_ascii=False)]
        lines.extend(json.dumps(message, ensure_ascii=False) for message in session.messages)
        # asyncio.to_thread：将同步 IO 操作放到线程池执行，避免阻塞事件循环
        # 原理：
        #   1. Python 事件循环自带默认线程池，首次使用时自动创建
        #   2. to_thread 会从线程池取一个线程，在其中执行同步函数
        #   3. 主协程 await 等待线程完成，期间事件循环可处理其他协程
        #   4. 线程完成后返回结果，主协程继续执行
        await asyncio.to_thread(path.write_text, "\n".join(lines) + "\n", encoding="utf-8")
        self._cache[session.session_name] = session


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
            last_consolidated = 0

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
            )
        except Exception as exc:
            logger.warning("加载会话失败 {}: {}", session_name, exc)
            return None

    def _session_path(self, session_name: str) -> Path:
        """返回会话文件的完整路径。"""
        safe_name = safe_filename(session_name)  # 转义非法字符
        return self.sessions_dir / f"{safe_name}.jsonl"

    @staticmethod
    def _metadata_line(session: Session) -> dict[str, Any]:
        """
        生成元数据行的字典。元数据包含会话的基本信息，但不包含大量消息内容，便于快速读取和使用。
        """
        return {
            "_type": "metadata",          # 标记这是元数据行
            "name": session.session_name, # 会话名称
            "created_at": session.created_at.isoformat(),  # 创建时间
            "updated_at": session.updated_at.isoformat(),  # 更新时间
            "last_consolidated": session.last_consolidated,  # 归档索引
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