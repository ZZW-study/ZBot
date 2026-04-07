#!/usr/bin/env python3
"""
技能打包工具 - 将技能文件夹打包为可分发的 .skill 格式文件
"""
技能打包工具 - 将技能文件夹打包为可分发的 .skill 文件（ZIP 格式）

用法：
    python package_skill.py <技能文件夹路径> [输出目录]

示例：
    python package_skill.py skills/public/my-skill
    python package_skill.py skills/public/my-skill ./dist

说明：本脚本会执行基本的安全与格式校验，确保生成的 .skill 包不包含符号链接、
也不会将输出压缩包自身包含进压缩文件中，适用于本地打包与发布前的检查。
"""
import zipfile
from pathlib import Path

# 导入技能校验工具
from quick_validate import validate_skill


def _is_within(path: Path, root: Path) -> bool:
    """判断文件路径是否位于指定根目录内部，防止路径穿越攻击。

    返回 True 表示 path 在 root 内部；否则返回 False。
    """
    try:
        # 尝试获取相对路径，成功则说明在根目录内
        path.relative_to(root)
        return True
    except ValueError:
        # 抛出异常说明路径超出根目录范围
        return False


def _cleanup_partial_archive(skill_filename: Path) -> None:
    """删除打包失败时遗留的不完整压缩文件，忽略删除错误。"""
    try:
        if skill_filename.exists():
            skill_filename.unlink()
    except OSError:
        # 忽略删除失败的异常
        pass


def package_skill(skill_path, output_dir=None):
    """将技能目录打包为 `.skill` 文件（ZIP），并返回生成的文件路径。

    参数：
    - skill_path: 技能目录路径（字符串或 Path）
    - output_dir: 可选的输出目录（未指定则使用当前工作目录）

    返回：打包成功返回 Path 对象；失败返回 None。
    """
    # 标准化路径为绝对路径
    skill_path = Path(skill_path).resolve()

    # 校验1：技能文件夹是否存在
    if not skill_path.exists():
        print(f"[错误] 技能文件夹不存在：{skill_path}")
        return None

    # 校验2：路径是否为文件夹
    if not skill_path.is_dir():
        print(f"[错误] 指定路径不是文件夹：{skill_path}")
        return None

    # 校验3：必须包含 SKILL.md 核心文件
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        print(f"[错误] 技能文件夹内未找到 SKILL.md：{skill_path}")
        return None

    # 打包前执行技能格式校验
    print("正在校验技能格式...")
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"[错误] 技能校验失败：{message}")
        print("   请修复校验错误后重新打包。")
        return None
    print(f"[成功] {message}\n")

    # 确定输出文件路径
    skill_name = skill_path.name
    if output_dir:
        # 用户指定输出目录，创建目录（支持多级）
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        # 默认输出到当前工作目录
        output_path = Path.cwd()

    # 最终打包文件名：技能名.skill
    skill_filename = output_path / f"{skill_name}.skill"

    # 打包时需要排除的目录（版本控制、缓存、依赖文件夹）
    EXCLUDED_DIRS = {".git", ".svn", ".hg", "__pycache__", "node_modules"}

    # 待打包的文件列表
    files_to_package = []
    # 打包文件的绝对路径（用于自引用判断）
    resolved_archive = skill_filename.resolve()

    # 递归遍历技能文件夹下所有文件
    for file_path in skill_path.rglob("*"):
        # 安全校验：禁止打包符号链接（防止路径漏洞）
        if file_path.is_symlink():
            print(f"[错误] 技能包中不允许包含符号链接：{file_path}")
            _cleanup_partial_archive(skill_filename)
            return None

        # 获取文件相对路径的各部分，检查是否需要排除
        rel_parts = file_path.relative_to(skill_path).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue

        # 只处理文件，跳过目录
        if file_path.is_file():
            resolved_file = file_path.resolve()
            # 校验：文件不能超出技能根目录
            if not _is_within(resolved_file, skill_path):
                print(f"[错误] 文件超出技能根目录范围：{file_path}")
                _cleanup_partial_archive(skill_filename)
                return None
            # 避免将打包后的文件自身加入压缩包（自引用）
            if resolved_file == resolved_archive:
                print(f"[警告] 跳过输出压缩包自身：{file_path}")
                continue
            # 符合条件的文件加入打包列表
            files_to_package.append(file_path)

    # 创建 .skill 压缩包（ZIP_DEFLATED 启用压缩）
    try:
        with zipfile.ZipFile(skill_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in files_to_package:
                # 计算压缩包内的相对路径（保持目录结构）
                arcname = Path(skill_name) / file_path.relative_to(skill_path)
                zipf.write(file_path, arcname)
                print(f"  已添加：{arcname}")

        # 打包完成
        print(f"\n[成功] 技能打包完成，文件路径：{skill_filename}")
        return skill_filename

    except Exception as e:
        # 打包异常：清理不完整文件并报错
        _cleanup_partial_archive(skill_filename)
        print(f"[错误] 创建 .skill 文件失败：{e}")
        return None


def main():
    """主函数：处理命令行参数，调用打包逻辑"""
    # 校验命令行参数数量
    if len(sys.argv) < 2:
        print("用法：python package_skill.py <技能文件夹路径> [输出目录]")
        print("\n示例：")
        print("  python package_skill.py skills/public/my-skill")
        print("  python package_skill.py skills/public/my-skill ./dist")
        sys.exit(1)

    # 解析参数
    skill_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    # 打印打包信息
    print(f"正在打包技能：{skill_path}")
    if output_dir:
        print(f"   输出目录：{output_dir}")
    print()

    # 执行打包
    result = package_skill(skill_path, output_dir)

    # 根据结果设置退出码
    sys.exit(0 if result else 1)


# 程序入口
if __name__ == "__main__":
    main()