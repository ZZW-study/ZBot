from __future__ import annotations

import pytest

from ZBot.backend.routers.config import config_status
from ZBot.config.schema import Config
from ZBot.service.config_service import config_cache


@pytest.fixture(autouse=True)
def _clear_config_cache():
    config_cache.invalidate()
    yield
    config_cache.invalidate()


@pytest.mark.asyncio
async def test_config_status_missing_config_marks_exists_false(monkeypatch):
    monkeypatch.setattr(config_cache, "get", lambda: None)

    response = await config_status()

    assert response["exists"] is False
    assert response["configured"] is False


@pytest.mark.asyncio
async def test_config_status_existing_but_invalid_marks_exists_true_configured_false():
    config = Config(model="deepseek-chat", provider="deepseek")
    config.providers.deepseek.api_key = ""
    config.providers.deepseek.api_base = "https://api.deepseek.com/v1"
    config_cache._cached = config
    config_cache._cached_at = 10**9

    response = await config_status()

    assert response["exists"] is True
    assert response["configured"] is False
    assert response["provider"] == "deepseek"
    assert response["reason"]


@pytest.mark.asyncio
async def test_config_status_existing_valid_marks_configured_true():
    config = Config(model="deepseek-chat", provider="deepseek")
    config.providers.deepseek.api_key = "test_key"
    config.providers.deepseek.api_base = "https://api.deepseek.com/v1"
    config_cache._cached = config
    config_cache._cached_at = 10**9

    response = await config_status()

    assert response["exists"] is True
    assert response["configured"] is True
    assert response["provider"] == "deepseek"
