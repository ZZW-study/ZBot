from __future__ import annotations

import litellm

from ZBot.providers.litellm_provider import LiteLLMProvider


def test_dashscope_new_qwen_model_uses_local_context_window(monkeypatch):
    def fail_get_model_info(_model: str):
        raise Exception("not mapped")

    monkeypatch.setattr(litellm, "get_model_info", fail_get_model_info)
    provider = LiteLLMProvider(default_model="qwen3.6-max-preview", provider_name="dashscope")

    assert provider.get_context_window() == 262_144


def test_kimi_model_uses_global_local_context_window(monkeypatch):
    def fail_get_model_info(_model: str):
        raise Exception("not mapped")

    monkeypatch.setattr(litellm, "get_model_info", fail_get_model_info)
    provider = LiteLLMProvider(default_model="kimi-k2.6", provider_name=None)

    assert provider.get_context_window() == 262_144


def test_unknown_model_still_uses_default_context_window(monkeypatch):
    def fail_get_model_info(_model: str):
        raise Exception("not mapped")

    monkeypatch.setattr(litellm, "get_model_info", fail_get_model_info)
    provider = LiteLLMProvider(default_model="unknown-model", provider_name=None)

    assert provider.get_context_window() == 128_000
