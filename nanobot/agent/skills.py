"""
智能体技能加载器
核心功能：加载、管理、校验AI智能体的所有技能（Skill），支持自定义技能+内置技能双源，自动检查依赖可用性
"""
import json    # 解析技能的JSON格式元数据
import os      # 检查环境变量、文件路径
import re      # 正则匹配，去除Markdown的YAML前置元数据
import shutil  # 检查系统命令行工具（CLI）是否存在
from pathlib import Path  # 路径管理

# 默认【内置技能】目录：相对于当前文件的上级/skills文件夹（程序自带的官方技能）
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillsLoader:
    """
    智能体技能加载器
    技能定义：所有技能都是以 SKILL.md 为文件名的Markdown文件，用于教会AI如何使用工具、执行任务
    技能来源：1.工作区自定义技能（优先级最高） 2.程序内置技能（默认自带）
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        """
        初始化技能加载器
        :param workspace: 项目工作目录（用户自定义技能存放位置）
        :param builtin_skills_dir: 内置技能目录（不传则使用默认内置目录）
        """
        self.workspace = workspace  # 工作根目录
        self.workspace_skills = workspace / "skills"  # 【用户自定义技能】路径
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR  # 【内置技能】路径

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        列出所有可用技能
        :param filter_unavailable: True=过滤掉依赖不满足的技能，False=列出所有
        :return: 技能列表（名称、文件路径、来源：workspace/builtin）
        """
        skills = []

        # 第一步：加载【工作区自定义技能】（优先级最高，会覆盖内置同名技能）
        if self.workspace_skills.exists():
            # 遍历skills下的所有子文件夹
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    # 技能标准文件：文件夹内必须有 SKILL.md
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({
                            "name": skill_dir.name,  # 技能名=文件夹名
                            "path": str(skill_file), # 技能文件绝对路径
                            "source": "workspace"    # 来源：用户自定义
                        })

        # 第二步：加载【程序内置技能】（仅加载无同名自定义技能的）
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    # 关键：同名技能只保留工作区的，内置的被覆盖
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({
                            "name": skill_dir.name,
                            "path": str(skill_file),
                            "source": "builtin"  # 来源：程序内置
                        })

        # 第三步：过滤依赖不满足的技能（默认开启）
        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        按名称加载技能内容（优先读自定义，再读内置）
        :param name: 技能名称（文件夹名）
        :return: SKILL.md 原文内容，找不到返回None
        """
        # 优先：工作区自定义技能
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")

        # 其次：程序内置技能
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")

        # 技能不存在
        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        加载指定技能，并格式化为AI可直接使用的上下文内容
        :param skill_names: 要加载的技能名称列表
        :return: 格式化后的技能文本（去除元数据，分块展示）
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                # 去除技能文件头部的YAML元数据，只保留纯技能说明
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")

        # 用分隔线拼接多个技能，无技能返回空
        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """
        生成【XML格式技能摘要】，用于AI渐进式加载
        作用：AI先看摘要，需要时再读取完整技能文件，节省上下文
        :return: XML格式的所有技能清单（名称、描述、路径、是否可用、缺失依赖）
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        # XML转义：防止特殊字符破坏格式
        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)

            # 拼接XML节点
            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            # 不可用技能：标注缺失的依赖
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """
        【私有】获取技能缺失的依赖项
        :return: 缺失的CLI工具/环境变量，逗号分隔
        """
        missing = []
        requires = skill_meta.get("requires", {})
        # 检查系统命令行工具是否存在
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        # 检查环境变量是否配置
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        return ", ".join(missing)

    def _get_skill_description(self, name: str) -> str:
        """【私有】获取技能的描述信息，无描述则返回技能名"""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name

    def _strip_frontmatter(self, content: str) -> str:
        """【私有】去除Markdown文件头部的YAML前置元数据（---包裹的内容）"""
        if content.startswith("---"):
            # 正则匹配：从开头---到下一个---的所有内容，去除
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content

    def _parse_nanobot_metadata(self, raw: str) -> dict:
        """【私有】解析技能的JSON元数据，兼容nanobot/openclaw双格式"""
        try:
            data = json.loads(raw)
            # 优先读nanobot字段，没有则读openclaw字段
            return data.get("nanobot", data.get("openclaw", {})) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _check_requirements(self, skill_meta: dict) -> bool:
        """【私有】检查技能的所有依赖是否满足（必须全部满足才可用）"""
        requires = skill_meta.get("requires", {})
        # 检查CLI工具
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        # 检查环境变量
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True

    def _get_skill_meta(self, name: str) -> dict:
        """【私有】获取技能的nanobot专属元数据"""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(meta.get("metadata", ""))

    def get_always_skills(self) -> list[str]:
        """
        获取【始终加载】的技能列表
        技能元数据中标记 always=true 且依赖满足的技能，会被AI永久加载
        """
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
            # 判断是否标记为始终加载
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        解析技能文件的【YAML前置元数据】
        元数据格式：---开头，---结尾，中间是key: value键值对
        """
        content = self.load_skill(name)
        if not content:
            return None

        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                metadata = {}
                # 简单解析YAML格式
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"\'')
                return metadata

        return None