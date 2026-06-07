"""Thread API 请求/响应结构。

API 层统一用 `thread`（与 Codex / OpenAI Responses API 对齐），
底层存储仍是 `Session` / `SessionManager`，由 router 层做映射。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ThreadSummary(Base):
    """列表里返回的轻量元信息。"""

    name: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    title: Optional[str] = None
    pinned: bool = False
    archived: bool = False


class ThreadMessage(Base):
    """单条历史消息。"""

    id: str
    role: str
    content: str
    timestamp: Optional[datetime] = None
    tools_used: list[str] = Field(default_factory=list)


class ThreadDetail(Base):
    """单个 thread 的完整信息（包含消息历史）。"""

    name: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    messages: list[ThreadMessage] = Field(default_factory=list)
    title: Optional[str] = None
    pinned: bool = False
    archived: bool = False


class ThreadCreate(Base):
    """POST /api/threads 的 body。"""

    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[\w\-\.\u4e00-\u9fa5 ]+$",
        description="thread 名称(将作为 URL 段)",
    )


class ThreadUpdate(Base):
    """PATCH /api/threads/{name} 的 body,所有字段可选(部分更新语义)。"""

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[\w\-\.\u4e00-\u9fa5 ]+$",
        description="改名(更新 URL 段)",
    )
    title: Optional[str] = Field(
        default=None,
        max_length=256,
        description="thread 显示标题",
    )
    pinned: Optional[bool] = Field(default=None)
    archived: Optional[bool] = Field(default=None)
