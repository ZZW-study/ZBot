"""ZBot FastAPI 后端入口。"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from ZBot.backend.routers.agent import router as agent_router
from ZBot.backend.routers.config import router as config_router
from ZBot.backend.routers.multimodal import router as multimodal_router
from ZBot.memory.daily_memory import daily_memory_store

app = FastAPI(title="ZBot Harness API")

# CORS：允许前端 dev server (localhost:5173) 跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 开发阶段允许所有来源
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(agent_router)
app.include_router(multimodal_router)


@app.on_event("startup")
async def warmup_daily_memory_embeddings() -> None:
    """后台预热日常记忆 embedding，不阻塞 FastAPI 对外提供服务。"""
    task = asyncio.create_task(daily_memory_store.warmup_embeddings())
    task.add_done_callback(_log_warmup_failure)


def _log_warmup_failure(task: asyncio.Task[None]) -> None:
    """记录预热任务异常，避免后台 task 静默失败。"""
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("日常记忆 embedding 后台预热任务失败")
