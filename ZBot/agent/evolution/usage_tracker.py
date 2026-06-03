"""技能使用追踪器。

记录技能的加载、应用、修补、创建事件，为 Curator 和进化引擎提供数据支撑。
存储使用 SQLite（复用 daily_memory 的 aiosqlite 模式）。

每次操作开/关连接，避免持久连接过期/泄漏问题。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import aiosqlite
from loguru import logger

from ZBot.services.formatting import ensure_dir

# 数据库文件路径
_DB_NAME = "SKILL_USAGE.db"

# DDL 语句（幂等，可重复执行）
_CREATE_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS skill_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_name TEXT NOT NULL,
        session_name TEXT NOT NULL,
        action TEXT NOT NULL,
        success BOOLEAN DEFAULT TRUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_skill_usage_name
        ON skill_usage(skill_name);

    CREATE INDEX IF NOT EXISTS idx_skill_usage_created
        ON skill_usage(created_at);
"""


@dataclass(frozen=True)
class SkillStats:
    """单个技能的使用统计。"""

    skill_name: str
    usage_count: int
    last_used: datetime | None
    success_rate: float
    created_at: datetime | None


def _empty_stats(skill_name: str) -> SkillStats:
    """返回空统计数据。"""
    return SkillStats(
        skill_name=skill_name,
        usage_count=0,
        last_used=None,
        success_rate=0.0,
        created_at=None,
    )


async def _get_db(workspace_path: Path) -> aiosqlite.Connection:
    """获取 SQLite 数据库连接并确保表已创建。"""
    db_path = workspace_path / "memory" / _DB_NAME
    ensure_dir(db_path.parent)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    # 每次连接时确保表存在（幂等 DDL，开销可忽略）
    await db.executescript(_CREATE_TABLES_SQL)
    await db.commit()
    return db


class SkillUsageTracker:
    """技能使用追踪器。

    每次操作独立开/关连接，避免持久连接过期或泄漏。
    """

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path

    async def record(
        self,
        skill_name: str,
        session_name: str,
        action: str,
        success: bool = True,
    ) -> None:
        """记录一次技能使用事件。

        Args:
            skill_name: 技能名称
            session_name: 会话名称
            action: 事件类型 ('loaded' | 'applied' | 'patched' | 'created')
            success: 是否成功
        """
        try:
            db = await _get_db(self.workspace_path)
            try:
                await db.execute(
                    "INSERT INTO skill_usage (skill_name, session_name, action, success) VALUES (?, ?, ?, ?)",
                    (skill_name, session_name, action, success),
                )
                await db.commit()
            finally:
                await db.close()
        except Exception:
            logger.exception("记录技能使用失败: skill={}, action={}", skill_name, action)

    async def get_stats(self, skill_name: str) -> SkillStats:
        """获取单个技能的使用统计。"""
        try:
            db = await _get_db(self.workspace_path)
            try:
                row = await db.execute_fetchall(
                    "SELECT COUNT(*) as cnt, MAX(created_at) as last_used, "
                    "SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count, "
                    "MIN(created_at) as created_at "
                    "FROM skill_usage WHERE skill_name = ?",
                    (skill_name,),
                )

                if not row or row[0][0] == 0:
                    return _empty_stats(skill_name)

                r = row[0]
                count = r[0]
                return SkillStats(
                    skill_name=skill_name,
                    usage_count=count,
                    last_used=datetime.fromisoformat(r[1]) if r[1] else None,
                    success_rate=(r[2] or 0) / count if count > 0 else 0.0,
                    created_at=datetime.fromisoformat(r[3]) if r[3] else None,
                )
            finally:
                await db.close()
        except Exception:
            logger.exception("获取技能统计失败: skill={}", skill_name)
            return _empty_stats(skill_name)

    async def get_all_stats(self) -> dict[str, SkillStats]:
        """获取所有技能的使用统计。"""
        try:
            db = await _get_db(self.workspace_path)
            try:
                rows = await db.execute_fetchall(
                    "SELECT skill_name, COUNT(*) as cnt, MAX(created_at) as last_used, "
                    "SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count, "
                    "MIN(created_at) as created_at "
                    "FROM skill_usage GROUP BY skill_name"
                )

                result: dict[str, SkillStats] = {}
                for r in rows:
                    name = r[0]
                    count = r[1]
                    result[name] = SkillStats(
                        skill_name=name,
                        usage_count=count,
                        last_used=datetime.fromisoformat(r[2]) if r[2] else None,
                        success_rate=(r[3] or 0) / count if count > 0 else 0.0,
                        created_at=datetime.fromisoformat(r[4]) if r[4] else None,
                    )

                return result
            finally:
                await db.close()
        except Exception:
            logger.exception("获取所有技能统计失败")
            return {}

    async def close(self) -> None:
        """兼容接口（无持久连接，实际无操作）。"""
        pass
