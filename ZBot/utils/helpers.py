"""通用辅助函数。

本模块提供一些零散但各处都会用到的工具函数，
例如目录创建、文件名清理、工作区初始化等。
"""

from __future__ import annotations

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
    """将文件名中的不安全字符替换为下划线。
    某些字符（如 / \ ? * 等）在文件系统中是非法的，
    此函数将这些字符替换为下划线，保证文件名可用。
    参数：
        name: 原始文件名

    返回：
        清理后的安全文件名
    """
    # 用正则将所有不安全字符替换为下划线，并去除首尾空白
    return _UNSAFE_CHARS.sub("_", name).strip()


def ensure_workspace_dirs(workspace: Path) ->None:
    """创建工作区所需的必要目录。
    在首次使用 ZBot 或新建工作区时，
    需要创建 memory（记忆）、skills（技能）、sessions（会话）等目录。
    """
    # 创建工作区必须存在的目录列表
    dirs = [
        workspace / "memory",    # 长期记忆和归档目录
        workspace / "skills",    # 自定义技能目录
        workspace / "sessions",  # 会话历史记录目录
    ]
    for d in dirs:
        # 目录不存在时创建
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
