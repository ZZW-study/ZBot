"""Tests for /api/config/* endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# status / defaults (always available, no config required)
# ---------------------------------------------------------------------------

def test_status_returns_200(client: TestClient, isolated_config):
    r = client.get("/api/config/status")
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["configured"] is False


def test_defaults_returns_provider_dict(client: TestClient, isolated_config):
    r = client.get("/api/config/defaults")
    assert r.status_code == 200
    body = r.json()
    assert "deepseek" in body
    assert "openrouter" in body
    assert "api_base" in body["deepseek"]


# ---------------------------------------------------------------------------
# GET (requires config file)
# ---------------------------------------------------------------------------

def test_get_missing_returns_404(client: TestClient, isolated_config):
    r = client.get("/api/config")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_get_existing_returns_masked_config(client: TestClient, isolated_config):
    # Pre-populate the temp config file directly
    _write_raw_config(
        isolated_config,
        {
            "model": "deepseek-chat",
            "provider": "auto",
            "maxTokens": 2048,
            "temperature": 0.2,
            "providers": {
                "deepseek": {"apiKey": "sk-abcdef1234567890", "apiBase": "https://api.deepseek.com/v1"},
            },
        },
    )
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "deepseek-chat"
    # API key must be masked
    deepseek_key = body["providers"]["deepseek"]["apiKey"]
    assert "*" in deepseek_key
    assert "sk-abcdef1234567890" not in deepseek_key


# ---------------------------------------------------------------------------
# PUT (replace)
# ---------------------------------------------------------------------------

def test_put_writes_file_and_returns_saved(client: TestClient, isolated_config):
    payload = {
        "model": "deepseek-chat",
        "provider": "auto",
        "workspace": "~/.ZBot/workspace",
        "maxTokens": 2048,
        "temperature": 0.2,
        "providers": {
            "deepseek": {"apiKey": "sk-test-1234", "apiBase": "https://api.deepseek.com/v1"},
        },
    }
    r = client.put("/api/config", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "deepseek-chat"
    assert isolated_config.exists()

    # Verify file content
    raw = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert raw["model"] == "deepseek-chat"
    assert raw["maxTokens"] == 2048


def test_put_invalid_config_returns_422(client: TestClient, isolated_config):
    r = client.put("/api/config", json={"model": 123})  # wrong type
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# PATCH (merge)
# ---------------------------------------------------------------------------

def test_patch_partial_update_merges(client: TestClient, isolated_config):
    # Pre-populate the file with maxTokens=2048
    _write_raw_config(
        isolated_config,
        {
            "model": "deepseek-chat",
            "provider": "auto",
            "maxTokens": 2048,
            "temperature": 0.2,
            "providers": {"deepseek": {"apiKey": "sk-test-1234"}},
        },
    )

    # PATCH only model
    r = client.patch("/api/config", json={"model": "qwen-plus"})
    assert r.status_code == 200
    assert r.json()["model"] == "qwen-plus"

    # Verify file content: maxTokens preserved
    raw = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert raw["maxTokens"] == 2048
    assert raw["temperature"] == 0.2
    assert raw["model"] == "qwen-plus"


def test_patch_empty_api_key_preserves_existing(client: TestClient, isolated_config):
    _write_raw_config(
        isolated_config,
        {
            "model": "deepseek-chat",
            "providers": {"deepseek": {"apiKey": "sk-original-1234", "apiBase": "https://api.deepseek.com/v1"}},
        },
    )
    r = client.patch(
        "/api/config",
        json={"providers": {"deepseek": {"apiKey": "****"}}},
    )
    assert r.status_code == 200
    raw = json.loads(isolated_config.read_text(encoding="utf-8"))
    # Original key preserved (not overwritten with mask)
    assert raw["providers"]["deepseek"]["apiKey"] == "sk-original-1234"


def test_patch_invalid_returns_422(client: TestClient, isolated_config):
    r = client.patch("/api/config", json={"maxTokens": "not-a-number"})
    assert r.status_code == 422


def test_patch_when_no_config_creates_one(client: TestClient, isolated_config):
    r = client.patch("/api/config", json={"model": "fresh-model"})
    assert r.status_code == 200
    assert r.json()["model"] == "fresh-model"
    assert isolated_config.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_raw_config(path: Path, data: dict) -> None:
    """Write a raw config dict to the temp file (bypassing the singleton Config)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
