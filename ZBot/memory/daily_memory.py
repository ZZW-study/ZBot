from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import aiosqlite
import sqlite_vec
from loguru import logger
from sqlite_vec import serialize_float32

from ZBot.services.config.schema import Config
from ZBot.prompts.memory_prompts import (
    DAILY_MEMORY_SYSTEM_PROMPT,
    SAVE_DAILY_MEMORY_TOOL,
    build_daily_memory_prompt,
)
from ZBot.services.formatting.paths import ensure_dir
from ZBot.services.formatting.tools import normalize_tool_args

if TYPE_CHECKING:
    from ZBot.providers.base import LLMProvider
    from ZBot.session.manager import Session

DEFAULT_DAILY_MEMORY_TOP_K = 5


async def get_db(workspace_path: Path) -> aiosqlite.Connection:
    """获取 SQLite 数据库连接，数据库文件位于工作区的 memory 目录下。"""
    db_path = workspace_path / "memory" / "DAILY_MEMORY.db"
    ensure_dir(db_path.parent)  # 确保目录存在

    db = await aiosqlite.connect(db_path)
    await db.enable_load_extension(True)  # 允许加载扩展
    await db.load_extension(sqlite_vec.loadable_path())  # 加载向量扩展
    await db.enable_load_extension(False)  # 加载完成后禁用扩展加载以增强安全性
    db.row_factory = aiosqlite.Row  # 以字典形式返回查询结果

    return db


async def init_db(db: aiosqlite.Connection):
    """初始化数据库，创建必要的表格。"""
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS daily_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_name TEXT NOT NULL,
        content TEXT NOT NULL,
        recall_count INTEGER DEFAULT 0 NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    -- sqlite-vec 向量表。
    -- 约定：daily_memory.id == daily_memory_vector.rowid。
    -- 因此插入向量时要手动指定 rowid = daily_memory.id。
    --
    -- distance_metric=cosine 使用余弦距离：
    --   余弦相似度 = cos(θ) = A·B / (|A||B|)，范围 [-1, 1]，1 表示完全相同
    --   余弦距离 = 1 - 余弦相似度，范围 [0, 2]，0 表示完全相同
    --
    -- 使用 cosine 距离做语义检索。
    -- 文本 embedding 通常更关心向量方向而不是向量长度，
    -- cosine 能更好表达“语义是否接近”。
    --
    -- cosine distance 一般表示 1 - cosine_similarity，
    -- distance 越小表示语义越相似。
    --
    -- 这里选择 cosine 主要是为了匹配文本 embedding 的检索语义，
    -- sqlite-vec 返回的是余弦距离，需要用 1 - distance 转成相似度
    CREATE VIRTUAL TABLE IF NOT EXISTS daily_memory_vector
    USING vec0(
        vector float[768] distance_metric=cosine
    );
    """)

    await db.commit()


class DailyMemoryStore:
    """每日记忆存储类，负责管理每日记忆的数据库操作。"""

    _instance: Optional["DailyMemoryStore"] = None
    db: aiosqlite.Connection | None
    _embeddings: Any | None
    _embedding_lock: threading.Lock
    workspace_path: Path

    def __new__(cls, workspace_path: Path):
        """创建或复用每日记忆存储单例。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.workspace_path = workspace_path
            cls._instance.db = None
            cls._instance._embeddings = None
            cls._instance._embedding_lock = threading.Lock()
        return cls._instance

    async def add_daily_memory(
        self,
        provider: LLMProvider,
        model: str,
        session: Session,
    ) -> bool:
        """
        往数据库添加一条新的每日记忆记录和对应的向量表示。给每次会话结束的时候用,在每次会话结束的时候，会进行归档，把会话中的旧消息归档进每日记忆。

        daily_memory.id == daily_memory_vector.rowid
        """
        db = await self._ensure_db()
        content = await self._generate_daily_memory_text(provider, model, session)
        if not content:
            return False

        vector = await self._generate_daily_memory_vec(content)
        vector_blob = serialize_float32(vector)

        try:
            cursor = await db.execute(
                """
                INSERT INTO daily_memory (session_name, content)
                VALUES (?, ?)
                """,
                (session.session_name, content),
            )

            memory_id = cursor.lastrowid
            # 关闭 cursor 连接以释放资源，虽然 aiosqlite 会在 commit/rollback 时自动关闭，但这里提前关闭更清晰。
            await cursor.close()

            if memory_id is None:
                raise RuntimeError("插入 daily_memory 后没有拿到 id")

            await db.execute(
                """
                INSERT INTO daily_memory_vector (rowid, vector)
                VALUES (?, ?)
                """,
                (memory_id, vector_blob),
            )

            await db.commit()
            return True

        except Exception:
            await db.rollback()
            raise

    async def get_daily_memory_text(self, user_content: str, score_threshold: float = 0.75) -> str:
        """基于向量相似度检索相关的每日记忆记录(给上下文构造用的)，并返回文本内容。就是每一次问，在构造上下文提示词的时候，会进行召回"""
        try:
            daily_memory = await self._retrieve_daily_memory(user_content, score_threshold)
        except Exception:
            logger.exception("日常记忆召回失败，已跳过，不阻断本轮对话")
            return ""
        merged_daily_memory = "\n---\n".join(
            f"- 会话名字:{entry['session_name']}\n- 日常记忆内容:{entry['content']}" for entry in daily_memory
        )
        return f"## DAILY_MEMORY.md\n{merged_daily_memory}" if daily_memory else ""

    async def obsolete_daily_memory(self, decay_rate: float = 0.12, obsolete_score_threshold: float = 0.5) -> bool:
        """
        根据衰减率淘汰过时的日常记忆记录。
        score = recall_count * e^(-λ * days_alive)
        λ = 0.12（衰减速度，可调）
        days_alive = 当前时间距离 created_at 的天数
        """
        db = await self._ensure_db()
        try:
            # 标准 SQLite 不支持 `DELETE ... JOIN ...`,改用子查询:
            # 先挑出满足 score 阈值且在 vector 表里存在的 id,再 DELETE。
            # 这样既保证 sqlite-vec rowid 完整性,又避免 OperationalError。
            await db.execute(
                """
                DELETE FROM daily_memory
                WHERE recall_count * EXP(-? * (JULIANDAY('now') - JULIANDAY(created_at))) < ?
                  AND id IN (SELECT rowid FROM daily_memory_vector)
                """,
                (decay_rate, obsolete_score_threshold),
            )
            await db.execute(
                """
                DELETE FROM daily_memory_vector
                WHERE rowid IN (
                    SELECT id FROM daily_memory
                    WHERE recall_count * EXP(-? * (JULIANDAY('now') - JULIANDAY(created_at))) < ?
                )
                """,
                (decay_rate, obsolete_score_threshold),
            )
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise Exception("淘汰过时日常记忆失败")

    async def evolve_daily_memory(
        self, decay_rate: float = 0.12, evolve_score_threshold: float = 1.3
    ) -> list[dict[str, str]]:
        """
        根据进化阈值升级有价值的日常记忆记录为长期记忆。
        score = recall_count * e^(-λ * days_alive)
        λ = 0.12（衰减速度，可调）
        days_alive = 当前时间距离 created_at 的天数
        """
        db = await self._ensure_db()
        try:
            cursor = await db.execute(
                """
                SELECT session_name, content
                FROM daily_memory
                WHERE recall_count * EXP(-? * (JULIANDAY('now') - JULIANDAY(created_at))) >= ?
                """,
                (decay_rate, evolve_score_threshold),
            )
            results = await cursor.fetchall()
            await cursor.close()
            # 这里可以把 results 直接返回给调用者让它们自己处理。
            # 迁移完成后再删除这些记录。
            # 标准 SQLite 不支持 `DELETE ... JOIN ...`,改用子查询。
            await db.execute(
                """
                DELETE FROM daily_memory
                WHERE recall_count * EXP(-? * (JULIANDAY('now') - JULIANDAY(created_at))) >= ?
                  AND id IN (SELECT rowid FROM daily_memory_vector)
                """,
                (decay_rate, evolve_score_threshold),
            )
            await db.execute(
                """
                DELETE FROM daily_memory_vector
                WHERE rowid IN (
                    SELECT id FROM daily_memory
                    WHERE recall_count * EXP(-? * (JULIANDAY('now') - JULIANDAY(created_at))) >= ?
                )
                """,
                (decay_rate, evolve_score_threshold),
            )
            await db.commit()
            return [dict(result) for result in results]

        except Exception:
            await db.rollback()
            raise Exception("升级有价值日常记忆失败")

    async def _generate_daily_memory_text(self, provider: "LLMProvider", model: str, session: "Session") -> str:
        """调用大模型生成每日记忆文本。"""
        memory_snapshot = session.memory_snapshot or ""
        messages = session.messages[session.last_consolidated :]
        prompt = self._build_daily_memory_prompt(messages, memory_snapshot)

        try:
            response = await provider.chat(
                [
                    {
                        "role": "system",
                        "content": DAILY_MEMORY_SYSTEM_PROMPT,
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=SAVE_DAILY_MEMORY_TOOL,
                model=model,
            )
        except Exception:
            logger.exception("生成每日记忆失败")
            return ""

        # 检查模型是否调用了 save_daily_memory 工具
        if not response.has_tool_calls:
            logger.warning("生成每日记忆被跳过：模型没有调用 save_daily_memory 工具")
            return ""

        # 规范化工具参数
        args = normalize_tool_args(response.tool_calls[0].arguments)
        if args is None:
            logger.warning("生成每日记忆失败：模型返回的工具参数格式不正确")
            return ""

        return args.get("content", "")

    def _build_daily_memory_prompt(self, messages: list[dict[str, Any]], memory_snapshot: str) -> str:
        """构建每日记忆的提示词"""
        return build_daily_memory_prompt(messages, memory_snapshot)

    async def _generate_daily_memory_vec(self, content: str) -> list[float]:
        """生成每日记忆的向量表示。"""

        def _embed() -> list[float]:
            embeddings = self._get_embeddings()
            return embeddings.embed_query(content)

        return await asyncio.to_thread(_embed)

    async def _retrieve_daily_memory(
        self,
        user_content: str,
        score_threshold: float = 0.75,
        top_k: int = DEFAULT_DAILY_MEMORY_TOP_K,
    ) -> list[dict[str, Any]]:
        """
        基于向量相似度检索相关的每日记忆记录，并返回文本内容。
        """
        db = await self._ensure_db()
        if not user_content.strip() or not await self._has_daily_memory(db):
            return []

        user_content_embeddings = serialize_float32(await self._generate_daily_memory_vec(user_content.strip()))

        cursor = await db.execute(
            """
            WITH ranked AS(
                SELECT rowid, distance
                FROM daily_memory_vector
                WHERE vector MATCH ?
                LIMIT ?
            )

            SELECT daily_memory.id, daily_memory.session_name, daily_memory.content, ranked.distance
            FROM ranked
            -- JOIN 是 SQL 中的一个关键字，用于把两张表按照某个条件关联起来，组合成一张查询结果。
            -- 从 ranked 里拿到向量检索命中的 rowid，
            -- 然后去 daily_memory 表里找 id 等于这个 rowid 的记录，
            -- 最后把两边的数据拼在一起返回。
            JOIN daily_memory ON daily_memory.id = ranked.rowid
            WHERE 1 - ranked.distance >= ?
            ORDER BY ranked.distance ASC
            """,
            (user_content_embeddings, top_k, score_threshold),
        )

        results = await cursor.fetchall()
        await cursor.close()

        memories: list[dict[str, Any]] = []

        try:
            for result in results:
                # sqlite-vec 返回的 distance 是余弦距离，需要转换成相似度
                id = result["id"]
                await db.execute(
                    """
                    UPDATE daily_memory
                    SET recall_count = recall_count + 1
                    WHERE id = ?
                    """,
                    (id,),
                )

                memories.append(
                    {
                        "session_name": result["session_name"],
                        "content": result["content"],
                    }
                )

            await db.commit()
            return memories

        except Exception:
            await db.rollback()
            raise

    async def warmup_embeddings(self) -> None:
        """后台预热 embedding；首次会下载模型，之后从本地缓存加载到内存。"""
        try:
            await asyncio.to_thread(self._get_embeddings)
            logger.info("日常记忆 embedding 预热完成")
        except Exception:
            logger.exception("日常记忆 embedding 预热失败，后续对话会降级为空记忆")

    async def _ensure_db(self) -> aiosqlite.Connection:
        """懒初始化日常记忆数据库，避免 import 阶段运行异步初始化。"""
        if self.db is None:
            self.db = await get_db(self.workspace_path)
            await init_db(self.db)
        return self.db

    def _get_embeddings(self) -> Any:
        """懒加载 HuggingFace embedding，避免启动时就下载或占用内存。"""
        if self._embeddings is None:
            with self._embedding_lock:
                if self._embeddings is None:
                    from langchain_community.embeddings import HuggingFaceEmbeddings

                    self._embeddings = HuggingFaceEmbeddings(
                        model_name="BAAI/bge-base-zh",
                        model_kwargs={"device": "cpu"},
                    )
        return self._embeddings

    @staticmethod
    async def _has_daily_memory(db: aiosqlite.Connection) -> bool:
        """判断是否已有日常记忆；空库时不需要加载 embedding。"""
        cursor = await db.execute("SELECT 1 FROM daily_memory LIMIT 1")
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None


# 全局单例
config = Config()
daily_memory_store = DailyMemoryStore(config.workspace_path)
