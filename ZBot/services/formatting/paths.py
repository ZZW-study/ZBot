"""路径与目录辅助函数模块。"""

import re
from pathlib import Path

# 文件名中不允许出现的不安全字符（Windows/Unix 系统保留字符）
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def ensure_dir(path: Path) -> Path:
    """确保目录存在，如果不存在则递归创建。"""
    # parents=True 递归创建所有缺失的父目录
    # exist_ok=True 目录已存在时不报错
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """将文件名中的不安全字符替换为下划线。"""
    # 用正则将所有不安全字符替换为下划线，并去除首尾空白
    return _UNSAFE_CHARS.sub("_", name).strip()


def ensure_workspace_dirs(workspace: Path) -> None:
    """创建工作区所需的必要目录。"""
    dirs = [
        workspace / "memory",
        workspace / "sessions",
        workspace / "skills",
    ]
    for d in dirs:
        if not d.exists():
            ensure_dir(d)


def resolve_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
    extra_allowed_dirs: list[Path] | None = None,
) -> Path:
    """解析文件路径，确保在允许的目录范围内"""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()

    if allowed_dir:
        all_dirs = [allowed_dir] + (extra_allowed_dirs or [])
        if not any(is_under(resolved, d) for d in all_dirs):
            raise PermissionError(f"路径 {path} 超出了允许访问的目录范围：{allowed_dir}")
    return resolved


def is_under(path: Path, directory: Path) -> bool:
    """判断 path 是否位于 directory 目录之下"""
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def preview_dir(path: Path, limit: int = 8) -> str:
    """返回目录下少量条目，给失败结果提供可行动线索。"""
    if not path.exists() or not path.is_dir():
        return ""
    try:
        names = sorted(item.name + ("/" if item.is_dir() else "") for item in path.iterdir())
    except OSError:
        return ""
    if not names:
        return "目录为空"
    preview = ", ".join(names[:limit])
    if len(names) > limit:
        preview += f", ...（共 {len(names)} 项）"
    return preview


def path_failure_hint(path: str, resolved: Path, *, expected: str, workspace: Path | None) -> str:
    """为路径类失败生成观察信息。"""
    parent = resolved.parent
    parts = [
        f"请求路径：{path}",
        f"解析后路径：{resolved}",
    ]
    if workspace is not None:
        parts.append(f"工作区：{workspace}")
    parts.append(f"期望类型：{expected}")
    if parent.exists():
        parts.append(f"父目录存在：{parent}")
        preview = preview_dir(parent)
        if preview:
            parts.append(f"父目录条目预览：{preview}")
    else:
        parts.append(f"父目录不存在：{parent}")
    return "；".join(parts)
