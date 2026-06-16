"""/api/mcp/* 路由: 提供后端 agent bundle 上 MCP 连接状态的只读视图。

ZBot 改: 前端在 App 启动时调用此端点, 缓存 MCP 连接状态到 localStorage,
避免每次 sendMessage 都要重新连接 MCP 工具。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ZBot.backend.agent_service_pool import get_current_agent_service

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/status")
async def mcp_status() -> dict[str, Any]:
    """返回当前共享 AgentRunService 持有的 MCP 连接状态。"""
    service = get_current_agent_service()
    if service is None:
        return {"connected": False, "connecting": False, "servers": []}

    bundle = getattr(service, "bundle", None)
    if bundle is None:
        return {"connected": False, "connecting": False, "servers": []}

    agent = getattr(bundle, "agent", None)
    connected = bool(getattr(agent, "_mcp_connected", False))
    connecting = bool(getattr(agent, "_mcp_connecting", False))

    mcp_servers = []
    try:
        cfg = getattr(bundle, "runtime_config", None)
        servers = getattr(cfg, "mcp_servers", None) or {}
        mcp_servers = list(servers.keys())
    except Exception:
        mcp_servers = []

    return {
        "connected": connected,
        "connecting": connecting,
        "servers": mcp_servers,
    }
