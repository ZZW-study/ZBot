"""会话持久化与缓存管理。

会话文件采用 `jsonl` 格式：
1. 第一行是 metadata。
2. 后续每行是一条消息。

这样既方便直接追加/读取，也方便在出问题时人工排查。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config import get_legacy_sessions_dir
from nanobot.utils.helpers import ensure_dir, safe_filename


_HISTORY_FIELDS = ("tool_calls", "tool_call_id", "name")


@dataclass
class Session:
    """单个会话的内存态表示。"""

    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """向会话追加一条完整消息，并自动更新时间戳。"""
        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                **kwargs,
            }
        )
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """返回适合送给模型的历史消息。

        这里会做两件事：
        1. 只取尚未被记忆归档的那部分消息。
        2. 如果截断后前面不是 user 消息，就继续向后裁到第一条 user，
           避免把半截工具链或 assistant 回复直接暴露给模型。
        """
        messages = self.messages[self.last_consolidated :][-max_messages:]
        first_user = next((index for index, message in enumerate(messages) if message.get("role") == "user"), None)
        if first_user is not None:
            messages = messages[first_user:]

        history: list[dict[str, Any]] = []
        for message in messages:
            entry = {"role": message["role"], "content": message.get("content", "")}
            for field in _HISTORY_FIELDS:
                if field in message:
                    entry[field] = message[field]
            history.append(entry)
        return history

    def clear(self) -> None:
        """清空会话正文，但保留 key 和基础元信息。"""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """负责会话文件的读写、缓存和旧目录迁移。"""

    def __init__(self, workspace: Path | str):
        self.sessions_dir = ensure_dir(Path(workspace) / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

    def get_or_create(self, key: str) -> Session:
        """优先从缓存取会话，没有则从磁盘加载，再不行就创建新会话。"""
        session = self._cache.get(key)
        if session is None:
            session = self._load(key) or Session(key=key)
            self._cache[key] = session
        return session

    def save(self, session: Session) -> None:
        """把会话完整写回磁盘，并刷新缓存。"""
        path = self._session_path(session.key)
        lines = [json.dumps(self._metadata_line(session), ensure_ascii=False)]
        lines.extend(json.dumps(message, ensure_ascii=False) for message in session.messages)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """让指定会话在下次访问时强制从磁盘重载。"""
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """扫描当前工作区中的所有会话，并按更新时间倒序返回。"""
        sessions: list[dict[str, Any]] = []
        for path in self.sessions_dir.glob("*.jsonl"):
            metadata = self._read_metadata(path)
            if metadata:
                sessions.append(metadata)
        return sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)

    def _load(self, key: str) -> Session | None:
        """从磁盘读取单个会话。

        如果工作区里还没有该会话，会先尝试把旧目录中的历史文件迁移过来。
        """
        path = self._session_path(key)
        if not path.exists():
            self._migrate_legacy_session(key, path)
        if not path.exists():
            return None

        try:
            metadata: dict[str, Any] = {}
            messages: list[dict[str, Any]] = []
            created_at: datetime | None = None
            updated_at: datetime | None = None
            last_consolidated = 0

            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("_type") == "metadata":
                    metadata = data.get("metadata", {})
                    created_at = self._parse_datetime(data.get("created_at"))
                    updated_at = self._parse_datetime(data.get("updated_at"))
                    last_consolidated = data.get("last_consolidated", 0)
                    continue
                messages.append(data)

            now = datetime.now()
            return Session(
                key=key,
                messages=messages,
                created_at=created_at or now,
                updated_at=updated_at or created_at or now,
                metadata=metadata,
                last_consolidated=last_consolidated,
            )
        except Exception as exc:
            logger.warning("加载会话 {} 失败：{}", key, exc)
            return None

    def _migrate_legacy_session(self, key: str, path: Path) -> None:
        """把旧目录中的会话文件移动到当前工作区目录。"""
        legacy_path = self._legacy_session_path(key)
        if not legacy_path.exists():
            return
        try:
            shutil.move(str(legacy_path), str(path))
            logger.info("已迁移旧版会话 {}", key)
        except Exception:
            logger.exception("迁移旧版会话 {} 失败", key)

    def _session_path(self, key: str) -> Path:
        """把会话 key 转成当前目录下的安全文件名。"""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _legacy_session_path(self, key: str) -> Path:
        """计算旧版会话目录中的路径。"""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    @staticmethod
    def _metadata_line(session: Session) -> dict[str, Any]:
        """生成 jsonl 第一行的 metadata 结构。"""
        return {
            "_type": "metadata",
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "last_consolidated": session.last_consolidated,
        }

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        """安全解析 ISO 时间字符串。"""
        return datetime.fromisoformat(value) if value else None

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, Any] | None:
        """只读取会话第一行 metadata，用于列表页快速展示。

        这里故意不完整解析整个文件，避免仅仅为了列出会话就把所有消息都读一遍。
        """
        try:
            first_line = path.read_text(encoding="utf-8").splitlines()[0].strip()
        except Exception:
            return None

        if not first_line:
            return None

        try:
            data = json.loads(first_line)
        except json.JSONDecodeError:
            return None

        if data.get("_type") != "metadata":
            return None

        return {
            "key": data.get("key") or path.stem.replace("_", ":", 1),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "path": str(path),
        }
