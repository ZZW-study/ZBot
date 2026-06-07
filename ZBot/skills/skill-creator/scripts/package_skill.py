#!/usr/bin/env python3
"""
技能打包器 - 为技能文件夹创建可分发的 .skill 文件

用法:
    python package_skill.py <path/to/skill-folder> [output-directory]

示例:
    python package_skill.py skills/public/my-skill
    python package_skill.py skills/public/my-skill ./dist
"""

import sys
import zipfile
from contextlib import suppress
from pathlib import Path

from quick_validate import validate_skill


def _is_within(path: Path, root: Path) -> bool:
    with suppress(ValueError):
        path.relative_to(root)
        return True
    return False


def _cleanup_partial_archive(skill_filename: Path) -> None:
    if skill_filename.exists():
        with suppress(OSError):
            skill_filename.unlink()


def package_skill(skill_path, output_dir=None):
    """
    将技能文件夹打包为 .skill 文件。

    Args:
        skill_path: 技能文件夹的路径
        output_dir: .skill 文件的可选输出目录(默认为当前目录)

    Returns:
        已创建 .skill 文件的路径,出错时返回 None
    """
    skill_path = Path(skill_path).resolve()

    # 验证技能文件夹是否存在
    if not skill_path.exists():
        print(f"[ERROR] Skill folder not found: {skill_path}")
        return None

    if not skill_path.is_dir():
        print(f"[ERROR] Path is not a directory: {skill_path}")
        return None

    # 验证 SKILL.md 是否存在
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        print(f"[ERROR] SKILL.md not found in {skill_path}")
        return None

    # 在打包前运行验证
    print("Validating skill...")
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"[ERROR] Validation failed: {message}")
        print("   Please fix the validation errors before packaging.")
        return None
    print(f"[OK] {message}\n")

    # 确定输出位置
    skill_name = skill_path.name
    if output_dir:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path.cwd()

    skill_filename = output_path / f"{skill_name}.skill"

    EXCLUDED_DIRS = {".git", ".svn", ".hg", "__pycache__", "node_modules"}

    files_to_package = []
    resolved_archive = skill_filename.resolve()

    for file_path in skill_path.rglob("*"):
        # 对符号链接采取失败关闭策略,确保打包内容明确可预测。
        if file_path.is_symlink():
            print(f"[ERROR] Symlink not allowed in packaged skill: {file_path}")
            _cleanup_partial_archive(skill_filename)
            return None

        rel_parts = file_path.relative_to(skill_path).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue

        if file_path.is_file():
            resolved_file = file_path.resolve()
            if not _is_within(resolved_file, skill_path):
                print(f"[ERROR] File escapes skill root: {file_path}")
                _cleanup_partial_archive(skill_filename)
                return None
            # 如果输出位置在 skill_path 之下,避免将归档写入自身。
            if resolved_file == resolved_archive:
                print(f"[WARN] Skipping output archive: {file_path}")
                continue
            files_to_package.append(file_path)

    # 创建 .skill 文件(zip 格式)
    try:
        with zipfile.ZipFile(skill_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_to_package:
                # 计算 zip 内的相对路径。
                arcname = Path(skill_name) / file_path.relative_to(skill_path)
                zipf.write(file_path, arcname)
                print(f"  Added: {arcname}")

        print(f"\n[OK] Successfully packaged skill to: {skill_filename}")
        return skill_filename

    except Exception as e:
        _cleanup_partial_archive(skill_filename)
        print(f"[ERROR] Error creating .skill file: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Usage: python package_skill.py <path/to/skill-folder> [output-directory]")
        print("\nExample:")
        print("  python package_skill.py skills/public/my-skill")
        print("  python package_skill.py skills/public/my-skill ./dist")
        sys.exit(1)

    skill_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Packaging skill: {skill_path}")
    if output_dir:
        print(f"   Output directory: {output_dir}")
    print()

    result = package_skill(skill_path, output_dir)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
