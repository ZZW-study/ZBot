import asyncio
from celery_app import app
from ZBot.memory.daily_memory import daily_memory_store
from ZBot.memory.long_term_memory import long_term_memory_store
from ZBot.config.schema import Config
from ZBot.cli.commands import make_provider
from loguru import logger

@app.task(
    bind=True,
    max_retries=3,
    acks_late=True,
    default_retry_delay=300,
    ignore_result=True,
    queue='default'
)
def weekly_daily_memory_operate(self): # ⚠️ 改成同步 def
    """每周五清理过时记忆 + 晋升长期记忆"""
    try:
        # 用 asyncio.run 执行异步逻辑
        asyncio.run(_run_memory_operations())
    except Exception as e:
        logger.error(f"任务执行失败，准备重试: {e}")
        raise self.retry(exc=e)

async def _run_memory_operations():
    """真正的异步业务逻辑"""
    config = Config()
    provider = make_provider(config)

    # 1. 清理过时日常记忆
    obsolete_ok = await daily_memory_store.obsolete_daily_memory(
        decay_rate=config.decay_rate,
        obsolete_score_threshold=config.obsolete_score_threshold
    )
    logger.info(f"日常记忆清理结果: {'成功' if obsolete_ok else '失败'}")

    # 2. 晋升并写入长期记忆
    try:
        evolve_data = await daily_memory_store.evolve_daily_memory(
            decay_rate=config.decay_rate,
            evolve_score_threshold=config.evolve_score_threshold
        )
        write_ok = await long_term_memory_store.write_long_term_memory(
            provider=provider,
            model=config.model,
            filtered_daily_memory=evolve_data
        )
        logger.info(f"长期记忆写入结果: {'成功' if write_ok else '失败'}")
    except Exception as e:
        logger.error(f"记忆晋升流程异常: {e}")
        raise