"""技能运行时工具（改进版）。
核心机制：
- 模糊匹配：8 级匹配链，模型传参有偏差也能匹配
- 原子写入：临时文件 + os.replace，写一半崩了不损坏文件
- frontmatter 校验：create/patch 后确保 YAML 结构完整
- 路径安全：防止模型传 ../../etc/passwd 之类的穿越路径
- 名称校验：统一的 skill name 格式规范
- 失败反馈：patch 失败时返回文件预览 + "Did you mean?" 提示

工具设计：
- load_new_skills_list: 发现新技能（扫描目录，返回 name + description）
- read_skill: 按名称加载技能全文
- skills_manager: create / patch / delete（单次单操作，语义清晰）
"""

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Optional

import aiofiles
import yaml
from loguru import logger

from ZBot.agent.tools.base import Tool

# =============================================================================
# 常量
# =============================================================================

VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_SKILL_CONTENT_CHARS = 100_000  # ~36k tokens


# =============================================================================
# 数据结构
# =============================================================================


@dataclass(frozen=True)
class SkillManifest:
    """技能元数据。"""

    name: str
    description: str
    skill_file: Path


# =============================================================================
# 路径安全
# =============================================================================


def _validate_within_dir(path: Path, root: Path) -> Optional[str]:
    """确保 path 解析后在 root 目录内。返回错误信息或 None。"""
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
    except (ValueError, OSError) as exc:
        return f"路径越界: {exc}"
    return None


# =============================================================================
# 验证器
# =============================================================================


def _validate_name(name: str) -> Optional[str]:
    """校验技能名称格式。返回错误信息或 None。"""
    if not name:
        return "技能名称不能为空。"
    if len(name) > MAX_NAME_LENGTH:
        return f"技能名称超过 {MAX_NAME_LENGTH} 个字符。"
    if not VALID_NAME_RE.match(name):
        return (
            f"无效的技能名称 '{name}'。"
            f"只能用小写字母、数字、连字符、下划线、点号，且必须以字母或数字开头。"
        )
    return None


def _validate_frontmatter(content: str) -> Optional[str]:
    """校验 SKILL.md 的 YAML frontmatter 完整性。返回错误信息或 None。"""
    if not content.strip():
        return "内容不能为空。"
    if not content.startswith("---"):
        return "SKILL.md 必须以 YAML frontmatter (---) 开头。"

    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return "frontmatter 缺少闭合的 '---'。"

    yaml_content = content[3 : end_match.start() + 3]
    try:
        parsed = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return f"YAML 解析错误: {e}"

    if not isinstance(parsed, dict):
        return "frontmatter 必须是 YAML mapping（key: value 键值对）。"
    if "name" not in parsed:
        return "frontmatter 必须包含 'name' 字段。"
    if "description" not in parsed:
        return "frontmatter 必须包含 'description' 字段。"
    if len(str(parsed["description"])) > MAX_DESCRIPTION_LENGTH:
        return f"description 超过 {MAX_DESCRIPTION_LENGTH} 个字符。"

    return None


def _validate_content_size(content: str) -> Optional[str]:
    """校验内容大小。返回错误信息或 None。"""
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        return (
            f"内容大小 {len(content):,} 字符，超过限制 {MAX_SKILL_CONTENT_CHARS:,}。"
            f"考虑拆分成更小的 SKILL.md + references/ 下的辅助文件。"
        )
    return None


# =============================================================================
# 原子写入
# =============================================================================


async def _atomic_write_text(file_path: Path, content: str) -> None:
    """原子写入：先写临时文件，再 os.replace，确保不会写一半损坏。"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(file_path.parent),
        prefix=f".{file_path.name}.tmp.",
        suffix="",
    )
    os.close(fd)
    try:
        async with aiofiles.open(temp_path, "w", encoding="utf-8") as f:
            await f.write(content)
        os.replace(temp_path, file_path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            logger.error("清理临时文件 {} 失败", temp_path)
        raise


# =============================================================================
# 模糊匹配引擎（8 级匹配链）
# =============================================================================
# 模型传过来的 old_string 跟文件内容可能有空格、缩进、转义差异，
# 精确匹配经常静默失败，所以需要逐级模糊匹配。


def _fuzzy_find_and_replace(
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> tuple[str, int, Optional[str], Optional[str]]:
    """模糊查找替换。

    Returns:
        (new_content, match_count, strategy_name, error_message)
        成功时 error 为 None，失败时 new_content 等于原 content。
    """
    if not old_string:
        return content, 0, None, "old_string 不能为空。"
    if old_string == new_string:
        return content, 0, None, "old_string 和 new_string 完全相同。"

    strategies: list[tuple[str, Callable]] = [
        ("exact", _strategy_exact),
        ("line_trimmed", _strategy_line_trimmed),
        ("whitespace_normalized", _strategy_whitespace_normalized),
        ("indentation_flexible", _strategy_indentation_flexible),
        ("escape_normalized", _strategy_escape_normalized),
        ("unicode_normalized", _strategy_unicode_normalized),
        ("block_anchor", _strategy_block_anchor),
        ("context_aware", _strategy_context_aware),
    ]

    for strategy_name, strategy_fn in strategies:
        matches = strategy_fn(content, old_string)
        if not matches:
            continue
        if len(matches) > 1 and not replace_all:
            return content, 0, None, (
                f"找到 {len(matches)} 处匹配。请提供更多上下文使其唯一，"
                f"或使用 replace_all=True 全部替换。"
            )
        new_content = _apply_replacements(content, matches, new_string)
        return new_content, len(matches), strategy_name, None

    return content, 0, None, "在文件中找不到 old_string 的匹配。"


def _apply_replacements(
    content: str, matches: list[tuple[int, int]], new_string: str
) -> str:
    """从后往前替换，避免位置偏移。"""
    sorted_matches = sorted(matches, key=lambda x: x[0], reverse=True)
    result = content
    for start, end in sorted_matches:
        result = result[:start] + new_string + result[end:]
    return result


def _strategy_exact(content: str, pattern: str) -> list[tuple[int, int]]:
    """策略 1：精确匹配。"""
    matches = []
    start = 0
    while True:
        pos = content.find(pattern, start)
        if pos == -1:
            break
        matches.append((pos, pos + len(pattern)))
        start = pos + 1
    return matches


def _strategy_line_trimmed(content: str, pattern: str) -> list[tuple[int, int]]:
    """策略 2：逐行去首尾空白后匹配。"""
    pattern_lines = [line.strip() for line in pattern.split("\n")]
    pattern_normalized = "\n".join(pattern_lines)
    content_lines = content.split("\n")
    content_normalized_lines = [line.strip() for line in content_lines]
    return _find_normalized_matches(
        content, content_lines, content_normalized_lines, pattern, pattern_normalized
    )


def _strategy_whitespace_normalized(
    content: str, pattern: str
) -> list[tuple[int, int]]:
    """策略 3：多空格/Tab 合并为单空格后匹配。"""

    def normalize(s: str) -> str:
        return re.sub(r"[ \t]+", " ", s)

    pattern_normalized = normalize(pattern)
    content_normalized = normalize(content)
    matches_in_normalized = _strategy_exact(content_normalized, pattern_normalized)
    if not matches_in_normalized:
        return []
    return _map_normalized_positions(content, content_normalized, matches_in_normalized)


def _strategy_indentation_flexible(
    content: str, pattern: str
) -> list[tuple[int, int]]:
    """策略 4：忽略缩进差异。"""
    content_lines = content.split("\n")
    content_stripped = [line.lstrip() for line in content_lines]
    pattern_lines = [line.lstrip() for line in pattern.split("\n")]
    return _find_normalized_matches(
        content, content_lines, content_stripped, pattern, "\n".join(pattern_lines)
    )


def _strategy_escape_normalized(
    content: str, pattern: str
) -> list[tuple[int, int]]:
    """策略 5：转义字符标准化（\\n → 真实换行）。"""

    def unescape(s: str) -> str:
        return s.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")

    pattern_unescaped = unescape(pattern)
    if pattern_unescaped == pattern:
        return []
    return _strategy_exact(content, pattern_unescaped)


def _strategy_unicode_normalized(
    content: str, pattern: str
) -> list[tuple[int, int]]:
    """策略 6：Unicode 标准化（智能引号→ASCII）。"""
    unicode_map = {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "—": "--",
        "–": "-",
        "…": "...",
        " ": " ",
    }

    def normalize(text: str) -> str:
        for char, repl in unicode_map.items():
            text = text.replace(char, repl)
        return text

    norm_pattern = normalize(pattern)
    norm_content = normalize(content)
    if norm_content == content and norm_pattern == pattern:
        return []
    norm_matches = _strategy_exact(norm_content, norm_pattern)
    if not norm_matches:
        norm_matches = _strategy_line_trimmed(norm_content, norm_pattern)
    if not norm_matches:
        return []
    # 映射回原始位置（简化版：假设替换不改变长度）
    orig_to_norm = _build_orig_to_norm_map(content, unicode_map)
    return _map_positions_norm_to_orig(orig_to_norm, norm_matches)


def _strategy_block_anchor(content: str, pattern: str) -> list[tuple[int, int]]:
    """策略 7：首行+末行锚点匹配，中间用相似度判断。"""
    pattern_lines = pattern.split("\n")
    if len(pattern_lines) < 2:
        return []

    first_line = pattern_lines[0].strip()
    last_line = pattern_lines[-1].strip()
    content_lines = content.split("\n")
    pattern_line_count = len(pattern_lines)

    potential = []
    for i in range(len(content_lines) - pattern_line_count + 1):
        if (
            content_lines[i].strip() == first_line
            and content_lines[i + pattern_line_count - 1].strip() == last_line
        ):
            potential.append(i)

    matches = []
    threshold = 0.50 if len(potential) == 1 else 0.70

    for i in potential:
        if pattern_line_count <= 2:
            similarity = 1.0
        else:
            content_middle = "\n".join(content_lines[i + 1 : i + pattern_line_count - 1])
            pattern_middle = "\n".join(pattern_lines[1:-1])
            similarity = SequenceMatcher(None, content_middle, pattern_middle).ratio()
        if similarity >= threshold:
            start_pos, end_pos = _calculate_line_positions(
                content_lines, i, i + pattern_line_count, len(content)
            )
            matches.append((start_pos, end_pos))

    return matches


def _strategy_context_aware(content: str, pattern: str) -> list[tuple[int, int]]:
    """策略 8：50% 行相似度阈值匹配。"""
    pattern_lines = pattern.split("\n")
    content_lines = content.split("\n")
    if not pattern_lines:
        return []

    matches = []
    pattern_line_count = len(pattern_lines)

    for i in range(len(content_lines) - pattern_line_count + 1):
        block_lines = content_lines[i : i + pattern_line_count]
        high_sim_count = 0
        for p_line, c_line in zip(pattern_lines, block_lines):
            sim = SequenceMatcher(None, p_line.strip(), c_line.strip()).ratio()
            if sim >= 0.80:
                high_sim_count += 1
        if high_sim_count >= len(pattern_lines) * 0.5:
            start_pos, end_pos = _calculate_line_positions(
                content_lines, i, i + pattern_line_count, len(content)
            )
            matches.append((start_pos, end_pos))

    return matches


# -- 模糊匹配辅助函数 --


def _calculate_line_positions(
    content_lines: list[str], start_line: int, end_line: int, content_length: int
) -> tuple[int, int]:
    """从行索引计算字符位置。"""
    start_pos = sum(len(line) + 1 for line in content_lines[:start_line])
    end_pos = sum(len(line) + 1 for line in content_lines[:end_line]) - 1
    if end_pos >= content_length:
        end_pos = content_length
    return start_pos, end_pos


def _find_normalized_matches(
    content: str,
    content_lines: list[str],
    content_normalized_lines: list[str],
    pattern: str,
    pattern_normalized: str,
) -> list[tuple[int, int]]:
    """在标准化内容中查找匹配，映射回原始位置。"""
    pattern_norm_lines = pattern_normalized.split("\n")
    num_lines = len(pattern_norm_lines)
    matches = []
    for i in range(len(content_normalized_lines) - num_lines + 1):
        block = "\n".join(content_normalized_lines[i : i + num_lines])
        if block == pattern_normalized:
            start_pos, end_pos = _calculate_line_positions(
                content_lines, i, i + num_lines, len(content)
            )
            matches.append((start_pos, end_pos))
    return matches


def _build_orig_to_norm_map(original: str, unicode_map: dict) -> list[int]:
    """构建原始字符索引 → 标准化索引的映射。"""
    result = []
    norm_pos = 0
    for char in original:
        result.append(norm_pos)
        repl = unicode_map.get(char)
        norm_pos += len(repl) if repl is not None else 1
    result.append(norm_pos)
    return result


def _map_positions_norm_to_orig(
    orig_to_norm: list[int], norm_matches: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """标准化位置 → 原始位置。"""
    norm_to_orig_start: dict[int, int] = {}
    for orig_pos, norm_pos in enumerate(orig_to_norm[:-1]):
        if norm_pos not in norm_to_orig_start:
            norm_to_orig_start[norm_pos] = orig_pos

    results = []
    orig_len = len(orig_to_norm) - 1
    for norm_start, norm_end in norm_matches:
        if norm_start not in norm_to_orig_start:
            continue
        orig_start = norm_to_orig_start[norm_start]
        orig_end = orig_start
        while orig_end < orig_len and orig_to_norm[orig_end] < norm_end:
            orig_end += 1
        results.append((orig_start, orig_end))
    return results


def _map_normalized_positions(
    original: str, normalized: str, normalized_matches: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """空白标准化后的位置映射回原始位置。"""
    if not normalized_matches:
        return []
    orig_to_norm = []
    orig_idx = 0
    norm_idx = 0
    while orig_idx < len(original) and norm_idx < len(normalized):
        if original[orig_idx] == normalized[norm_idx]:
            orig_to_norm.append(norm_idx)
            orig_idx += 1
            norm_idx += 1
        elif original[orig_idx] in " \t" and normalized[norm_idx] == " ":
            orig_to_norm.append(norm_idx)
            orig_idx += 1
            if orig_idx < len(original) and original[orig_idx] not in " \t":
                norm_idx += 1
        elif original[orig_idx] in " \t":
            orig_to_norm.append(norm_idx)
            orig_idx += 1
        else:
            orig_to_norm.append(norm_idx)
            orig_idx += 1
    while orig_idx < len(original):
        orig_to_norm.append(len(normalized))
        orig_idx += 1

    norm_to_orig_start: dict[int, int] = {}
    norm_to_orig_end: dict[int, int] = {}
    for orig_pos, norm_pos in enumerate(orig_to_norm):
        if norm_pos not in norm_to_orig_start:
            norm_to_orig_start[norm_pos] = orig_pos
        norm_to_orig_end[norm_pos] = orig_pos

    original_matches = []
    for norm_start, norm_end in normalized_matches:
        orig_start = norm_to_orig_start.get(norm_start, 0)
        if norm_end - 1 in norm_to_orig_end:
            orig_end = norm_to_orig_end[norm_end - 1] + 1
        else:
            orig_end = orig_start + (norm_end - norm_start)
        while orig_end < len(original) and original[orig_end] in " \t":
            orig_end += 1
        original_matches.append((orig_start, min(orig_end, len(original))))
    return original_matches


def _find_closest_lines(old_string: str, content: str) -> str:
    """在文件中找与 old_string 最相似的片段，用于 "Did you mean?" 提示。"""
    if not old_string or not content:
        return ""
    old_lines = old_string.splitlines()
    content_lines = content.splitlines()
    if not old_lines or not content_lines:
        return ""

    anchor = old_lines[0].strip()
    if not anchor:
        candidates = [l.strip() for l in old_lines if l.strip()]
        if not candidates:
            return ""
        anchor = candidates[0]

    scored = []
    for i, line in enumerate(content_lines):
        stripped = line.strip()
        if not stripped:
            continue
        ratio = SequenceMatcher(None, anchor, stripped).ratio()
        if ratio > 0.3:
            scored.append((ratio, i))

    if not scored:
        return ""

    scored.sort(key=lambda x: -x[0])
    top = scored[:3]

    parts = []
    seen = set()
    for _, line_idx in top:
        start = max(0, line_idx - 2)
        end = min(len(content_lines), line_idx + len(old_lines) + 2)
        if (start, end) in seen:
            continue
        seen.add((start, end))
        snippet = "\n".join(
            f"{start + j + 1:4d}| {content_lines[start + j]}"
            for j in range(end - start)
        )
        parts.append(snippet)

    return "\n---\n".join(parts)


# =============================================================================
# 技能元数据解析
# =============================================================================


async def _normalize_manifest(skill_dir: Path) -> tuple[SkillManifest, str]:
    """解析技能目录，返回 (元数据, 正文内容)。

    skill_dir 下必须有 SKILL.md。
    """
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        raise FileNotFoundError(f"技能目录 {skill_dir} 下没有 SKILL.md")

    async with aiofiles.open(skill_file, "r", encoding="utf-8") as f:
        raw = await f.read()

    # 解析 frontmatter
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
                    description = str(fm.get("description", ""))
            except yaml.YAMLError as exc:
                logger.warning("技能 {} 的 YAML frontmatter 解析失败，使用目录名作为名称: {}", skill_dir, exc)
            body = raw[end_match.end() + 3 :]
        else:
            body = raw
    else:
        body = raw

    # 如果 frontmatter 声明的 name 与目录名不一致，以目录名为准并警告
    if name != skill_dir.name:
        logger.warning(
            "技能 {} 的 frontmatter name='{}' 与目录名 '{}' 不一致，使用目录名",
            skill_dir, name, skill_dir.name,
        )
        name = skill_dir.name

    manifest = SkillManifest(
        name=name,
        description=description.strip(),
        skill_file=skill_file,
    )
    return manifest, body.strip()


# =============================================================================
# Tool 1: NewSkillsListLoader — 发现新技能
# =============================================================================


class NewSkillsListLoader(Tool):
    """扫描技能目录，返回当前所有可用技能的 name + description。

    模型可以传入已知技能名列表，工具只返回增量（新创建的）。
    不传 known_skills 则返回全部。
    """

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir: Path = skills_dir

    @property
    def name(self) -> str:
        return "load_new_skills_list"

    @property
    def description(self) -> str:
        return (
            "扫描技能目录，返回可用技能的名称和描述。"
            "可传入已知技能名列表，只返回新增的技能。"
            "不传参则返回全部技能。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "known_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "模型已知的技能名称列表。传入后只返回不在列表中的新技能。不传则返回全部。",
                }
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        known: set[str] = set(kwargs.get("known_skills", []))

        if not self.skills_dir.exists():
            return json.dumps({"success": True, "skills": [], "count": 0}, ensure_ascii=False)

        all_skills = []
        for skill_md in self.skills_dir.rglob("SKILL.md"):
            skill_dir = skill_md.parent
            try:
                manifest, _ = await _normalize_manifest(skill_dir)
                all_skills.append(manifest)
            except Exception as e:
                logger.warning("解析技能 {} 失败: {}", skill_dir, e)

        # 如果传了 known_skills，只返回增量
        if known:
            all_skills = [s for s in all_skills if s.name not in known]

        entries = [
            {"name": s.name, "description": s.description, "path": str(s.skill_file)}
            for s in all_skills
        ]
        return json.dumps(
            {"success": True, "skills": entries, "count": len(entries)},
            ensure_ascii=False,
        )


# =============================================================================
# Tool 2: SkillReader — 加载技能全文
# =============================================================================


class SkillReader(Tool):
    """按技能名称加载 SKILL.md 正文。"""

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir: Path = skills_dir

    @property
    def name(self) -> str:
        return "read_skill"

    @property
    def description(self) -> str:
        return (
            "按技能名称加载 SKILL.md 正文内容。"
            "传入技能名称（如 'fastapi-setup'），返回完整指令。"
            "可一次传多个名称批量加载。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要加载的技能名称列表，如 ['fastapi-setup', 'docker-mysql']。",
                }
            },
            "required": ["skill_names"],
        }

    async def execute(self, **kwargs: Any) -> str:
        skill_names: list[str] = kwargs.get("skill_names", [])
        if not skill_names:
            return json.dumps({"success": False, "error": "未传入任何技能名称。"}, ensure_ascii=False)

        results = []
        for name in skill_names:
            skill_dir = self.skills_dir / name
            err = _validate_within_dir(skill_dir, self.skills_dir)
            if err:
                results.append({"name": name, "success": False, "error": err})
                continue
            if not skill_dir.exists():
                results.append({"name": name, "success": False, "error": f"技能 '{name}' 不存在。"})
                continue
            try:
                manifest, body = await _normalize_manifest(skill_dir)
                results.append({
                    "name": manifest.name,
                    "description": manifest.description,
                    "content": body,
                    "success": True,
                })
            except Exception as e:
                results.append({"name": name, "success": False, "error": str(e)})

        return json.dumps(results, ensure_ascii=False)


# =============================================================================
# Tool 3: SkillsManager — 创建/修补/删除技能
# =============================================================================


class SkillsManager(Tool):
    """技能管理工具。

    三个操作：
    - create: 创建新技能（完成复杂任务后保存可复用流程）
    - patch:  局部修补（使用技能时发现过时/错误/遗漏，立即修补）
    - delete: 删除技能（不再适用时）
    """

    def __init__(self, skills_dir: Path, catalog: Any = None) -> None:
        self.skills_dir: Path = skills_dir
        self.catalog = catalog  # SkillCatalog 实例，用于 create/delete 后清缓存

    @property
    def name(self) -> str:
        return "skills_manager"

    @property
    def description(self) -> str:
        return (
            "技能管理工具，用于创建、修补、删除技能。\n"
            "- create: 完成复杂任务（5+工具调用）后，将可复用流程保存为技能。"
            "需要传入 name 和 content（完整的 SKILL.md 内容，含 frontmatter）。\n"
            "- patch: 使用技能时发现步骤过时、命令错误、遗漏了坑，立即修补。"
            "需要传入 name、old_string（要替换的文字）和 new_string（替换后的文字）。\n"
            "- delete: 技能不再适用时删除。需要传入 name。\n\n"
            "优先改造旧技能（patch），实在不行再创建新技能（create）。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "patch", "delete"],
                    "description": (
                        "操作类型。"
                        "create=创建新技能，patch=修补已有技能，delete=删除技能。"
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "技能名称（小写字母+数字+连字符/下划线/点号，最大64字符）。"
                        "create 时为新技能名，patch/delete 时为已有技能名。"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "create 时必传。完整的 SKILL.md 内容，必须包含 YAML frontmatter"
                        "（--- 开头，含 name 和 description 字段）。"
                    ),
                },
                "old_string": {
                    "type": "string",
                    "description": (
                        "patch 时必传。要查找替换的文字片段。"
                        "支持模糊匹配（空格、缩进、转义差异自动处理）。"
                    ),
                },
                "new_string": {
                    "type": "string",
                    "description": "patch 时必传。替换后的文字。传空字符串表示删除 old_string。",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "patch 时可选。true=替换所有匹配，false（默认）=要求唯一匹配。",
                },
            },
            "required": ["action", "name"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action: str = kwargs.get("action", "")
        name: str = kwargs.get("name", "")

        if action == "create":
            return await self._handle_create(name, kwargs)
        elif action == "patch":
            return await self._handle_patch(name, kwargs)
        elif action == "delete":
            return await self._handle_delete(name)
        else:
            return json.dumps(
                {"success": False, "error": f"未知操作 '{action}'，请用 create/patch/delete。"},
                ensure_ascii=False,
            )

    # -- create --

    async def _handle_create(self, name: str, kwargs: dict) -> str:
        content: str = kwargs.get("content", "")

        # 校验名称
        err = _validate_name(name)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        # 校验 frontmatter
        err = _validate_frontmatter(content)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        # 校验 frontmatter 中的 name 与传入的 name 一致
        end_match = re.search(r"\n---\s*\n", content[3:])
        if end_match:
            yaml_content = content[3 : end_match.start() + 3]
            try:
                fm = yaml.safe_load(yaml_content)
                if isinstance(fm, dict) and fm.get("name") and fm["name"] != name:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"frontmatter 中的 name='{fm['name']}' 与传入的名称 '{name}' 不一致。请保持两者相同。",
                        },
                        ensure_ascii=False,
                    )
            except yaml.YAMLError:
                pass  # 已在 _validate_frontmatter 中校验过

        # 校验大小
        err = _validate_content_size(content)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        # 名称冲突检查
        skill_dir = self.skills_dir / name
        if skill_dir.exists():
            return json.dumps(
                {"success": False, "error": f"技能 '{name}' 已存在。请用 patch 修改，或先 delete 再 create。"},
                ensure_ascii=False,
            )

        # 路径安全
        err = _validate_within_dir(skill_dir, self.skills_dir)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        # 原子写入
        try:
            skill_file = skill_dir / "SKILL.md"
            await _atomic_write_text(skill_file, content)
        except Exception as e:
            logger.error("创建技能 {} 失败: {}", name, e)
            return json.dumps({"success": False, "error": f"写入失败: {e}"}, ensure_ascii=False)

        # 清缓存
        if self.catalog is not None:
            self.catalog.invalidate_cache()

        return json.dumps(
            {"success": True, "message": f"技能 '{name}' 已创建。", "path": str(skill_dir)},
            ensure_ascii=False,
        )

    # -- patch --

    async def _handle_patch(self, name: str, kwargs: dict) -> str:
        old_string: str = kwargs.get("old_string", "")
        new_string: str = kwargs["new_string"] if "new_string" in kwargs else None  # type: ignore[assignment]
        replace_all: bool = kwargs.get("replace_all", False)

        if not old_string:
            return json.dumps(
                {"success": False, "error": "patch 操作必须传入 old_string。"},
                ensure_ascii=False,
            )
        if new_string is None:
            return json.dumps(
                {"success": False, "error": "patch 操作必须传入 new_string（空字符串表示删除 old_string）。"},
                ensure_ascii=False,
            )

        # 定位技能
        skill_dir = self.skills_dir / name
        err = _validate_within_dir(skill_dir, self.skills_dir)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return json.dumps(
                {"success": False, "error": f"技能 '{name}' 不存在（{skill_file}）。"},
                ensure_ascii=False,
            )

        # 读取原内容
        async with aiofiles.open(skill_file, "r", encoding="utf-8") as f:
            original_content = await f.read()

        # 模糊匹配替换
        new_content, match_count, strategy, match_error = _fuzzy_find_and_replace(
            original_content, old_string, new_string, replace_all
        )

        if match_error:
            # 失败：返回错误 + 文件预览 + "Did you mean?"
            preview = original_content[:500] + ("..." if len(original_content) > 500 else "")
            hint = _find_closest_lines(old_string, original_content)
            result = {
                "success": False,
                "error": match_error,
                "file_preview": preview,
            }
            if hint:
                result["did_you_mean"] = hint
            return json.dumps(result, ensure_ascii=False)

        # 校验 patch 后的 frontmatter 完整性
        err = _validate_frontmatter(new_content)
        if err:
            return json.dumps(
                {"success": False, "error": f"修补后 frontmatter 损坏: {err}"},
                ensure_ascii=False,
            )

        # 校验大小
        err = _validate_content_size(new_content)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        # 原子写入（失败时回滚）
        try:
            await _atomic_write_text(skill_file, new_content)
        except Exception as e:
            logger.error("修补技能 {} 失败: {}", name, e)
            return json.dumps({"success": False, "error": f"写入失败: {e}"}, ensure_ascii=False)

        return json.dumps(
            {
                "success": True,
                "message": f"技能 '{name}' 已修补（{match_count} 处替换，策略: {strategy}）。",
            },
            ensure_ascii=False,
        )

    # -- delete --

    async def _handle_delete(self, name: str) -> str:
        skill_dir = self.skills_dir / name

        # 路径安全
        err = _validate_within_dir(skill_dir, self.skills_dir)
        if err:
            return json.dumps({"success": False, "error": err}, ensure_ascii=False)

        if not skill_dir.exists():
            return json.dumps(
                {"success": False, "error": f"技能 '{name}' 不存在。"},
                ensure_ascii=False,
            )

        try:
            shutil.rmtree(skill_dir)
        except Exception as e:
            logger.error("删除技能 {} 失败: {}", name, e)
            return json.dumps({"success": False, "error": f"删除失败: {e}"}, ensure_ascii=False)

        # 清缓存
        if self.catalog is not None:
            self.catalog.invalidate_cache()

        return json.dumps(
            {"success": True, "message": f"技能 '{name}' 已删除。"},
            ensure_ascii=False,
        )
