"""通用辅助函数模块。"""
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


def ensure_workspace_dirs(workspace: Path) ->None:
    """创建工作区所需的必要目录。"""
    dirs = [
        workspace / "memory",
        workspace / "sessions",
        workspace / "skills",
    ]
    for d in dirs:
        if not d.exists():
            ensure_dir(d)
