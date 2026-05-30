"""进化指标记录。

记录技能进化事件（created/patched/stale/archived/merged），为用户提供进化历史查询。
存储使用 SQLite（与 usage_tracker 共用 SKILL_USAGE.db）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from ZBot.service.utils.helpers import ensure_dir

_DB_NAME = "SKILL_USAGE.db"

# DDL 语句（幂等，可重复执行）
_CREATE_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS evolution_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        skill_name TEXT NOT NULL,
        session_name TEXT,
        details TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_evolution_events_type
        ON evolution_events(event_type);

    CREATE INDEX IF NOT EXISTS idx_evolution_events_skill
        ON evolution_events(skill_name);
"""


async def _get_db(workspace_path: Path) -> aiosqlite.Connection:
    """获取 SQLite 数据库连接并确保表已创建。"""
    db_path = workspace_path / "memory" / _DB_NAME
    ensure_dir(db_path.parent)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.executescript(_CREATE_TABLES_SQL)
    await db.commit()
    return db


async def init_evolution_metrics_db(workspace_path: Path) -> None:
    """初始化进化指标数据库表（兼容接口，实际由 _get_db 自动完成）。"""
    db = await _get_db(workspace_path)
    await db.close()


async def record_evolution_event(
    workspace_path: Path,
    event_type: str,
    skill_name: str,
    session_name: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """记录一次进化事件。

    Args:
        workspace_path: 工作区路径
        event_type: 事件类型 ('created' | 'patched' | 'stale' | 'archived' | 'merged')
        skill_name: 技能名称
        session_name: 会话名称
        details: 额外详情（JSON 序列化）
    """
    try:
        db = await _get_db(workspace_path)
        try:
            await db.execute(
                "INSERT INTO evolution_events (event_type, skill_name, session_name, details) VALUES (?, ?, ?, ?)",
                (event_type, skill_name, session_name, json.dumps(details, ensure_ascii=False) if details else None),
            )
            await db.commit()
        finally:
            await db.close()
    except Exception:
        logger.exception("记录进化事件失败: type={}, skill={}", event_type, skill_name)


async def get_evolution_summary(workspace_path: Path, days: int = 30) -> dict[str, Any]:
    """获取进化指标摘要。

    Args:
        workspace_path: 工作区路径
        days: 统计最近 N 天

    Returns:
        包含事件统计、最活跃技能等信息的字典
    """
    try:
        db = await _get_db(workspace_path)
        try:
            # 按事件类型统计
            rows = await db.execute_fetchall(
                "SELECT event_type, COUNT(*) as cnt "
                "FROM evolution_events "
                "WHERE created_at >= datetime('now', ?) "
                "GROUP BY event_type",
                (f"-{days} days",),
            )
            events_by_type = {r[0]: r[1] for r in rows}

            # 最活跃技能
            rows = await db.execute_fetchall(
                "SELECT skill_name, COUNT(*) as cnt "
                "FROM evolution_events "
                "WHERE created_at >= datetime('now', ?) "
                "GROUP BY skill_name "
                "ORDER BY cnt DESC LIMIT 5",
                (f"-{days} days",),
            )
            most_active = [{"skill": r[0], "events": r[1]} for r in rows]

            return {
                "period_days": days,
                "events_by_type": events_by_type,
                "most_active_skills": most_active,
                "total_events": sum(events_by_type.values()),
            }
        finally:
            await db.close()
    except Exception:
        logger.exception("获取进化指标摘要失败")
        return {"period_days": days, "events_by_type": {}, "most_active_skills": [], "total_events": 0}


async def get_skill_history(workspace_path: Path, skill_name: str) -> list[dict[str, Any]]:
    """获取单个技能的完整进化历史。

    Args:
        workspace_path: 工作区路径
        skill_name: 技能名称

    Returns:
        按时间排序的事件列表
    """
    try:
        db = await _get_db(workspace_path)
        try:
            rows = await db.execute_fetchall(
                "SELECT event_type, session_name, details, created_at "
                "FROM evolution_events "
                "WHERE skill_name = ? "
                "ORDER BY created_at ASC",
                (skill_name,),
            )
            return [
                {
                    "event_type": r[0],
                    "session_name": r[1],
                    "details": json.loads(r[2]) if r[2] else None,
                    "created_at": r[3],
                }
                for r in rows
            ]
        finally:
            await db.close()
    except Exception:
        logger.exception("获取技能进化历史失败: skill={}", skill_name)
        return []
