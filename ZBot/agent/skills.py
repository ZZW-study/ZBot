"""技能发现、解析、筛选与按需加载。

这个模块负责：
1. 从多个目录（内置/用户/工作区）发现技能
2. 解析 SKILL.md 文件的 frontmatter 元数据
3. 筛选出当前环境可用的技能
4. 按需加载技能正文内容
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 内置技能目录：当前文件所在目录的上一级的 skills 文件夹
# 例如：ZBot/agent/skills.py -> ZBot/skills/
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# 技能来源优先级：数值越大，优先级越高。
# 这意味着如果同名技能同时出现在多个目录中，
# workspace 会覆盖 user，user 会覆盖 builtin。
SOURCE_PRIORITY = {
    "builtin": 1,    # 内置技能，优先级最低
    "user": 2,       # 用户技能，中等优先级
    "workspace": 3,  # 工作区技能，优先级最高
}


@dataclass(slots=True)  # slots=True 可以节省内存，提高属性访问速度
class SkillManifest:
    """技能的标准化元数据。

    以前你的系统把技能看成"目录名 + 原始 SKILL.md 文本"。
    现在我们把它升级成一个真正的结构化对象。
    """

    name: str  # 技能名称
    description: str  # 技能描述
    source: str  # 技能来源（builtin/user/workspace）
    base_dir: Path  # 技能所在目录
    skill_file: Path  # SKILL.md 文件路径
    homepage: str | None = None  # 技能主页链接（可选）
    tags: list[str] = field(default_factory=list)  # 标签列表
    tools: list[str] = field(default_factory=list)  # 所需工具列表
    triggers: list[str] = field(default_factory=list)  # 触发词列表
    requires_bins: list[str] = field(default_factory=list)  # 依赖的二进制程序列表
    requires_env: list[str] = field(default_factory=list)  # 依赖的环境变量列表
    user_invocable: bool = True  # 是否可由用户手动调用
    auto_invocable: bool = True  # 是否可自动调用


def _extract_frontmatter_and_body(content: str) -> tuple[str | None, str]:
    """把 SKILL.md 拆成 frontmatter 和正文。

    SKILL.md 文件格式：
    ---
    name: skill-name
    description: 技能描述
    ---
    # 正文内容

    返回值：
    - 第一个值：frontmatter 字符串（不含 --- 分隔线）；如果没有 frontmatter，返回 None
    - 第二个值：正文 Markdown
    """

    # 按行拆分内容，splitlines() 会去掉每行的换行符
    lines = content.splitlines()

    # 如果文件为空，或者第一行不是 "---"，说明没有 frontmatter
    if not lines or lines[0].strip() != "---":
        return None, content.strip()

    # 从第二行开始查找结束的 "---"
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            # 提取 frontmatter（两个 --- 之间的内容）
            frontmatter = "\n".join(lines[1:index])  # splitlines() 已去掉换行符，join() 再加回来
            # 提取正文（第二个 --- 之后的内容）
            body = "\n".join(lines[index + 1 :]).strip()
            return frontmatter, body

    # 如果开头有 ---，但后面没有结束的 ---，格式错误
    raise ValueError("SKILL.md frontmatter 缺少结束分隔线 ---")


def _as_string_list(value: Any) -> list[str]:
    """把任意输入尽量规范成字符串列表。

    支持的输入类型：
    - None -> []
    - "text" -> ["text"]
    - ["a", "b"] -> ["a", "b"]
    - 其他类型 -> 转成字符串后放入列表
    """

    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []

    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items

    return []


def _merge_string_lists(*values: Any) -> list[str]:
    """把多个来源的列表合并，并去重但保留顺序。

    例如：
    _merge_string_lists(["a", "b"], ["b", "c"]) -> ["a", "b", "c"]
    """

    merged: list[str] = []  # 结果列表
    seen: set[str] = set()  # 已见过的元素，用于去重

    for value in values:
        for item in _as_string_list(value):
            if item not in seen:
                merged.append(item)
                seen.add(item)

    return merged


def _as_bool(value: Any, default: bool = False) -> bool:
    """把各种可能的值转成布尔值。

    支持的输入：
    - True/False -> 直接返回
    - "true", "1", "yes", "on" -> True
    - "false", "0", "no", "off" -> False
    - 其他 -> 返回默认值
    """

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False

    return default


def _load_frontmatter(frontmatter_text: str) -> dict[str, Any]:
    """用 PyYAML 解析 frontmatter，并兼容旧版 metadata JSON。

    新格式：
    name: skill-name
    zbot:
      emoji: 🦞

    旧格式：
    name: skill-name
    metadata: {"ZBot": {"emoji": "🦞"}}
    """

    # 用 YAML 解析 frontmatter 文本
    loaded = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(loaded, dict):
        raise ValueError("SKILL.md frontmatter 必须是一个 YAML 对象")

    # 兼容旧版：metadata 字段可能是 JSON 字符串，需要解析
    metadata = loaded.get("metadata")
    if isinstance(metadata, str):
        try:
            loaded["metadata"] = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise ValueError(f"metadata 不是合法 JSON：{exc}") from exc

    return loaded


def _normalize_zbot_block(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """统一读取 zbot 配置块。

    支持两种来源：
    1. 新格式：zbot:
       zbot:
         emoji: 🦞
    2. 旧格式：metadata: {"ZBot": {...}}
       metadata:
         ZBot:
           emoji: 🦞
    """

    # 先尝试新格式
    zbot_block = frontmatter.get("zbot")
    if isinstance(zbot_block, dict):
        return zbot_block

    # 再尝试旧格式
    metadata = frontmatter.get("metadata")
    if isinstance(metadata, dict):
        legacy = metadata.get("ZBot") or metadata.get("zbot")
        if isinstance(legacy, dict):
            return legacy

    return {}


def _normalize_manifest(skill_dir: Path, source: str) -> SkillManifest:
    """把一个技能目录解析成 SkillManifest。

    参数：
    - skill_dir: 技能目录路径
    - source: 技能来源（builtin/user/workspace）

    返回：SkillManifest 对象

    异常：
    - 缺少 SKILL.md 文件
    - SKILL.md 缺少必要的 frontmatter
    - name 与目录名不匹配
    """

    # 检查 SKILL.md 文件是否存在
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        raise ValueError(f"目录 {skill_dir} 下缺少 SKILL.md")

    # 读取文件内容，提取 frontmatter 和正文
    content = skill_file.read_text(encoding="utf-8")
    frontmatter_text, _body = _extract_frontmatter_and_body(content)
    if frontmatter_text is None:
        raise ValueError(f"{skill_file} 缺少 YAML frontmatter")

    # 解析 frontmatter
    frontmatter = _load_frontmatter(frontmatter_text)
    zbot_block = _normalize_zbot_block(frontmatter)

    # 提取基本字段
    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()
    homepage = frontmatter.get("homepage")

    # 验证必要字段
    if not name:
        raise ValueError(f"{skill_file} 缺少 name")
    if not description:
        raise ValueError(f"{skill_file} 缺少 description")
    if name != skill_dir.name:
        raise ValueError(
            f"{skill_file} 的 name 为 '{name}'，但目录名是 '{skill_dir.name}'，两者必须一致"
        )

    # 提取 requires 配置（新格式）
    requires = frontmatter.get("requires")
    if not isinstance(requires, dict):
        requires = {}

    # 提取 requires 配置（旧格式，从 zbot 块中）
    legacy_requires = zbot_block.get("requires")
    if not isinstance(legacy_requires, dict):
        legacy_requires = {}

    # 合并各种列表字段
    tags = _merge_string_lists(frontmatter.get("tags"), zbot_block.get("tags"))
    tools = _merge_string_lists(frontmatter.get("tools"), frontmatter.get("allowed-tools"))
    triggers = _merge_string_lists(
        zbot_block.get("triggers"),  # 旧格式的触发词
        tags,                        # 标签也作为触发词
        [name],                      # 技能名本身也是触发词
    )

    # 合并依赖配置（新格式和旧格式）
    requires_bins = _merge_string_lists(
        requires.get("bins"),
        legacy_requires.get("bins"),
    )
    requires_env = _merge_string_lists(
        requires.get("env"),
        legacy_requires.get("env"),
    )

    # 解析布尔配置
    user_invocable = _as_bool(frontmatter.get("user-invocable"), True)
    disable_model_invocation = _as_bool(frontmatter.get("disable-model-invocation"), False)
    auto_invocable = not disable_model_invocation

    # 构建并返回 SkillManifest 对象
    return SkillManifest(
        name=name,
        description=description,
        source=source,
        base_dir=skill_dir,
        skill_file=skill_file,
        homepage=str(homepage).strip() if homepage else None,
        tags=tags,
        tools=tools,
        triggers=triggers,
        requires_bins=requires_bins,
        requires_env=requires_env,
        user_invocable=user_invocable,
        auto_invocable=auto_invocable,
    )


class SkillsLoader:
    """技能注册表：负责发现、过滤、构建 catalog、按需加载正文。

    主要功能：
    1. 从多个目录扫描技能
    2. 缓存技能注册表
    3. 检查技能依赖是否满足
    4. 根据用户消息匹配合适的技能
    5. 加载技能正文内容
    """

    def __init__(
        self,
        workspace: Path | None = None,
        builtin_skills_dir: Path | None = None,
        user_skills_dir: Path | None = None,
    ):
        """初始化技能加载器。

        参数：
        - workspace: 工作区目录，用于查找工作区技能
        - builtin_skills_dir: 内置技能目录，默认为 ZBot/skills/
        - user_skills_dir: 用户技能目录，默认为 ~/.ZBot/skills/
        """
        self.builtin_skills_dir = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.user_skills_dir = user_skills_dir or (Path.home() / ".ZBot" / "skills")
        self.workspace_skills_dir = workspace / "skills" if workspace else None
        self._registry_cache: dict[str, SkillManifest] | None = None  # 技能注册表缓存

    def _iter_sources(self) -> list[tuple[str, Path]]:
        """返回所有要扫描的技能目录来源。

        返回：[(来源名称, 目录路径), ...]
        例如：[("builtin", /path/to/ZBot/skills), ("user", ~/.ZBot/skills), ...]
        """

        sources: list[tuple[str, Path]] = [("builtin", self.builtin_skills_dir)]

        if self.user_skills_dir:
            sources.append(("user", self.user_skills_dir))

        if self.workspace_skills_dir:
            sources.append(("workspace", self.workspace_skills_dir))

        return sources

    def _discover_registry(self) -> dict[str, SkillManifest]:
        """扫描所有来源，合并成最终 registry。

        返回：{技能名: SkillManifest}

        注意：
        - 同名技能按优先级覆盖（workspace > user > builtin）
        - 解析失败的技能会被跳过
        """

        registry: dict[str, SkillManifest] = {}

        for source_name, source_dir in self._iter_sources():
            # 跳过不存在的目录
            if not source_dir.exists():
                continue

            # 遍历目录下的每个子目录（每个子目录是一个技能）
            for skill_dir in source_dir.iterdir():
                if not skill_dir.is_dir():
                    continue

                try:
                    # 尝试解析技能
                    manifest = _normalize_manifest(skill_dir, source_name)
                except Exception:
                    # 解析失败的技能跳过，不让整个系统崩溃
                    continue

                # 检查是否已有同名技能
                existing = registry.get(manifest.name)
                if existing is None:
                    # 没有同名技能，直接添加
                    registry[manifest.name] = manifest
                    continue

                # 有同名技能，按优先级决定是否覆盖
                if SOURCE_PRIORITY[manifest.source] >= SOURCE_PRIORITY[existing.source]:
                    registry[manifest.name] = manifest

        return registry

    def _registry(self) -> dict[str, SkillManifest]:
        """返回缓存后的 registry。

        第一次调用会扫描目录，后续调用使用缓存。
        """
        if self._registry_cache is None:
            self._registry_cache = self._discover_registry()
        return self._registry_cache

    def refresh(self) -> None:
        """清空缓存，强制下次重新扫描。

        当技能目录有变化时调用此方法。
        """
        self._registry_cache = None

    def get_manifest(self, name: str) -> SkillManifest | None:
        """按技能名读取 manifest。

        参数：
        - name: 技能名称

        返回：SkillManifest 或 None（技能不存在）
        """
        return self._registry().get(name)

    def _missing_requirements(self, manifest: SkillManifest) -> list[str]:
        """检查技能依赖缺失情况。

        参数：
        - manifest: 技能元数据

        返回：缺失项列表，例如 ["缺少命令行工具：gh", "缺少环境变量：GITHUB_TOKEN"]
        """

        missing: list[str] = []

        # 检查依赖的命令行工具是否存在
        for binary in manifest.requires_bins:
            if not shutil.which(binary):
                missing.append(f"缺少命令行工具：{binary}")

        # 检查依赖的环境变量是否设置
        for env_name in manifest.requires_env:
            if not os.environ.get(env_name):
                missing.append(f"缺少环境变量：{env_name}")

        return missing

    def list_visible_skills(self, *, auto_only: bool = True) -> list[SkillManifest]:
        """列出当前环境中真正可见、可用的技能。

        参数：
        - auto_only: 是否只列出可自动调用的技能

        返回：可见技能列表，按名称排序

        过滤条件：
        1. auto_only=True 时，过滤掉 auto_invocable=False 的技能
        2. 过滤掉依赖不满足的技能
        """

        visible: list[SkillManifest] = []

        for manifest in self._registry().values():
            # 过滤不可自动调用的技能
            if auto_only and not manifest.auto_invocable:
                continue

            # 过滤依赖不满足的技能
            if self._missing_requirements(manifest):
                continue

            visible.append(manifest)

        # 按名称排序
        visible.sort(key=lambda item: item.name)
        return visible

    def build_catalog_for_prompt(self) -> str:
        """构建给 system prompt 用的技能目录（摘要）。

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        【这个方法的作用：生成技能"摘要目录"】
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        这个方法只读取每个技能的 frontmatter（元数据），不读取技能正文。
        生成的摘要会被注入到 system prompt 中，让模型知道"有哪些技能可用"。

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        【为什么只读摘要，不读正文？——节省 token】
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        假设有 10 个技能，每个 SKILL.md 平均 500 行：
        - 如果全部加载正文：10 × 500 = 5000 行 → 约 25000 tokens
        - 如果只加载摘要：10 × 2 行 = 20 行 → 约 200 tokens

        摘要只包含：技能名 + 描述 + 标签 + 路径，足够让模型判断"是否需要这个技能"。

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        【模型如何获取完整技能内容？——用 read_file 工具】
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        摘要中包含 SKILL.md 文件的路径，例如：
            - `github`：通过 gh 命令行工具与 GitHub 交互（路径：/path/to/ZBot/skills/github/SKILL.md）

        模型看到摘要后，如果需要详细指令，可以调用 read_file 工具：
            read_file(path="/path/to/ZBot/skills/github/SKILL.md")

        这样模型就能获取完整的技能正文（包含所有命令示例、使用说明等）。

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        【数据流向图】
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        ┌─────────────────────────────────────────────────────────────────────────────┐
        │  SKILL.md 文件结构                                                          │
        │  ───────────────────────────────────────────────────────────────────────    │
        │                                                                             │
        │  ---                                                                        │
        │  name: github                          ← frontmatter（元数据）              │
        │  description: 通过 gh 命令行工具...    ← frontmatter（元数据）              │
        │  tags: [git, github]                  ← frontmatter（元数据）              │
        │  ---                                                                        │
        │                                                                             │
        │  # GitHub 技能                         ← 正文开始                           │
        │  使用 gh 命令行工具...                                                      │
        │  ...                                                                        │
        └─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │  _normalize_manifest() 方法                                                 │
        │  ───────────────────────────────────────────────────────────────────────    │
        │                                                                             │
        │  1. 读取 SKILL.md 文件全部内容                                               │
        │  2. _extract_frontmatter_and_body() 分离 frontmatter 和正文                 │
        │  3. 解析 frontmatter 为字典                                                  │
        │  4. 构建 SkillManifest 对象（只保存元数据，不保存正文）                        │
        │                                                                             │
        │  返回的 SkillManifest 包含：                                                 │
        │  - name: "github"                                                           │
        │  - description: "通过 gh 命令行工具..."                                      │
        │  - tags: ["git", "github"]                                                  │
        │  - skill_file: Path("/path/to/SKILL.md")  ← 文件路径，用于后续加载正文        │
        └─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │  build_catalog_for_prompt() 方法（本方法）                                   │
        │  ───────────────────────────────────────────────────────────────────────    │
        │                                                                             │
        │  遍历所有 SkillManifest，生成摘要文本：                                       │
        │                                                                             │
        │  - `github`：通过 gh 命令行工具与 GitHub 交互                                │
        │    （来源：builtin；标签：git, github；路径：/path/to/SKILL.md）              │
        │                                                                             │
        │  注意：这里只用到 manifest 的元数据字段，不读取正文。                          │
        └─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │  注入到 system prompt                                                       │
        │  ───────────────────────────────────────────────────────────────────────    │
        │                                                                             │
        │  # 技能目录                                                                 │
        │                                                                             │
        │  以下是当前环境中可自动使用的技能目录。                                        │
        │  先根据技能描述判断是否需要某个技能；只有真正需要时，再读取对应 SKILL.md 正文。  │
        │                                                                             │
        │  - `github`：通过 gh 命令行工具与 GitHub 交互（来源：builtin；...）           │
        │  - `weather`：查询天气信息（来源：builtin；...）                              │
        └─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
        ┌─────────────────────────────────────────────────────────────────────────────┐
        │  大模型收到 system prompt                                                    │
        │  ───────────────────────────────────────────────────────────────────────    │
        │                                                                             │
        │  模型看到摘要后有两种选择：                                                   │
        │                                                                             │
        │  1. 摘要足够用 → 直接根据摘要执行任务                                          │
        │  2. 需要详细指令 → 调用 read_file(path="...SKILL.md") 获取完整正文            │
        │                                                                             │
        └─────────────────────────────────────────────────────────────────────────────┘

        返回：技能目录文本，用于注入到 system prompt

        格式示例：
        以下是当前环境中可自动使用的技能目录。
        先根据技能描述判断是否需要某个技能；只有真正需要时，再读取对应 SKILL.md 正文。

        - `github`：通过 gh 命令行工具与 GitHub 交互（来源：builtin；标签：git, github；路径：/path/to/SKILL.md）
        - `weather`：查询天气信息（来源：builtin；路径：/path/to/SKILL.md）
        """

        # 获取所有可见的、可自动调用的技能
        # list_visible_skills() 会过滤掉：
        # 1. auto_invocable=False 的技能（用户禁用了自动调用）
        # 2. 依赖不满足的技能（如缺少 gh 命令、缺少环境变量等）
        visible = self.list_visible_skills(auto_only=True)
        if not visible:
            return ""

        # 构建摘要文本的开头说明
        lines = [
            "以下是当前环境中可自动使用的技能目录。",
            "先根据技能描述判断是否需要某个技能；只有真正需要时，再读取对应 SKILL.md 正文。",
            "",
        ]

        # 遍历每个技能，生成一行摘要
        for manifest in visible:
            # manifest 是 SkillManifest 对象，包含从 frontmatter 解析出的元数据
            # 这些元数据在 _normalize_manifest() 时就已经提取好了，这里直接使用

            # 构建额外信息（来源、标签、建议工具）
            extras: list[str] = [f"来源：{manifest.source}"]
            if manifest.tags:
                extras.append("标签：" + ", ".join(manifest.tags))
            if manifest.tools:
                extras.append("建议工具：" + ", ".join(manifest.tools))

            # 关键：添加 SKILL.md 文件路径
            # manifest.skill_file 是 Path 对象，指向 SKILL.md 文件的绝对路径
            # 模型可以用这个路径调用 read_file 工具来获取完整正文
            extras.append(f"路径：{manifest.skill_file}")

            extra_text = "；".join(extras)
            # 生成一行摘要：技能名 + 描述 + 额外信息
            lines.append(f"- `{manifest.name}`：{manifest.description}（{extra_text}）")

        return "\n".join(lines)

    def _score_manifest_for_message(self, manifest: SkillManifest, message: str) -> int:
        """根据用户消息，为技能打一个简单相关性分数。

        参数：
        - manifest: 技能元数据
        - message: 用户消息

        返回：相关性分数（0 表示不相关）

        计分规则：
        - 消息包含 "/技能名"：+10 分（用户明确调用）
        - 消息包含技能名：+5 分
        - 消息包含触发词：+3 分
        """

        text = message.lower()
        score = 0

        # 检查是否有 /技能名 的调用格式
        if f"/{manifest.name.lower()}" in text:
            score += 10

        # 检查消息是否包含技能名
        if manifest.name.lower() in text:
            score += 5

        # 检查消息是否包含触发词
        for trigger in manifest.triggers:
            trigger_text = trigger.lower().strip()
            if trigger_text and trigger_text in text:
                score += 3

        return score

    def select_skills_for_message(self, message: str, limit: int = 3) -> list[SkillManifest]:
        """从当前用户消息里挑选最相关的几个技能。

        参数：
        - message: 用户消息
        - limit: 最多返回几个技能

        返回：相关技能列表，按分数降序排列
        """

        scored: list[tuple[int, SkillManifest]] = []

        for manifest in self.list_visible_skills(auto_only=True):
            score = self._score_manifest_for_message(manifest, message)
            if score > 0:
                scored.append((score, manifest))

        # 按分数降序，名称升序排序
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [manifest for _, manifest in scored[:limit]]

    def load_skill_body(self, name: str) -> str:
        """读取某个技能的正文，不含 frontmatter。

        参数：
        - name: 技能名称

        返回：技能正文 Markdown，技能不存在时返回空字符串
        """

        manifest = self.get_manifest(name)
        if manifest is None:
            return ""

        content = manifest.skill_file.read_text(encoding="utf-8")
        _frontmatter, body = _extract_frontmatter_and_body(content)
        return body

    def load_skill_context(self, name: str) -> str:
        """读取某个技能，并包装成可直接注入 prompt 的文本块。

        参数：
        - name: 技能名称

        返回：格式化的技能文本块

        格式：
        ## 技能：skill-name

        技能正文内容...
        """

        manifest = self.get_manifest(name)
        if manifest is None:
            return ""

        body = self.load_skill_body(name)
        if not body:
            return ""

        return f"## 技能：{manifest.name}\n\n{body}"

    def load_relevant_skill_contexts(self, message: str, limit: int = 3) -> str:
        """根据用户消息，按需加载相关技能正文。

        参数：
        - message: 用户消息
        - limit: 最多加载几个技能

        返回：合并后的技能正文，用 --- 分隔
        """

        selected = self.select_skills_for_message(message, limit=limit)
        if not selected:
            return ""

        parts = [self.load_skill_context(manifest.name) for manifest in selected]
        parts = [part for part in parts if part]
        return "\n\n---\n\n".join(parts)
