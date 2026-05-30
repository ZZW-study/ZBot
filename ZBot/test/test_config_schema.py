"""Config 配置模型与提供商匹配逻辑测试。"""

from __future__ import annotations

import pytest

from ZBot.config.schema import Config, ProviderConfig, ProvidersConfig


class TestConfigDefaults:
    """Config 默认值验证。"""

    def test_default_model_is_empty(self):
        """未配置时 model 应为空字符串。"""
        config = Config()
        assert config.model == ""

    def test_default_provider_is_auto(self):
        """provider 默认值应为 'auto'。"""
        config = Config()
        assert config.provider == "auto"

    def test_default_temperature_within_range(self):
        """temperature 默认值应在 0.0~2.0 之间。"""
        config = Config()
        assert 0.0 <= config.temperature <= 2.0

    def test_default_positive_integers(self):
        """整数配置默认值应为正数。"""
        config = Config()
        assert config.max_tokens > 0
        assert config.agent_timeout_seconds > 0
        assert config.subagent_timeout_seconds > 0


class TestConfigValidators:
    """Config 字段校验器测试。"""

    def test_temperature_too_high_raises(self):
        """temperature > 2.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="temperature"):
            Config(temperature=3.0)

    def test_temperature_too_low_raises(self):
        """temperature < 0.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="temperature"):
            Config(temperature=-0.1)

    def test_max_tokens_zero_raises(self):
        """max_tokens = 0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match=">= 1"):
            Config(max_tokens=0)

    def test_compaction_threshold_too_high_raises(self):
        """context_compaction_threshold > 0.95 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="比例参数"):
            Config(context_compaction_threshold=1.0)


class TestGetProvider:
    """get_provider 匹配逻辑测试。"""

    def test_no_model_returns_none(self):
        """未设置 model 时应返回 (None, None, None)。"""
        config = Config(model="")
        result = config.get_provider()
        assert result == (None, None, None)

    def test_forced_provider_deepseek(self):
        """强制指定 provider='deepseek' 时应返回 deepseek 配置。"""
        config = Config(provider="deepseek")
        config.providers.deepseek.api_key = "test_key"
        config.providers.deepseek.api_base = "https://api.deepseek.com/v1"
        provider_config, name, is_gateway = config.get_provider()
        assert name == "deepseek"
        assert is_gateway is False
        assert provider_config.api_key == "test_key"

    def test_forced_provider_unknown_returns_none(self):
        """强制指定未知 provider 时应返回 (None, None, None)。"""
        config = Config(provider="unknown_provider")
        result = config.get_provider()
        assert result == (None, None, None)

    def test_gateway_prefix_openrouter(self):
        """模型前缀 'openrouter' 应匹配网关提供商。"""
        config = Config(model="openrouter/anthropic/claude")
        config.providers.openrouter.api_key = "test_key"
        provider_config, name, is_gateway = config.get_provider()
        assert name == "openrouter"
        assert is_gateway is True

    def test_keyword_match_deepseek(self):
        """模型名称含 'deepseek' 应匹配标准厂商。"""
        config = Config(model="deepseek-chat")
        config.providers.deepseek.api_key = "test_key"
        provider_config, name, is_gateway = config.get_provider()
        assert name == "deepseek"
        assert is_gateway is False

    def test_keyword_match_qwen(self):
        """模型名称含 'qwen' 应匹配 dashscope。"""
        config = Config(model="qwen-plus")
        config.providers.dashscope.api_key = "test_key"
        provider_config, name, is_gateway = config.get_provider()
        assert name == "dashscope"
        assert is_gateway is False

    def test_no_match_returns_none(self):
        """无法匹配的模型应返回 (None, None, None)。"""
        config = Config(model="some-unknown-model")
        result = config.get_provider()
        assert result == (None, None, None)


class TestConfigSingletonReset:
    """conftest.py 中 Config 单例重置是否生效。"""

    def test_config_instances_are_independent_after_reset(self):
        """每个测试应获得独立的 Config 实例。"""
        config1 = Config()
        config1.model = "test_model_a"

        # 手动重置（conftest 中 autouse fixture 已处理，此处验证机制）
        Config._instance = None

        config2 = Config()
        assert config2.model == ""  # 默认值，不应受 config1 影响
