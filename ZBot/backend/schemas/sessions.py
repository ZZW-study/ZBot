"""Session API 请求/响应结构。

底层存储是 `Session` / `SessionManager`(`ZBot.session.manager`),与 Codex /
OpenAI Responses API 保持概念对齐:对外暴露为 session 资源,统一走 `/api/sessions/*`。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    """API schema 基类:snake_case 与 camelCase 双向识别,序列化时输出 camelCase。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SessionSummary(Base):
    """列表里返回的轻量元信息。"""

    name: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SessionMessage(Base):
    """单条历史消息。"""

    id: str
    role: str
    content: str
    timestamp: Optional[datetime] = None
    tools_used: list[str] = Field(default_factory=list)


class SessionDetail(Base):
    """单个 session 的完整信息(包含消息历史)。"""

    name: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    messages: list[SessionMessage] = Field(default_factory=list)


class SessionCreate(Base):
    """POST /api/sessions 的 body。"""

    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[\w\-\.一-龥 ]+$",
        description="session 名称(将作为 URL 段)",
    )


class SessionUpdate(Base):
    """PATCH /api/sessions/{name} 的 body,所有字段可选(部分更新语义)。

    底层 `Session` 不持有 title/pinned/archived 之类的增强元数据,
    因此当前 PATCH 仅支持 `name` 重命名。
    """

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[\w\-\.一-龥 ]+$",
        description="改名(更新 URL 段)",
    )
