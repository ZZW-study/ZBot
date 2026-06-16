"""ZBot 改: 跨 run 共享的 AgentRunService 单例。

提出到这里是为了打破 backend/app.py 和 backend/routers/mcp.py 之间的
循环导入 (routers/mcp.py 需要 get_current_agent_service, 而 app.py
在 lifespan 里需要 include mcp_router)。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from loguru import logger

from ZBot.services.agent_run.agent_run_service import (
    AgentRunService,
    create_agent_run_service,
)
from ZBot.services.config.config import config_cache
from ZBot.services.config.schema import Config

_agent_service_state: dict[str, Any] = {"service": None, "fingerprint": None}


def _config_fingerprint(config: Config | None) -> tuple | None:
    if config is None:
        return None
    return (
        getattr(config, "provider_name", None),
        getattr(config, "model", None),
        tuple(sorted((getattr(config, "mcp_servers", None) or {}).items())),
        getattr(config, "workspace_path", None),
    )


async def get_or_create_agent_service(app: FastAPI) -> AgentRunService | None:
    config = config_cache.get()
    fp = _config_fingerprint(config)
    cached = _agent_service_state.get("service")
    if cached is not None and _agent_service_state.get("fingerprint") == fp:
        return cached
    if cached is not None:
        try:
            await cached.close("default")
        except Exception:
            logger.exception("关闭旧 AgentRunService 失败, 继续重建")
    new_service = create_agent_run_service(config) if config is not None else None
    _agent_service_state["service"] = new_service
    _agent_service_state["fingerprint"] = fp
    logger.info("AgentRunService 重建 (fingerprint={})", fp)
    return new_service


def get_current_agent_service() -> AgentRunService | None:
    return _agent_service_state.get("service")


async def shutdown_agent_service() -> None:
    svc = _agent_service_state.get("service")
    if svc is not None:
        try:
            await svc.close("default")
        except Exception:
            logger.exception("关闭共享 AgentRunService 失败")
        _agent_service_state["service"] = None
