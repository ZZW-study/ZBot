"""FastAPI 依赖注入。"""

from __future__ import annotations

from fastapi import HTTPException, Request

from ZBot.services.agent_run.follow_up_queue import FollowUpQueue
from ZBot.services.agent_run.run_registry import RunRegistry
from ZBot.services.config.config import config_cache
from ZBot.services.config.schema import Config
from ZBot.session.manager import ThreadManager

__all__ = [
    "config_cache",
    "get_config_or_503",
    "get_thread_manager",
    "get_run_registry",
    "get_follow_up_queue",
]


def get_config_or_503() -> Config:
    config = config_cache.get()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="ZBot \u672a\u5b8c\u6210\u914d\u7f6e,\u8bf7\u5148\u5728\u524d\u7aef onboarding \u9875\u9762\u914d\u7f6e LLM\u3002",
        )
    return config


def get_thread_manager(request: Request) -> ThreadManager:
    manager: ThreadManager | None = getattr(request.app.state, "thread_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="thread_manager \u672a\u521d\u59cb\u5316")
    return manager


def get_run_registry(request: Request) -> RunRegistry:
    registry: RunRegistry | None = getattr(request.app.state, "run_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="run_registry \u672a\u521d\u59cb\u5316")
    return registry


def get_follow_up_queue(request: Request) -> FollowUpQueue:
    queue: FollowUpQueue | None = getattr(request.app.state, "follow_up_queue", None)
    if queue is None:
        raise HTTPException(status_code=503, detail="follow_up_queue \u672a\u521d\u59cb\u5316")
    return queue
