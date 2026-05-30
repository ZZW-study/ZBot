from __future__ import annotations

from types import SimpleNamespace

from ZBot.agent.tools.mcp import _resolve_transport_type


def test_resolve_transport_type_uses_explicit_type():
    cfg = SimpleNamespace(type="sse", command="npx", args=["server"], url="")
    assert _resolve_transport_type(cfg) == "sse"


def test_resolve_transport_type_accepts_transport_alias():
    cfg = {"transport": "stdio", "command": "npx", "args": ["server"]}
    assert _resolve_transport_type(cfg) == "stdio"


def test_resolve_transport_type_infers_stdio_from_command():
    cfg = SimpleNamespace(type=None, command="npx", args=["server"], url="")
    assert _resolve_transport_type(cfg) == "stdio"


def test_resolve_transport_type_infers_http_from_url():
    cfg = SimpleNamespace(type=None, command="", args=[], url="https://example.com/mcp")
    assert _resolve_transport_type(cfg) == "streamableHttp"
