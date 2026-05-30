from __future__ import annotations

from datetime import datetime

import pytest

from ZBot.backend.routers import agent as agent_router
from ZBot.config.schema import Config
from ZBot.service.config_service import config_cache
from ZBot.session.manager import Session, SessionManager


@pytest.fixture
def temp_config(tmp_path):
    config = Config(model="deepseek-chat", provider="deepseek", workspace=str(tmp_path))
    config.providers.deepseek.api_key = "test_key"
    config.providers.deepseek.api_base = "https://api.deepseek.com/v1"
    config_cache._cached = config
    config_cache._cached_at = 10**9
    yield config
    config_cache.invalidate()


@pytest.mark.asyncio
async def test_get_session_detail_returns_display_messages_only(temp_config):
    manager = SessionManager(temp_config.workspace_path)
    session = Session(session_name="ui_history")
    session.messages.extend(
        [
            {"role": "system", "content": "internal"},
            {"role": "user", "content": "hello", "timestamp": "2026-05-30T10:00:00"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1"}]},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "hi", "tools_used": ["search"]},
        ]
    )
    await manager.save(session)

    response = await agent_router.get_session_detail("ui_history")

    assert response["name"] == "ui_history"
    assert response["message_count"] == 2
    assert [message["role"] for message in response["messages"]] == ["user", "assistant"]
    assert response["messages"][0]["content"] == "hello"
    assert response["messages"][1]["content"] == "hi"
    assert response["messages"][1]["tools_used"] == ["search"]


@pytest.mark.asyncio
async def test_get_session_detail_creates_empty_missing_session(temp_config):
    response = await agent_router.get_session_detail("missing_session")

    assert response["name"] == "missing_session"
    assert response["message_count"] == 0
    assert response["messages"] == []


def test_session_detail_formats_multimodal_user_content():
    session = Session(
        session_name="multimodal",
        created_at=datetime(2026, 5, 30, 10, 0, 0),
        updated_at=datetime(2026, 5, 30, 10, 0, 0),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look at this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ],
    )

    detail = agent_router._session_detail(session)

    assert detail["messages"][0]["content"] == "look at this\n[image]"
