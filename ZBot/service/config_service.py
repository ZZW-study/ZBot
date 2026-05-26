"""配置管理服务：TTL 缓存加载、配置合并、provider 状态校验。"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from ZBot.config.loader import load_config
from ZBot.config.schema import Config
from ZBot.service.utils.config_utils import is_masked_or_empty_key

# 各 provider 的默认 API Base，方便前端预填
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_base": "https://api.deepseek.com/v1",
        "model_placeholder": "deepseek-chat",
    },
    "openrouter": {
        "api_base": "https://openrouter.ai/api/v1",
        "model_placeholder": "openrouter/anthropic/claude-sonnet-4",
    },
    "dashscope": {
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_placeholder": "qwen-plus",
    },
    "siliconflow": {
        "api_base": "https://api.siliconflow.cn/v1",
        "model_placeholder": "deepseek-ai/DeepSeek-V3",
    },
}


class ConfigCache:
    """TTL 缓存的配置加载器，避免每次 HTTP 请求都读磁盘。"""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl_seconds = ttl_seconds
        self._cached: Config | None = None
        self._cached_at: float = 0.0

    def get(self) -> Config | None:
        """返回缓存的配置，或从磁盘重新加载。"""
        now = time.monotonic()
        if self._cached is not None and now - self._cached_at < self._ttl_seconds:
            return self._cached
        self._cached = load_config()
        self._cached_at = now
        return self._cached

    def invalidate(self) -> None:
        """清除缓存（save_config 后调用）。"""
        self._cached = None
        self._cached_at = 0.0


config_cache = ConfigCache()


def merge_config_patch(current: Config, patch: dict[str, Any]) -> Config:
    """把前端局部配置合并进当前配置，避免覆盖未展示的高级配置。"""
    data = current.model_dump(by_alias=True)

    for key, value in patch.items():
        if key == "providers":
            continue
        data[key] = value

    incoming_providers = patch.get("providers")
    if isinstance(incoming_providers, dict):
        providers = data.setdefault("providers", {})
        for provider_name, provider_patch in incoming_providers.items():
            if not isinstance(provider_patch, dict):
                continue
            existing = providers.setdefault(provider_name, {})
            for key, value in provider_patch.items():
                if key == "apiKey" and is_masked_or_empty_key(value):
                    continue
                existing[key] = value

    return Config.model_validate(data)


def resolved_provider_status(config: Config) -> tuple[bool, str, str]:
    """按当前 model/provider 解析实际使用的 provider，并判断关键字段是否齐全。"""
    provider_config, provider_name, _is_gateway = config.get_provider(config.model)
    if not config.model or not provider_config or not provider_name:
        return False, provider_name or config.provider, "未能按当前模型匹配到 provider。"
    if not provider_config.api_key:
        return False, provider_name, f"{provider_name} 缺少 API Key。"
    if not provider_config.api_base:
        return False, provider_name, f"{provider_name} 缺少 API Base URL。"
    return True, provider_name, ""
