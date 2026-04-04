"""项目级通用辅助函数。

这个文件只放“跨模块都会用到、逻辑又足够小”的辅助能力，避免把这类碎逻辑
分散到 `context`、`session`、`cron` 等模块里重复实现。
"""

from __future__ import annotations

import re
from pathlib import Path


_IMAGE_SIGNATURES: tuple[tuple[bytes, slice | None, bytes | None, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", None, None, "image/png"),
    (b"\xff\xd8\xff", None, None, "image/jpeg"),
    (b"GIF87a", None, None, "image/gif"),
    (b"GIF89a", None, None, "image/gif"),
    (b"RIFF", slice(8, 12), b"WEBP", "image/webp"),
)
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def detect_image_mime(data: bytes) -> str | None:
    """根据二进制文件头快速识别常见图片 MIME 类型。

    这里只做轻量级识别，不引入额外依赖，也不尝试覆盖所有格式。
    当前只服务于上下文构建阶段对图片附件的判断，因此识别 PNG/JPEG/GIF/WEBP
    就已经足够。
    """
    for prefix, check_slice, expected, mime in _IMAGE_SIGNATURES:
        if not data.startswith(prefix):
            continue
        if check_slice is not None and data[check_slice] != expected:
            continue
        return mime
    return None


def ensure_dir(path: Path) -> Path:
    """确保目录存在，并把路径对象原样返回。

    这样调用方可以直接写：
    `memory_dir = ensure_dir(workspace / "memory")`
    避免先 mkdir 再返回路径的重复模板代码。
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str) -> str:
    """把不适合文件名的字符替换为下划线。

    这里不是做严格的跨平台规范化，只处理最常见、最容易出问题的一组字符，
    目标是让 session key、chat id 这类运行时标识能稳定落盘。
    """
    return _UNSAFE_CHARS.sub("_", name).strip()


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """把内置模板同步到工作区。

    同步策略刻意保持保守：
    1. 只在目标文件不存在时写入，绝不覆盖用户已有内容。
    2. 返回新增文件列表，调用方可以据此打印提示或做进一步处理。
    3. 即使模板资源缺失，也返回空列表而不是抛异常，避免初始化流程被打断。
    """
    from importlib.resources import files as pkg_files

    try:
        templates = pkg_files("nanobot") / "templates"
    except Exception:
        return []

    if not templates.is_dir():
        return []

    added: list[str] = []

    def write_template(src, dest: Path) -> None:
        """仅在目标不存在时写模板。

        `src` 为 `None` 时表示创建空文件，这里用于 `HISTORY.md`。
        """
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = "" if src is None else src.read_text(encoding="utf-8")
        dest.write_text(content, encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    for item in templates.iterdir():
        if item.name.endswith(".md"):
            write_template(item, workspace / item.name)

    write_template(templates / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    write_template(None, workspace / "memory" / "HISTORY.md")
    (workspace / "skills").mkdir(parents=True, exist_ok=True)

    if added and not silent:
        from rich.console import Console

        console = Console()
        for name in added:
            console.print(f"[dim]已创建模板：{name}[/dim]")

    return added
