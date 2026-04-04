"""文件系统工具集：读取、写入、编辑、列出目录。"""

import difflib
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _resolve_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
    extra_allowed_dirs: list[Path] | None = None,
) -> Path:
    """
    解析文件路径，并确保路径在允许的目录范围内。

    参数：
        path: 原始路径字符串，可以是绝对路径或相对路径。
        workspace: 工作区根目录，用于解析相对路径。
        allowed_dir: 允许访问的根目录，用于安全检查。
        extra_allowed_dirs: 额外的允许目录列表。

    返回：
        解析后的绝对路径对象。

    抛出：
        PermissionError: 如果解析后的路径不在任何允许的目录内。
    """
    p = Path(path).expanduser()          # 展开用户目录（如 ~）
    if not p.is_absolute() and workspace:
        p = workspace / p                 # 相对路径拼接工作区
    resolved = p.resolve()                # 解析符号链接，得到绝对路径

    if allowed_dir:
        # 收集所有允许的目录
        all_dirs = [allowed_dir] + (extra_allowed_dirs or [])
        # 检查解析后的路径是否至少在一个允许目录内
        # 使用 _is_under 逐一判断，避免简单前缀比较带来的越界风险
        if not any(_is_under(resolved, d) for d in all_dirs):
            raise PermissionError(f"路径 {path} 超出了允许访问的目录范围：{allowed_dir}")
    return resolved


def _strip_code_fence(content: str) -> str:
    """
    如果内容被 Markdown 三反引号或三波浪线包裹，去除外层围栏并返回内部代码。
    只处理在全文首尾成对出现的外层围栏，保留其它内容不变。
    """
    m = re.match(r'^\s*(```|~~~)[^\n]*\n([\s\S]*?)\n\1\s*$', content, re.DOTALL)
    if m:
        return m.group(2)
    return content


def _is_under(path: Path, directory: Path) -> bool:
    """
    判断 path 是否位于 directory 目录之下（包括本身）。

    参数：
        path: 待检查的路径
        directory: 基准目录

    返回：
        如果 path 在 directory 内则返回 True，否则 False。
    """
    try:
        # 尝试计算相对路径，如果抛出 ValueError 则表示不在目录下
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


class _FsTool(Tool):
    """文件系统工具的共享基类，负责初始化工作区和路径解析。"""

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        extra_allowed_dirs: list[Path] | None = None,
    ):
        """
        初始化文件系统工具。

        参数：
            workspace: 工作区根目录，用于相对路径解析。
            allowed_dir: 允许访问的目录限制。
            extra_allowed_dirs: 额外的允许目录列表。
        """
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        self._extra_allowed_dirs = extra_allowed_dirs

    def _resolve(self, path: str) -> Path:
        """内部辅助方法：根据当前配置解析路径。"""
        # 统一调用 _resolve_path，集中做权限与工作区解析逻辑
        return _resolve_path(path, self._workspace, self._allowed_dir, self._extra_allowed_dirs)


# ---------------------------------------------------------------------------
# read_file 工具：读取文件内容
# ---------------------------------------------------------------------------

class ReadFileTool(_FsTool):
    """读取文件内容，支持基于行号的分页。"""

    _MAX_CHARS = 128_000      # 返回结果的最大字符数限制
    _DEFAULT_LIMIT = 2000     # 默认读取的行数

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "读取文件内容。返回带行号的行。"
            "可使用 offset 和 limit 对大文件进行分页读取。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """定义工具的 JSON Schema 参数。"""
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径"},
                "offset": {
                    "type": "integer",
                    "description": "起始行号（1 索引，默认为 1）",
                    "minimum": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "最多读取的行数（默认 2000）",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, offset: int = 1, limit: int | None = None, **kwargs: Any) -> str:
        """
        执行文件读取。

        参数：
            path: 文件路径
            offset: 起始行号（从1开始）
            limit: 最大行数（可选，默认 _DEFAULT_LIMIT）

        返回：
            带行号的文本内容，或错误信息。
        """
        try:
            # 解析并校验路径（含工作区与允许目录检查）
            fp = self._resolve(path)          # 解析路径，安全检查
            if not fp.exists():
                return f"错误：文件不存在：{path}"
            if not fp.is_file():
                return f"错误：目标不是文件：{path}"

            # 读取文件文本并标准化为 LF 换行，便于后续按行处理
            all_lines = fp.read_text(encoding="utf-8").splitlines()
            total = len(all_lines)

            # 边界校验与空文件处理
            if offset < 1:
                offset = 1
            if total == 0:
                return f"（空文件：{path}）"
            if offset > total:
                return f"错误：起始行号 {offset} 超出了文件末尾（总行数 {total}）"

            # 计算需要读取的行区间并生成带行号的输出
            start = offset - 1
            end = min(start + (limit or self._DEFAULT_LIMIT), total)
            numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
            result = "\n".join(numbered)

            # 防止返回体过大，对字符数超限进行截断
            if len(result) > self._MAX_CHARS:
                trimmed, chars = [], 0
                for line in numbered:
                    chars += len(line) + 1
                    if chars > self._MAX_CHARS:
                        break
                    trimmed.append(line)
                end = start + len(trimmed)
                result = "\n".join(trimmed)

            # 添加分页或结束提示，便于用户继续翻页或知道已到文件末尾
            if end < total:
                result += f"\n\n（当前显示第 {offset} 到 {end} 行，共 {total} 行；如需继续，请使用 offset={end + 1}）"
            else:
                result += f"\n\n（文件结束，共 {total} 行）"
            return result

        except PermissionError as e:
            return f"错误：{e}"
        except Exception as e:
            return f"错误：读取文件失败：{e}"


# ---------------------------------------------------------------------------
# write_file 工具：写入文件
# ---------------------------------------------------------------------------

class WriteFileTool(_FsTool):
    """将内容写入文件，自动创建父目录。"""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "将内容写入指定路径的文件。如果父目录不存在，会自动创建。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要写入的文件路径"},
                "content": {"type": "string", "description": "要写入的内容"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        """
        执行文件写入。

        参数：
            path: 文件路径
            content: 要写入的内容

        返回：
            成功或错误信息。
        """
        try:
            fp = self._resolve(path)
            # 确保父目录存在，再写入（原子性可由上层/工具框架额外保障）
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return f"已成功写入文件：{fp}（共 {len(content)} 个字符）"
        except PermissionError as e:
            return f"错误：{e}"
        except Exception as e:
            return f"错误：写入文件失败：{e}"


# ---------------------------------------------------------------------------
# edit_file 工具：编辑文件（替换文本）
# ---------------------------------------------------------------------------

def _find_match(content: str, old_text: str) -> tuple[str | None, int]:
    """
    在内容中定位旧文本，支持宽松匹配。

    先精确查找整个字符串，如果失败则尝试按行进行 strip 后匹配（滑动窗口）。
    输入内容已统一为 LF 换行符（由调用方规范化）。

    参数：
        content: 文件内容（LF 换行）
        old_text: 要查找的文本（LF 换行）

    返回：
        (matched_fragment, count) 或 (None, 0)
        matched_fragment 是实际匹配到的文本（可能与 old_text 略有空白差异）
        count 是匹配次数
    """
    # 精确匹配（整个字符串）
    if old_text in content:
        return old_text, content.count(old_text)

    old_lines = old_text.splitlines()
    if not old_lines:
        return None, 0

    # 将旧文本的每行去掉首尾空白
    stripped_old = [line.strip() for line in old_lines]
    content_lines = content.splitlines()

    candidates = []
    # 滑动窗口，按行比较去除空白后的内容
    for i in range(len(content_lines) - len(stripped_old) + 1):
        window = content_lines[i : i + len(stripped_old)]
        if [line.strip() for line in window] == stripped_old:
            candidates.append("\n".join(window))

    if candidates:
        # 返回第一个匹配到的片段及其出现次数
        return candidates[0], len(candidates)
    return None, 0


class EditFileTool(_FsTool):
    """通过替换文本来编辑文件，支持模糊匹配和可选的全替换。"""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "编辑文件，将 old_text 替换为 new_text。"
            "支持轻微的空白/换行符差异。"
            "设置 replace_all=true 可替换所有出现的位置。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要编辑的文件路径"},
                "old_text": {"type": "string", "description": "要查找并替换的文本"},
                "new_text": {"type": "string", "description": "替换成的新文本"},
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换所有出现（默认为 false）",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(
        self, path: str, old_text: str, new_text: str,
        replace_all: bool = False, **kwargs: Any,
    ) -> str:
        """
        执行文件编辑。

        参数：
            path: 文件路径
            old_text: 要查找的文本
            new_text: 替换文本
            replace_all: 是否替换所有匹配项

        返回：
            成功或错误信息。
        """
        try:
            fp = self._resolve(path)
            if not fp.exists():
                return f"错误：文件不存在：{path}"

            # 读取原始字节，检测换行符类型（CRLF 或 LF），并统一为 LF 方便匹配
            raw = fp.read_bytes()
            uses_crlf = b"\r\n" in raw
            content = raw.decode("utf-8").replace("\r\n", "\n")

            # 在统一格式下查找要替换的片段（支持宽松匹配）
            match, count = _find_match(content, old_text.replace("\r\n", "\n"))

            if match is None:
                # 未找到时返回带 diff 的提示，帮助用户定位最接近的片段
                return self._not_found_msg(old_text, content, path)

            # 如果匹配出现多次且未明确要求全部替换，则拒绝以避免误替换
            if count > 1 and not replace_all:
                return (
                    f"警告：old_text 在文件中出现了 {count} 次。"
                    "请补充更多上下文让它唯一，或显式传入 replace_all=true。"
                )

            # 规范化替换文本并执行替换操作（可选全替换）
            norm_new = new_text.replace("\r\n", "\n")
            new_content = content.replace(match, norm_new) if replace_all else content.replace(match, norm_new, 1)

            # 恢复原文件的换行风格（若之前是 CRLF）
            if uses_crlf:
                new_content = new_content.replace("\n", "\r\n")

            # 写回文件并返回成功信息
            fp.write_bytes(new_content.encode("utf-8"))
            return f"已成功编辑文件：{fp}"

        except PermissionError as e:
            return f"错误：{e}"
        except Exception as e:
            return f"错误：编辑文件失败：{e}"

    @staticmethod
    def _not_found_msg(old_text: str, content: str, path: str) -> str:
        """
        生成未找到文本时的错误信息，包含最佳匹配的 diff。

        参数：
            old_text: 要查找的文本（原始，可能含 CRLF）
            content: 文件内容（已统一为 LF）
            path: 文件路径

        返回：
            格式化的错误字符串。
        """
        # 将内容按行分割（保留行尾换行符）
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)

        # 滑动窗口，计算每段与 old_lines 的相似度，找到最佳匹配位置
        best_ratio, best_start = 0.0, 0
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        # 如果相似度超过 50%，生成 unified diff 帮助用户定位
        if best_ratio > 0.5:
            diff = "\n".join(difflib.unified_diff(
                old_lines, lines[best_start : best_start + window],
                fromfile="old_text（输入内容）",
                tofile=f"{path}（文件实际内容，第 {best_start + 1} 行起）",
                lineterm="",
            ))
            return (
                f"错误：在 {path} 中找不到 old_text。\n"
                f"最接近的片段位于第 {best_start + 1} 行起（相似度 {best_ratio:.0%}）：\n{diff}"
            )
        return f"错误：在 {path} 中找不到 old_text，且没有发现足够接近的片段。请先核对文件内容。"


# ---------------------------------------------------------------------------
# list_dir 工具：列出目录内容
# ---------------------------------------------------------------------------

class ListDirTool(_FsTool):
    """列出目录内容，支持递归，并自动忽略常见噪声目录。"""

    _DEFAULT_MAX = 200        # 默认最大条目数
    # 自动忽略的目录名（常见版本控制、虚拟环境、构建产物等）
    _IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".coverage", "htmlcov",
    }

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return (
            "列出目录内容。"
            "设置 recursive=true 可递归显示嵌套结构。"
            "常见噪声目录（.git, node_modules, __pycache__ 等）会被自动忽略。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要列出的目录路径"},
                "recursive": {
                    "type": "boolean",
                    "description": "是否递归列出所有文件（默认 false）",
                },
                "max_entries": {
                    "type": "integer",
                    "description": "最多返回的条目数（默认 200）",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }

    async def execute(
        self, path: str, recursive: bool = False,
        max_entries: int | None = None, **kwargs: Any,
    ) -> str:
        """
        执行目录列表。

        参数：
            path: 目录路径
            recursive: 是否递归
            max_entries: 最大条目数限制

        返回：
            格式化的目录内容列表，或错误信息。
        """
        try:
            dp = self._resolve(path)
            if not dp.exists():
                return f"错误：目录不存在：{path}"
            if not dp.is_dir():
                return f"错误：目标不是目录：{path}"

            cap = max_entries or self._DEFAULT_MAX
            items: list[str] = []
            total = 0

            if recursive:
                # 递归遍历所有子项，但忽略噪声目录
                for item in sorted(dp.rglob("*")):
                    # 如果路径中包含忽略目录，跳过
                    if any(p in self._IGNORE_DIRS for p in item.parts):
                        continue
                    total += 1
                    if len(items) < cap:
                        rel = item.relative_to(dp)
                        # 目录后加斜杠标识，文件不加
                        items.append(f"{rel}/" if item.is_dir() else str(rel))
            else:
                # 非递归：只列出直接子项
                for item in sorted(dp.iterdir()):
                    if item.name in self._IGNORE_DIRS:
                        continue
                    total += 1
                    if len(items) < cap:
                        pfx = "[DIR] " if item.is_dir() else "[FILE] "
                        items.append(f"{pfx}{item.name}")

            if not items and total == 0:
                return f"目录为空：{path}"

            result = "\n".join(items)
            # 如果条目过多，提示截断
            if total > cap:
                result += f"\n\n（结果已截断，当前显示前 {cap} 项，共 {total} 项）"
            return result

        except PermissionError as e:
            return f"错误：{e}"
        except Exception as e:
            return f"错误：列出目录失败：{e}"
