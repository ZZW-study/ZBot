"""技能发现、读取与可用性判断。"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

# 内置技能目录：ZBot/skills/
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# 匹配 SKILL.md 顶部的 frontmatter 块：--- ... ---
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


class SkillsLoader:
    """管理内置技能的加载器
    """

    def __init__(self, builtin_skills_dir: Path | None = None):
        """初始化加载器。

        Args:
            builtin_skills_dir: 可选的技能目录路径，默认使用 BUILTIN_SKILLS_DIR
        """
        self.skills_dir = builtin_skills_dir or BUILTIN_SKILLS_DIR


    def list_skills(self) -> list[str]:
        """列出所有可用的技能名称。

        扫描内置技能目录，返回所有包含 SKILL.md 文件且依赖满足的子目录名称。

        Returns:
            技能名称列表
        """
        if not self.skills_dir.exists():
            return []

        skills = []
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists() and self._check_requirements(skill_dir.name)[0]:
                skills.append(skill_dir.name)
        return skills

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """把多个技能拼成可直接注入 system prompt 的文本块。

        对每个技能：
        1. 读取 SKILL.md 内容
        2. 移除 frontmatter（只保留正文）
        3. 添加 "### 技能：xxx" 标题前缀

        多个技能用 "---" 分隔符连接。

        Args:
            skill_names: 要加载的技能名称列表

        Returns:
            拼接后的技能文本块，空列表返回空字符串

        Example:
            >>> loader.load_skills_for_context(["weather", "memory"])
            '### 技能：weather\\n\\n获取当前天气...\\n\\n---\\n\\n### 技能：memory\\n\\n基于 grep 检索...'
        """
        parts = []
        for name in skill_names:
            content = self._load_skill(name)
            if content:
                # 移除 frontmatter，只保留正文
                body = _FRONTMATTER_RE.sub("", content, count=1).strip()
                parts.append(f"### 技能：{name}\n\n{body}")
        return "\n\n---\n\n".join(parts)

    # -------------------------------------------------------------------------
    # 私有方法
    # -------------------------------------------------------------------------

    def _load_skill(self, name: str) -> str | None:
        """读取单个技能的完整内容。"""
        path = self.skills_dir / name / "SKILL.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def _get_skill_metadata(self, name: str) -> dict | None:
        """解析 SKILL.md 顶部 frontmatter 中的元数据。"""
        content = self._load_skill(name)
        if not content:
            return None

        match = _FRONTMATTER_RE.match(content)
        if not match:
            return None

        # 简单解析：每行一个 key: value
        meta: dict = {}
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("\"'")
        return meta

    def _check_requirements(self, name: str, meta: dict | None = None) -> tuple[bool, list[str]]:
        """检查技能依赖是否满足。

        依赖类型：
        - bins: 命令行工具（通过 shutil.which 检查）
        - env: 环境变量（通过 os.environ 检查）

        依赖信息存储在 frontmatter 的 metadata.ZBot.requires 中。

        Args:
            name: 技能名称
            meta: 可选的元数据字典，避免重复读取

        Returns:
            (available, missing) 元组：
            - available: 是否所有依赖都满足
            - missing: 缺失的依赖描述列表
        """
        meta = meta or self._get_skill_metadata(name) or {}
        zbot_meta = self._parse_zbot_meta(meta)
        requires = zbot_meta.get("requires", {})
        missing: list[str] = []

        # 检查命令行工具
        for binary in requires.get("bins", []):
            if not shutil.which(binary):
                missing.append(f"缺少命令行工具：{binary}")

        # 检查环境变量
        for env_name in requires.get("env", []):
            if not os.environ.get(env_name):
                missing.append(f"缺少环境变量：{env_name}")

        return not missing, missing

    def _parse_zbot_meta(self, meta: dict) -> dict:
        """解析 metadata 字段中的 ZBot 配置。

        SKILL.md 的 frontmatter 中可包含 metadata 字段，用于声明技能的依赖：
        ---
        name: weather
        metadata: {"ZBot": {"requires": {"bins": ["curl"], "env": ["API_KEY"]}}}
        ---

        ZBot.requires.bins: 需要的命令行工具（通过 shutil.which 检查）
        ZBot.requires.env: 需要的环境变量（通过 os.environ 检查）
        """
        raw = meta.get("metadata")
        if not raw:
            return {}
        try:
            if isinstance(raw, dict):
                return raw.get("ZBot", {})
            return json.loads(raw).get("ZBot", {})
        except (json.JSONDecodeError, TypeError):
            return {}
