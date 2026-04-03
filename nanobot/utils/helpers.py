"""nanobot 项目的通用工具函数模块,封装项目里反复用到的公共功能（图片检测、文件操作、文本处理、模板同步等）"""

import re
from pathlib import Path


def detect_image_mime(data: bytes) -> str:
    """
    【核心功能】通过图片的「文件头数据」检测图片格式
    不看文件后缀名（防止后缀改了但实际是别的图片）
    :param data: 图片的原始二进制数据（比如从WhatsApp收到的图片）
    :return: 图片格式字符串（image/png等），不认识的格式返回None
    """
    # 判断前8个字节 == PNG图片的固定文件头 → 返回PNG格式
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    return None


def ensure_dir(path: Path) -> Path:
    """创建文件"""
    path.mkdir(parents=True, exist_ok=True)
    return path


# Windows系统禁止文件名包含 <>:"/\\|?* 这些字符
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_filename(name: str) -> str:
    """
    把普通字符串转换成「安全的文件名」
    :param name: 原始文件名（可能包含非法字符）
    """
    return _UNSAFE_CHARS.sub('_', name).strip()  # 把非法字符替换成 _ ，并去除字符串首尾的空格/换行


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """
    【核心功能】同步项目内置的模板文件到你的工作区文件夹
    只创建「缺失的文件」，不会覆盖你已修改的文件
    用途：初始化项目时，自动生成配置文件、说明文档、文件夹
    :param workspace: 你的本地工作区路径（就是你电脑上的nanobot文件夹）
    :param silent: 是否静默运行（True=不打印日志，False=打印创建的文件）
    :return: 本次新创建的文件路径列表
    """
    from importlib.resources import files as pkg_files  # 读取 Python 包内部的静态文件
    try:
        # 获取项目内置的 templates 模板文件夹,返回一个Traversable对象
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        return []
    if not tpl.is_dir():  # 是否是目录
        return []

    added: list[str] = []  # 记录本次新创建的文件

    # 内部函数：把源文件复制到目标路径（仅当目标文件不存在时）
    def _write(src, dest: Path):
        if dest.exists():
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))  # 计算出 dest 路径 相对于 workspace 路径的【相对路径】

    # 遍历内置模板文件夹里的所有 .md 说明文档 → 同步到工作区
    for item in tpl.iterdir():
        if item.name.endswith(".md"):
            _write(item, workspace / item.name)

    # 同步 memory 文件夹的 MEMORY.md 文档
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    # 创建空的 HISTORY.md 聊天记录文件
    _write(None, workspace / "memory" / "HISTORY.md")
    # 创建 skills 技能文件夹（存放自定义功能）
    (workspace / "skills").mkdir(parents=True, exist_ok=True)

    if added and not silent:
        from rich.console import Console
        console = Console()
        for name in added:
            console.print(f"[dim]创建了{name}[/dim]")  # 开启「淡色」样式

    return added
