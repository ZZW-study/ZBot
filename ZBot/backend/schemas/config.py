"""Config API 请求/响应结构。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ConfigStatusResponse(Base):
    """GET /api/config/status 响应(轻量健康检查)。"""

    exists: bool
    configured: bool
    model: str = ""
    provider: str = ""
    reason: str = ""


class ProviderConfigPayload(Base):
    """单个 provider 配置(API key 已被脱敏)。"""

    api_key: str = Field(default="", alias="apiKey")
    api_base: str = Field(default="", alias="apiBase")


class ConfigResponse(Base):
    """GET /api/config 响应:完整配置,API key 已脱敏。"""

    model: str
    provider: str
    resolved_provider: Optional[str] = None
    configured: bool = False
    reason: str = ""
    providers: dict[str, ProviderConfigPayload] = Field(default_factory=dict)
    workspace: str = ""
    max_tokens: int = 4096
    temperature: float = 0.1
    reasoning_effort: Optional[str] = None
    has_key: bool = False

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ConfigPatch(Base):
    """PATCH /api/config body:部分更新(merge 语义)。

    嵌套结构也允许部分更新,空 apiKey 表示保留旧值(由 merge_config_patch 实现)。
    """

    model: Optional[str] = None
    provider: Optional[str] = None
    workspace: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    reasoning_effort: Optional[str] = None
    providers: Optional[dict[str, ProviderConfigPayload]] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ConfigSavedResponse(Base):
    """PUT/PATCH /api/config 响应:保存后的关键状态。"""

    configured: bool
    model: str
    provider: str
    reason: str = ""
