#!/usr/bin/env python3
"""
nanobot 技能文件夹极简校验工具
用于校验技能文件夹结构、SKILL.md 格式、配置项合法性
"""

import re
import sys
from pathlib import Path
from typing import Optional

# 尝试导入yaml库，用于解析前端配置
try:
    import yaml
except ModuleNotFoundError:
    yaml = None

# ===================== 常量配置 =====================
# 技能名称最大长度
MAX_SKILL_NAME_LENGTH = 64
# 允许的SKILL.md前端配置键名
ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "metadata",
    "always",
    "license",
    "allowed-tools",
}
# 允许的资源目录名称
ALLOWED_RESOURCE_DIRS = {"scripts", "references", "assets"}
# 占位符标记（校验是否未替换TODO）
PLACEHOLDER_MARKERS = ("[todo", "todo:")


def _extract_frontmatter(content: str) -> Optional[str]:
    """
    私有函数：从SKILL.md内容中提取YAML前端配置（--- 包裹的部分）
    Args:
        content: SKILL.md 文件完整文本
    Returns:
        提取到的前端配置文本，无则返回None
    """
    lines = content.splitlines()
    # 首行必须是 --- 才是合法的前端配置格式
    if not lines or lines[0].strip() != "---":
        return None
    # 查找结束的 --- 分割线
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def _parse_simple_frontmatter(frontmatter_text: str) -> Optional[dict[str, str]]:
    """
    私有函数：简易前端配置解析器（未安装PyYAML时的降级方案）
    仅支持基础的键值对格式
    Args:
        frontmatter_text: 前端配置纯文本
    Returns:
        解析后的字典，失败返回None
    """
    parsed: dict[str, str] = {}
    current_key: Optional[str] = None
    multiline_key: Optional[str] = None

    for raw_line in frontmatter_text.splitlines():
        stripped = raw_line.strip()
        # 跳过空行和注释
        if not stripped or stripped.startswith("#"):
            continue

        # 判断是否为缩进的多行文本
        is_indented = raw_line[:1].isspace()
        if is_indented:
            if current_key is None:
                return None
            current_value = parsed[current_key]
            parsed[current_key] = f"{current_value}\n{stripped}" if current_value else stripped
            continue

        # 必须包含冒号分隔键值
        if ":" not in stripped:
            return None

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            return None

        # 处理多行文本标记 | >
        if value in {"|", ">"}:
            parsed[key] = ""
            current_key = key
            multiline_key = key
            continue

        # 去除字符串首尾引号
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        parsed[key] = value
        current_key = key
        multiline_key = None

    if multiline_key is not None and multiline_key not in parsed:
        return None
    return parsed


def _load_frontmatter(frontmatter_text: str) -> tuple[Optional[dict], Optional[str]]:
    """
    私有函数：加载并解析前端配置
    优先使用PyYAML，无则使用简易解析器
    Args:
        frontmatter_text: 前端配置文本
    Returns:
        (解析结果, 错误信息) 成功则错误信息为None
    """
    if yaml is not None:
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as exc:
            return None, f"前端配置YAML格式无效：{exc}"
        if not isinstance(frontmatter, dict):
            return None, "前端配置必须是YAML字典格式"
        return frontmatter, None

    # 无PyYAML时使用简易解析
    frontmatter = _parse_simple_frontmatter(frontmatter_text)
    if frontmatter is None:
        return None, "前端配置YAML格式无效：未安装PyYAML，不支持复杂语法"
    return frontmatter, None


def _validate_skill_name(name: str, folder_name: str) -> Optional[str]:
    """
    私有函数：校验技能名称格式
    要求：小写短横线格式、长度合规、与文件夹名称一致
    Args:
        name: 配置中的技能名称
        folder_name: 技能文件夹名称
    Returns:
        错误信息，校验通过返回None
    """
    # 正则校验：仅允许小写字母、数字、单短横线
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return (
            f"名称 '{name}' 必须为短横线格式 "
            "(仅允许小写字母、数字和单个短横线)"
        )
    # 长度校验
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return (
            f"名称过长（{len(name)}个字符）。"
            f"最大长度限制：{MAX_SKILL_NAME_LENGTH}个字符。"
        )
    # 名称必须与文件夹名一致
    if name != folder_name:
        return f"技能名称 '{name}' 必须与文件夹名称 '{folder_name}' 一致"
    return None


def _validate_description(description: str) -> Optional[str]:
    """
    私有函数：校验技能描述合法性
    Args:
        description: 技能描述文本
    Returns:
        错误信息，校验通过返回None
    """
    trimmed = description.strip()
    # 不能为空
    if not trimmed:
        return "描述不能为空"
    # 不能包含TODO占位符
    lowered = trimmed.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return "描述中仍包含TODO占位文本，请替换为实际内容"
    # 不能包含尖括号
    if "<" in trimmed or ">" in trimmed:
        return "描述中不能包含尖括号（< 或 >）"
    # 长度限制
    if len(trimmed) > 1024:
        return f"描述过长（{len(trimmed)}个字符）。最大长度限制：1024个字符。"
    return None


def validate_skill(skill_path):
    """
    核心函数：完整校验技能文件夹
    校验内容：文件夹存在性、SKILL.md存在性、前端配置、目录结构
    Args:
        skill_path: 技能文件夹路径
    Returns:
        (是否合法, 提示信息)
    """
    skill_path = Path(skill_path).resolve()

    # 校验文件夹是否存在
    if not skill_path.exists():
        return False, f"技能文件夹不存在：{skill_path}"
    if not skill_path.is_dir():
        return False, f"路径不是文件夹：{skill_path}"

    # 校验SKILL.md文件
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, "未找到SKILL.md文件"

    # 读取文件内容
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"无法读取SKILL.md：{exc}"

    # 提取前端配置
    frontmatter_text = _extract_frontmatter(content)
    if frontmatter_text is None:
        return False, "前端配置格式无效（必须以---包裹）"

    # 解析前端配置
    frontmatter, error = _load_frontmatter(frontmatter_text)
    if error:
        return False, error

    # 校验不允许的配置项
    unexpected_keys = sorted(set(frontmatter.keys()) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected_keys:
        allowed = ", ".join(sorted(ALLOWED_FRONTMATTER_KEYS))
        unexpected = ", ".join(unexpected_keys)
        return (
            False,
            f"SKILL.md前端配置中存在不允许的键：{unexpected}。允许的配置项：{allowed}",
        )

    # 校验必填项
    if "name" not in frontmatter:
        return False, "前端配置缺少必填项：name"
    if "description" not in frontmatter:
        return False, "前端配置缺少必填项：description"

    # 校验技能名称
    name = frontmatter["name"]
    if not isinstance(name, str):
        return False, f"name必须是字符串类型，当前类型：{type(name).__name__}"
    name_error = _validate_skill_name(name.strip(), skill_path.name)
    if name_error:
        return False, name_error

    # 校验技能描述
    description = frontmatter["description"]
    if not isinstance(description, str):
        return False, f"description必须是字符串类型，当前类型：{type(description).__name__}"
    description_error = _validate_description(description)
    if description_error:
        return False, description_error

    # 校验always字段（布尔值）
    always = frontmatter.get("always")
    if always is not None and not isinstance(always, bool):
        return False, f"'always'必须是布尔值，当前类型：{type(always).__name__}"

    # 校验根目录文件/文件夹合法性
    for child in skill_path.iterdir():
        if child.name == "SKILL.md":
            continue
        if child.is_dir() and child.name in ALLOWED_RESOURCE_DIRS:
            continue
        if child.is_symlink():
            continue
        return (
            False,
            f"技能根目录存在不允许的文件/文件夹：{child.name}。"
            "仅允许SKILL.md、scripts/、references/、assets/。",
        )

    # 所有校验通过
    return True, "技能格式校验通过！"


if __name__ == "__main__":
    # 主程序入口：处理命令行参数
    if len(sys.argv) != 2:
        print("用法：python quick_validate.py <技能文件夹路径>")
        sys.exit(1)

    # 执行校验并输出结果
    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)