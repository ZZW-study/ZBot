"""ConfigCache 和 merge_config_patch 测试。"""

from __future__ import annotations

import time

from ZBot.config.schema import Config
from ZBot.service.config_service import ConfigCache, merge_config_patch, resolved_provider_status
from ZBot.service.utils.config_utils import is_masked_or_empty_key, mask_key


class TestConfigCache:
    """ConfigCache TTL 缓存测试。"""

    def test_get_returns_cached_config(self):
        """缓存未过期时应返回缓存的配置。"""
        cache = ConfigCache(ttl_seconds=60.0)
        config1 = cache.get()
        config2 = cache.get()
        # 应返回同一对象（未重新加载）
        assert config1 is config2

    def test_get_reloads_after_ttl_expires(self):
        """缓存过期后应重新加载。"""
        cache = ConfigCache(ttl_seconds=0.1)  # 很短的 TTL
        cache.get()

        # 等待 TTL 过期
        time.sleep(0.15)

        config2 = cache.get()
        # Config 是单例，返回同一对象，但 _cached_at 应已更新
        assert cache._cached is config2
        assert cache._cached_at > 0.0

    def test_invalidate_clears_cache(self):
        """invalidate 后应清除缓存。"""
        cache = ConfigCache()
        cache.get()
        cache.invalidate()
        assert cache._cached is None
        assert cache._cached_at == 0.0


class TestMergeConfigPatch:
    """merge_config_patch 配置合并测试。"""

    def test_merge_updates_model(self):
        """合并 patch 应更新 model 字段。"""
        current = Config(model="old_model")
        patched = merge_config_patch(current, {"model": "new_model"})
        assert patched.model == "new_model"

    def test_merge_preserves_unmodified_fields(self):
        """合并 patch 应保留未修改的字段。"""
        current = Config(model="test", temperature=0.5, max_tokens=8192)
        patched = merge_config_patch(current, {"model": "updated"})
        assert patched.model == "updated"
        assert patched.temperature == 0.5  # 未修改，应保留
        assert patched.max_tokens == 8192  # 未修改，应保留

    def test_merge_updates_provider_api_key(self):
        """合并 patch 应更新 provider 的 API key。"""
        current = Config()
        current.providers.deepseek.api_key = "old_key"
        patched = merge_config_patch(current, {"providers": {"deepseek": {"apiKey": "new_key"}}})
        assert patched.providers.deepseek.api_key == "new_key"

    def test_merge_preserves_masked_api_key(self):
        """合并 patch 时，掩码的 API key 应被保留。"""
        current = Config()
        current.providers.deepseek.api_key = "secret_key_123"
        masked = mask_key("secret_key_123")  # 掩码后的值

        # 前端提交掩码的 key，应被忽略（保留原值）
        patched = merge_config_patch(current, {"providers": {"deepseek": {"apiKey": masked}}})
        # 应保留原值，不被掩码值覆盖
        assert patched.providers.deepseek.api_key == "secret_key_123"

    def test_merge_preserves_empty_api_key(self):
        """合并 patch 时，空字符串 API key 应被保留。"""
        current = Config()
        current.providers.deepseek.api_key = ""

        # 前端提交空字符串，应被忽略
        patched = merge_config_patch(current, {"providers": {"deepseek": {"apiKey": ""}}})
        # 应保留原值（空字符串）
        assert patched.providers.deepseek.api_key == ""


class TestResolvedProviderStatus:
    """resolved_provider_status 测试。"""

    def test_missing_model_returns_false(self):
        """未配置 model 时应返回 False。"""
        config = Config(model="")
        is_valid, provider_name, message = resolved_provider_status(config)
        assert is_valid is False
        assert "model" in message.lower() or "provider" in message.lower()

    def test_missing_api_key_returns_false(self):
        """缺少 API key 时应返回 False。"""
        config = Config(model="deepseek-chat")
        config.providers.deepseek.api_key = ""
        config.providers.deepseek.api_base = "https://api.deepseek.com/v1"
        is_valid, provider_name, message = resolved_provider_status(config)
        assert is_valid is False
        assert "api key" in message.lower()

    def test_missing_api_base_returns_false(self):
        """缺少 API base 时应返回 False。"""
        config = Config(model="deepseek-chat")
        config.providers.deepseek.api_key = "test_key"
        config.providers.deepseek.api_base = ""
        is_valid, provider_name, message = resolved_provider_status(config)
        assert is_valid is False
        assert "api base" in message.lower() or "url" in message.lower()

    def test_all_fields_present_returns_true(self):
        """所有字段齐全时应返回 True。"""
        config = Config(model="deepseek-chat")
        config.providers.deepseek.api_key = "test_key"
        config.providers.deepseek.api_base = "https://api.deepseek.com/v1"
        is_valid, provider_name, message = resolved_provider_status(config)
        assert is_valid is True
        assert provider_name == "deepseek"
        assert message == ""


class TestMaskKey:
    """mask_key 工具函数测试。"""

    def test_mask_short_key(self):
        """短 key 应被掩码。"""
        masked = mask_key("abc123")
        assert masked.startswith("abc")
        assert "*" in masked

    def test_mask_long_key(self):
        """长 key 应保留前 4 位，其余掩码。"""
        masked = mask_key("sk-very-long-secret-key-1234567890")
        assert masked.startswith("sk-v")
        assert "****" in masked


class TestIsMaskedOrEmptyKey:
    """is_masked_or_empty_key 工具函数测试。"""

    def test_empty_string_is_masked(self):
        """空字符串应被视为掩码/空。"""
        assert is_masked_or_empty_key("") is True

    def test_string_with_stars_is_masked(self):
        """包含星号的字符串应被视为掩码。"""
        assert is_masked_or_empty_key("sk-****-123") is True

    def test_real_key_is_not_masked(self):
        """真实的 key 不应被视为掩码。"""
        assert is_masked_or_empty_key("sk-real-secret-key-123") is False
