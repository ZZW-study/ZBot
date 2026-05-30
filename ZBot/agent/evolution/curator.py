"""技能 Curator：后台技能维护系统。

参考 HermesAgent 的 Curator 设计，负责：
- 健康检查：检测过期技能，自动转换生命周期状态
- 重叠检测：发现描述相似的技能
- 质量评估：基于使用统计评估技能质量

Curator 是纯文件操作 + SQLite 查询，无 LLM 调用，轻量级。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from ZBot.agent.evolution.lifecycle import (
    check_staleness,
    find_overlaps,
    update_lifecycle_status,
)
from ZBot.agent.evolution.metrics import record_evolution_event
from ZBot.agent.evolution.usage_tracker import SkillUsageTracker


@dataclass
class CuratorReport:
    """Curator 健康检查报告。"""

    to_stale: list[str] = field(default_factory=list)
    to_archive: list[str] = field(default_factory=list)
    overlaps: dict[str, list[str]] = field(default_factory=dict)
    transitions_made: list[tuple[str, str]] = field(default_factory=list)  # (skill_name, new_status)


class SkillCurator:
    """技能 Curator：后台维护技能库健康状态。"""

    def __init__(
        self,
        skills_dir: Path,
        usage_tracker: SkillUsageTracker,
        workspace_path: Path | None = None,
        catalog: Any = None,
    ) -> None:
        self.skills_dir = skills_dir
        self.usage_tracker = usage_tracker
        self.workspace_path = workspace_path
        self.catalog = catalog

    async def health_check(self) -> CuratorReport:
        """执行技能健康检查。

        检测：
        1. 过期技能（active → stale → archived）
        2. 技能描述重叠
        """
        report = CuratorReport()

        # 检查过期状态
        to_stale, to_archive = await check_staleness(self.skills_dir)
        report.to_stale = to_stale
        report.to_archive = to_archive

        # 检查重叠
        report.overlaps = find_overlaps(self.skills_dir, threshold=0.5)

        return report

    async def run_maintenance(self) -> CuratorReport:
        """执行完整的维护流程：健康检查 + 自动状态转换。

        Returns:
            维护报告
        """
        report = await self.health_check()

        # 执行 stale 转换
        for skill_name in report.to_stale:
            skill_file = self.skills_dir / skill_name / "SKILL.md"
            if skill_file.exists():
                success = await update_lifecycle_status(skill_file, "stale")
                if success:
                    report.transitions_made.append((skill_name, "stale"))
                    logger.info("技能 {} 自动转换为 stale", skill_name)
                    await self._record_event("stale", skill_name)

        # 执行 archive 转换
        for skill_name in report.to_archive:
            skill_file = self.skills_dir / skill_name / "SKILL.md"
            if skill_file.exists():
                success = await update_lifecycle_status(skill_file, "archived")
                if success:
                    report.transitions_made.append((skill_name, "archived"))
                    logger.info("技能 {} 自动转换为 archived", skill_name)
                    await self._record_event("archived", skill_name)

        # 记录重叠信息（仅日志，不自动合并）
        if report.overlaps:
            for skill_name, overlapping in report.overlaps.items():
                logger.info("技能重叠：{} 与 {} 描述相似", skill_name, overlapping)

        # 有状态变更时使 catalog 缓存失效
        if report.transitions_made and self.catalog is not None:
            self.catalog.invalidate_cache()

        return report

    async def _record_event(self, event_type: str, skill_name: str) -> None:
        """记录进化事件（如果 workspace_path 已配置）。"""
        if self.workspace_path is None:
            return
        try:
            await record_evolution_event(self.workspace_path, event_type, skill_name)
        except Exception:
            logger.debug("Curator 记录进化事件失败: type={}, skill={}", event_type, skill_name)
