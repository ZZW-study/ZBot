"""技能生命周期管理。

状态机：
  active → stale (30天无使用)
  stale → archived (再60天无使用)
  stale → active (检测到使用)
  archived → active (显式恢复)
  any → pinned (跳过所有自动转换)

生命周期状态存储在 SKILL.md 的 YAML frontmatter 中：
  status: active | stale | archived | pinned
  last_used: 2026-05-28
  created_by: evolution | manual
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import aiofiles
import yaml
from loguru import logger

# 生命周期常量
STALE_DAYS = 30
ARCHIVE_DAYS = 60  # stale 后再经过这么多天变为 archived

VALID_STATUSES = {"active", "stale", "archived", "pinned"}


@dataclass(frozen=True)
class SkillLifecycleInfo:
    """技能生命周期信息。"""

    name: str
    status: str
    last_used: datetime | None
    created_by: str


async def read_lifecycle_info(skill_file: Path) -> SkillLifecycleInfo:
    """从 SKILL.md 读取生命周期信息。

    如果 frontmatter 中没有 status/last_used/created_by 字段，返回默认值。
    """
    try:
        async with aiofiles.open(skill_file, "r", encoding="utf-8") as f:
            raw = await f.read()
    except Exception:
        return SkillLifecycleInfo(
            name=skill_file.parent.name,
            status="active",
            last_used=None,
            created_by="manual",
        )

    name = skill_file.parent.name
    status = "active"
    last_used: datetime | None = None
    created_by = "manual"

    if raw.startswith("---"):
        end_match = re.search(r"\n---\s*\n", raw[3:])
        if end_match:
            yaml_content = raw[3 : end_match.start() + 3]
            try:
                fm = yaml.safe_load(yaml_content)
                if isinstance(fm, dict):
                    name = fm.get("name", name)
                    status = fm.get("status", "active")
                    if status not in VALID_STATUSES:
                        status = "active"
                    last_used_str = fm.get("last_used")
                    if last_used_str:
                        try:
                            last_used = datetime.fromisoformat(str(last_used_str))
                        except (ValueError, TypeError):
                            last_used = None
                    created_by = fm.get("created_by", "manual")
            except yaml.YAMLError:
                pass

    return SkillLifecycleInfo(
        name=name,
        status=status,
        last_used=last_used,
        created_by=created_by,
    )


async def update_lifecycle_status(skill_file: Path, new_status: str) -> bool:
    """更新 SKILL.md frontmatter 中的 status 字段。

    Returns:
        是否成功更新
    """
    if new_status not in VALID_STATUSES:
        logger.error("无效的生命周期状态: {}", new_status)
        return False

    try:
        async with aiofiles.open(skill_file, "r", encoding="utf-8") as f:
            raw = await f.read()
    except Exception:
        logger.error("读取技能文件失败: {}", skill_file)
        return False

    if not raw.startswith("---"):
        return False

    end_match = re.search(r"\n---\s*\n", raw[3:])
    if not end_match:
        return False

    yaml_content = raw[3 : end_match.start() + 3]
    body = raw[end_match.end() + 3 :].lstrip("\n")

    try:
        fm = yaml.safe_load(yaml_content)
        if not isinstance(fm, dict):
            return False
    except yaml.YAMLError:
        return False

    fm["status"] = new_status
    new_yaml = yaml.dump(fm, allow_unicode=True, default_flow_style=False)
    new_content = f"---\n{new_yaml}---\n{body}"

    try:
        async with aiofiles.open(skill_file, "w", encoding="utf-8") as f:
            await f.write(new_content)
    except Exception:
        logger.error("更新技能生命周期状态失败: {}", skill_file)
        return False

    logger.info("技能 {} 状态更新为 {}", skill_file.parent.name, new_status)
    return True


async def update_last_used(skill_file: Path) -> bool:
    """更新 SKILL.md frontmatter 中的 last_used 为当前日期。"""
    try:
        async with aiofiles.open(skill_file, "r", encoding="utf-8") as f:
            raw = await f.read()
    except Exception:
        return False

    if not raw.startswith("---"):
        return False

    end_match = re.search(r"\n---\s*\n", raw[3:])
    if not end_match:
        return False

    yaml_content = raw[3 : end_match.start() + 3]
    body = raw[end_match.end() + 3 :].lstrip("\n")

    try:
        fm = yaml.safe_load(yaml_content)
        if not isinstance(fm, dict):
            return False
    except yaml.YAMLError:
        return False

    fm["last_used"] = datetime.now().date().isoformat()
    new_yaml = yaml.dump(fm, allow_unicode=True, default_flow_style=False)
    new_content = f"---\n{new_yaml}---\n{body}"

    try:
        async with aiofiles.open(skill_file, "w", encoding="utf-8") as f:
            await f.write(new_content)
    except Exception:
        return False

    return True


async def check_staleness(skills_dir: Path) -> tuple[list[str], list[str]]:
    """检查所有技能的过期状态。

    Returns:
        (to_stale, to_archive) 两个技能名称列表
    """
    to_stale: list[str] = []
    to_archive: list[str] = []
    now = datetime.now()

    if not skills_dir.exists():
        return to_stale, to_archive

    for skill_md in skills_dir.rglob("SKILL.md"):
        info = await read_lifecycle_info(skill_md)

        # pinned 技能跳过所有自动转换
        if info.status == "pinned":
            continue

        # 没有 last_used 记录的技能不自动转换
        if info.last_used is None:
            continue

        days_since_use = (now - info.last_used).days

        if info.status == "active" and days_since_use >= STALE_DAYS:
            to_stale.append(info.name)
        elif info.status == "stale" and days_since_use >= STALE_DAYS + ARCHIVE_DAYS:
            to_archive.append(info.name)

    return to_stale, to_archive


def find_overlaps(skills_dir: Path, threshold: float = 0.5) -> dict[str, list[str]]:
    """检测技能之间的描述重叠。

    使用 SequenceMatcher 比较所有技能对的 description。
    Returns:
        {skill_name: [overlapping_skill_names]}
    """
    if not skills_dir.exists():
        return {}

    # 收集所有技能的描述
    skill_descs: list[tuple[str, str]] = []
    for skill_md in skills_dir.rglob("SKILL.md"):
        skill_dir = skill_md.parent
        try:
            raw = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue

        name = skill_dir.name
        description = ""

        if raw.startswith("---"):
            end_match = re.search(r"\n---\s*\n", raw[3:])
            if end_match:
                yaml_content = raw[3 : end_match.start() + 3]
                try:
                    fm = yaml.safe_load(yaml_content)
                    if isinstance(fm, dict):
                        name = fm.get("name", name)
                        description = str(fm.get("description", "")).strip()
                except yaml.YAMLError:
                    pass

        if description:
            skill_descs.append((name, description))

    # 两两比较
    overlaps: dict[str, list[str]] = {}
    for i in range(len(skill_descs)):
        for j in range(i + 1, len(skill_descs)):
            name_a, desc_a = skill_descs[i]
            name_b, desc_b = skill_descs[j]

            score = SequenceMatcher(None, desc_a.lower(), desc_b.lower()).ratio()
            if score >= threshold:
                overlaps.setdefault(name_a, []).append(name_b)
                overlaps.setdefault(name_b, []).append(name_a)

    return overlaps
