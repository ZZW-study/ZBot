"""ZBot FastAPI 后端入口。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from ZBot.backend.routers.agent import router as agent_router
from ZBot.backend.routers.config import router as config_router
from ZBot.backend.routers.session_name import router as session_router
from ZBot.memory.daily_memory import daily_memory_store


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
    """启动时后台预热日常记忆 embedding，不阻塞对外服务。"""
    task = asyncio.create_task(daily_memory_store.warmup_embeddings())
    # 当 task 执行完毕（成功/失败/取消），自动调用 _log_warmup_failure。
    # 后台 task 的异常不会冒泡到主线程，加这个回调是为了兜底——
    # 任务失败时至少能记一条日志，不会静默丢失错误。
    task.add_done_callback(_log_warmup_failure)
    yield


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
app.include_router(agent_router)
app.include_router(session_router)

