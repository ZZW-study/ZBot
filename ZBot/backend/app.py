"""ZBot FastAPI 后端入口。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from ZBot.backend.routers.config import router as config_router
from ZBot.backend.routers.files import router as files_router
from ZBot.backend.routers.mcp import router as mcp_router
from ZBot.backend.routers.runs import router as runs_router
from ZBot.backend.routers.sessions import router as sessions_router
from ZBot.memory.daily_memory import daily_memory_store
from ZBot.services.agent_run.run_registry import RunRegistry
from ZBot.services.agent_run.session_expiry import (
    session_registry,
    session_watcher,
    start_session_expiry_watcher,
)
from ZBot.session.manager import SessionManager


def _log_warmup_failure(task: asyncio.Task[None]) -> None:
    """记录预热任务异常，避免后台 task 静默失败。"""
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("日常记忆 embedding 后台预热任务失败")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """启动时初始化 session/run 单例,并后台预热日常记忆 embedding。
    """
    # 把核心单例挂到 app.state,供 FastAPI Depends 取用(get_session_manager 等)。
    workspace = Path.home() / ".ZBot" / "workspace"
    _app.state.session_manager = SessionManager(workspace)
    _app.state.run_registry = RunRegistry()
    # SessionRegistry + Watcher:之前是定义但没人启动的死代码,现在显式启动。
    _app.state.session_registry = session_registry
    _app.state.session_watcher_task = await start_session_expiry_watcher(session_watcher)

    warmup_task = asyncio.create_task(daily_memory_store.warmup_embeddings())
    warmup_task.add_done_callback(_log_warmup_failure)
    _app.state.warmup_task = warmup_task

    try:
        yield
    finally:
        # ZBot 改: 关闭共享 AgentRunService (cron.stop / close_mcp / 记忆刷盘)
        from ZBot.backend.agent_service_pool import shutdown_agent_service
        await shutdown_agent_service()
        # shutdown:取消并等待所有后台 task,避免资源泄漏。
        session_watcher.stop()
        if _app.state.session_watcher_task is not None:
            _app.state.session_watcher_task.cancel()
            try:
                await _app.state.session_watcher_task
            except (asyncio.CancelledError, Exception):
                pass
        warmup_task.cancel()
        try:
            await warmup_task
        except (asyncio.CancelledError, Exception):
            pass


# 开启lifespan，Fastapi退出时，自动执行finally后面的代码
app = FastAPI(title="ZBot Harness API", lifespan=lifespan)

# ── CORS 中间件 ─────────────────────────────────────────
# CORS（Cross-Origin Resource Sharing，跨域资源共享）是浏览器的安全策略。
#
# 浏览器的同源策略规定：http://localhost:5173 的页面，不能随便请求 http://localhost:8000 的 API，
# 因为端口不同就算"跨域"。没有 CORS 放行，浏览器会拦截请求，前端页面报错。
#
# 工作原理：
#   1. 浏览器先发一个 OPTIONS 预检请求，问后端："我能不能访问你？"
#   2. 后端返回 CORS 响应头（Access-Control-Allow-Origin 等），表示同意
#   3. 浏览器收到同意后，才发送真正的 GET/POST 请求
#
# 环境变量 ZBOT_CORS_ORIGINS 控制允许的域名：
#   未设置或设为 "*" → 允许所有来源（开发阶段）
#   设为逗号分隔的域名列表 → 仅允许指定域名（生产阶段）
_cors_env = os.environ.get("ZBOT_CORS_ORIGINS", "*").strip()
if _cors_env == "*":
    _allow_origins = ["*"]
else:
    _allow_origins = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(files_router)
app.include_router(mcp_router)
app.include_router(runs_router)
app.include_router(sessions_router)


# ZBot 改: agent_service_pool 提供跨 run 共享 AgentRunService (避免每次 sendMessage 重建 + 重连 MCP)
# 实现见 ZBot.backend.agent_service_pool
