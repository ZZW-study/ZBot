"""ZBot FastAPI 后端入口。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from ZBot.backend.routers.agent import router as agent_router
from ZBot.backend.routers.config import router as config_router
from ZBot.backend.routers.multimodal import router as multimodal_router
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
# allow_origins=["*"] = 允许所有来源访问（开发阶段用，上线后应改为具体域名）
# allow_methods=["*"] = 允许所有 HTTP 方法（GET/POST/PUT/DELETE 等）
# allow_headers=["*"] = 允许所有请求头
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 开发阶段允许所有来源
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(agent_router)
app.include_router(multimodal_router)
