"""FastAPI 依赖注入。"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ZBot.services.agent_run.follow_up_queue import FollowUpQueue
from ZBot.services.agent_run.run_registry import RunRegistry
from ZBot.services.config.config import config_cache
from ZBot.services.config.schema import Config
from ZBot.session.manager import SessionManager

__all__ = [
    "config_cache",
    "get_config_or_503",
    "get_session_manager",
    "get_run_registry",
    "get_follow_up_queue",
]


def get_config_or_503() -> Config:
    config = config_cache.get()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="ZBot 未完成配置,请先在前端 onboarding 页面配置 LLM。",
        )
    return config


def get_session_manager(request: Request) -> SessionManager:
    manager: SessionManager | None = getattr(request.app.state, "session_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="session_manager 未初始化")
    return manager


def get_run_registry(request: Request) -> RunRegistry:
    registry: RunRegistry | None = getattr(request.app.state, "run_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="run_registry 未初始化")
    return registry


def get_follow_up_queue(request: Request) -> FollowUpQueue:
    queue: FollowUpQueue | None = getattr(request.app.state, "follow_up_queue", None)
    if queue is None:
        raise HTTPException(status_code=503, detail="follow_up_queue 未初始化")
    return queue
