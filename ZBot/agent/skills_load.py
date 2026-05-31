"""技能目录。

从内置目录和工作区目录发现技能，复用 tools/skills.py 的解析逻辑，
构建技能目录供大模型自行选择加载。
"""

from __future__ import annotations

from pathlib import Path

from ZBot.agent.evolution.lifecycle import read_lifecycle_info
from ZBot.agent.tools.skills import SkillManifest, _normalize_manifest

# 内置技能目录：ZBot/skills/
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillCatalog:
    """技能目录：扫描目录、提取元数据、构建注册表。"""

    def __init__(
        self,
        workspace: Path | None = None,
        builtin_skills_dir: Path | None = None,
    ):
        self.builtin_skills_dir: Path = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.workspace_skills_dir: Path | None = workspace / "skills" if workspace else None
        self._registry_cache: dict[str, SkillManifest] | None = None

    def invalidate_cache(self) -> None:
        """清空技能注册表缓存，下次调用时重新扫描。"""
        self._registry_cache = None

    async def build_catalog_for_prompt(self) -> str:
        """构建技能目录摘要，注入到 system prompt。

        过滤 archived 技能（不可见），stale 技能标注 "(stale)"。
        """
        skills = await self._list_skills()
        if not skills:
            return ""

        lines = [
            "以下是当前可用的技能目录。",
            "根据技能描述判断是否需要；只有主 Agent 可使用 read_skill 加载对应 SKILL.md 正文。",
            "子 Agent 只能把这里的目录作为背景参考，不能主动读取、创建或修改 skill。",
            "",
        ]

        for manifest in skills:
            # 读取生命周期状态
            lifecycle = await read_lifecycle_info(manifest.skill_file)

            # archived 技能不显示在目录中
            if lifecycle.status == "archived":
                continue

            # stale 技能标注
            stale_tag = " (stale)" if lifecycle.status == "stale" else ""
            lines.append(f"- `{manifest.name}`{stale_tag}：{manifest.description}（路径：{manifest.skill_file}）")

        return "\n".join(lines)

    async def _list_skills(self) -> list[SkillManifest]:
        """列出所有技能，按名称排序。"""
        registry = await self._registry()
        skills = list(registry.values())
        skills.sort(key=lambda item: item.name)
        return skills

    async def _registry(self) -> dict[str, SkillManifest]:
        """返回缓存的技能注册表。"""
        if self._registry_cache is None:
            self._registry_cache = await self._discover_registry()
        return self._registry_cache

    async def _discover_registry(self) -> dict[str, SkillManifest]:
        """扫描所有目录，构建技能注册表。后者覆盖前者。"""
        registry: dict[str, SkillManifest] = {}

        for source_dir in self._iter_sources():
            if not source_dir.exists():
                continue

            for skill_file in source_dir.rglob("SKILL.md"):
                skill_dir = skill_file.parent
                try:
                    manifest, _ = await _normalize_manifest(skill_dir)
                except Exception:
                    continue

                registry[manifest.name] = manifest

        return registry

    def _iter_sources(self) -> list[Path]:
        """返回所有要扫描的技能目录，按优先级排列（后者覆盖前者）。"""
        sources: list[Path] = [self.builtin_skills_dir]
        if self.workspace_skills_dir:
            sources.append(self.workspace_skills_dir)
        return sources
