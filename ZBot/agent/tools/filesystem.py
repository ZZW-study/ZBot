"""文件系统工具集：读取、写入、编辑、列出目录"""

import difflib
from pathlib import Path
from typing import Any

import aiofiles

from ZBot.agent.tools.base import Tool, format_tool_error
from ZBot.services.formatting import path_failure_hint, resolve_path


class ReadFileTool(Tool):
    """读取指定路径的文件内容，返回带行号的文本。

    核心用途：
        已知文件路径时，读取文件的具体内容来理解上下文。
        比如 grep_search 找到了某个函数在第 10 行，但你需要知道完整函数有多长、
        前后逻辑是什么，就要用 read_file 把周围代码读出来。

    典型使用场景：
        - 读取某个已知路径的源代码文件，查看函数实现
        - 配合 offset/limit 分页读取大文件（如日志、数据文件）
        - 在 edit_file 之前，先 read_file 获取真实的 old_text，避免凭猜测编辑导致匹配失败
        - 验证 edit_file 的修改结果：编辑后再 read_file 确认改动是否正确

    分页机制：
        - 默认读取前 2000 行（可通过 limit 参数调整）
        - offset 指定从第几行开始读（1 索引）
        - 返回内容超过 128,000 字符时自动截断
        - 文件末尾会提示剩余行数和下次读取的 offset 值

    与其他工具的协作关系：
        - glob_search / grep_search 负责"找到文件在哪"，read_file 负责"读出文件内容"
        - edit_file 需要 read_file 提供准确的 old_text，不能凭记忆或猜测构造
        - list_dir 负责"看目录里有什么"，read_file 负责"看文件里写了什么"
    """

    _MAX_CHARS = (
        128_000  # 返回内容的最大字符数，超出则截断.数字下划线写法,下划线只用来分隔数字、方便阅读，不影响数值大小
    )
    _DEFAULT_LIMIT = 2000  # 默认读取行数

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        """初始化读取工具的工作区和访问边界。"""
        self._workspace = workspace  # 工作区根目录
        self._allowed_dir = allowed_dir  # 允许访问的目录

    @property
    def name(self) -> str:
        """返回读取文件工具名称。"""
        return "read_file"

    @property
    def description(self) -> str:
        """返回读取文件工具说明。"""
        return (
            "读取已知文件路径的内容，并返回带行号文本。"
            "大文件用 offset/limit 分页；edit_file 前必须先 read_file 获取真实 old_text。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """返回读取文件工具参数 Schema。"""
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件路径。已知路径时直接读取；未知路径先用 list_dir 或搜索工具定位。",
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号（1 索引）。继续读取大文件时使用工具返回提示里的下一个 offset。",
                    "minimum": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "最多读取的行数（默认 2000）。读取局部上下文时设置较小值。",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """读取指定文件内容并按需分页返回。"""
        try:
            # 解析路径并检查是否在允许范围内
            path: str = kwargs.get("path", "")
            offset: int = kwargs.get("offset", 1)
            limit = kwargs.get("limit", None)
            fp = resolve_path(path, self._workspace, self._allowed_dir)
            # 检查文件是否存在
            if not fp.exists():
                return format_tool_error(
                    "文件不存在",
                    attempted=f"读取文件 {path}",
                    observed=path_failure_hint(path, fp, expected="文件", workspace=self._workspace),
                    do_not_repeat=f"不要继续用相同路径调用 read_file：{path}",
                    next_action=f"先调用 list_dir 查看父目录：{fp.parent}",
                )
            # 检查是否为普通文件（非目录）
            if not fp.is_file():
                next_action = f"如果要查看目录内容，请调用 list_dir：{path}" if fp.is_dir() else "请确认目标路径类型"
                return format_tool_error(
                    "目标不是文件",
                    attempted=f"读取文件 {path}",
                    observed=path_failure_hint(path, fp, expected="文件", workspace=self._workspace),
                    do_not_repeat=f"不要继续用 read_file 读取该路径：{path}",
                    next_action=next_action,
                )

            # 读取文件全部行
            async with aiofiles.open(fp, mode="r", encoding="utf-8") as f:
                content = await f.read()
            all_lines = content.splitlines()
            # fp.read_text(encoding="utf-8")
            # 打开文件 fp
            # 以 UTF-8 编码读取全部内容
            # 返回一个大字符串（包含所有换行、空格）
            # splitlines()
            # 把上面那个大字符串按换行符切割
            # 自动去掉换行符 \n、\r\n
            # 返回一个列表，每一项是文件的一行内容
            total = len(all_lines)  # 总行数

            # 校正 offset 为最小值 1
            if offset < 1:
                offset = 1
            # 空文件直接返回提示
            if total == 0:
                return f"（空文件：{path}）"
            # offset 超出总行数则返回错误
            if offset > total:
                return format_tool_error(
                    "起始行号超出文件末尾",
                    attempted=f"读取 {path} 的第 {offset} 行起",
                    observed=f"文件总行数为 {total}",
                    do_not_repeat=f"不要继续使用 offset={offset} 读取该文件",
                    next_action="改用更小的 offset，或根据已读取内容继续分析",
                )

            # 计算实际读取范围（offset 是 1 索引，需减 1）
            start = offset - 1
            # 结束位置取 limit 默认值和总行数的较小值
            end = min(start + (limit or self._DEFAULT_LIMIT), total)
            # 给每行加上行号前缀
            numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
            result = "\n".join(numbered)

            # 如果内容超过最大字符数，截断到限制以内
            if len(result) > self._MAX_CHARS:
                trimmed, chars = [], 0
                for line in numbered:
                    chars += len(line) + 1
                    if chars > self._MAX_CHARS:
                        break
                    trimmed.append(line)
                end = start + len(trimmed)
                result = "\n".join(trimmed)

            # 提示用户是否还有更多内容需要读取
            if end < total:
                result += f"\n\n（当前显示第 {offset} 到 {end} 行，共 {total} 行；如需继续，请使用 offset={end + 1}）"
            else:
                result += f"\n\n（文件结束，共 {total} 行）"
            return result

        except PermissionError as e:
            return format_tool_error(
                str(e),
                attempted=f"读取文件 {kwargs.get('path', '')}",
                do_not_repeat="不要重复访问同一路径",
                next_action="改用工作区内允许访问的路径，或先 list_dir 确认可访问目录",
            )
        except Exception as e:
            return format_tool_error(
                f"读取文件失败：{e}",
                attempted=f"读取文件 {kwargs.get('path', '')}",
                do_not_repeat="不要用相同参数重复读取",
                next_action="先确认路径、编码和文件类型；必要时改用 list_dir 定位文件",
            )


class WriteFileTool(Tool):
    """将指定内容写入文件，如果文件不存在则自动创建，包括所有缺失的父目录。

    核心用途：
        创建新文件或覆盖已有文件的全部内容。
        适合从零生成代码、配置文件、文档等场景。

    典型使用场景：
        - 从零创建一个新的源代码文件
        - 生成配置文件（如 .json、.yaml、.env）
        - 将分析结果或生成的内容写入文件
        - 覆盖已有文件的全部内容（注意：是全量覆盖，不是追加）

    与其他工具的协作关系：
        - 如果只想修改文件中的某段代码，应该用 edit_file 而不是 write_file
        - 写入后可以用 read_file 验证内容是否正确
        - 如果不确定文件是否存在，可以先 list_dir 查看目录，或直接 write_file（会自动创建）
    """

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        """初始化写入工具的工作区和访问边界。"""
        self._workspace = workspace  # 工作区根目录
        self._allowed_dir = allowed_dir  # 允许访问的目录

    @property
    def name(self) -> str:
        """返回写入文件工具名称。"""
        return "write_file"

    @property
    def description(self) -> str:
        """返回写入文件工具说明。"""
        return (
            "创建新文件或覆盖写入整个小文件，会自动创建父目录。"
            "局部修改已有文件优先用 edit_file；覆盖前要确认这是预期行为。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """返回写入文件工具参数 Schema。"""
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要写入的文件路径。文件已存在时会整体覆盖。"},
                "content": {"type": "string", "description": "要写入的完整文件内容，不是局部补丁。"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """把指定内容写入目标文件。"""
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")
        try:
            # 解析路径(包含了文件)并检查是否在允许范围内
            fp = resolve_path(path, self._workspace, self._allowed_dir)
            # 自动创建所有缺失的父目录
            fp.parent.mkdir(parents=True, exist_ok=True)
            # 写入文件内容, write_text() 会自动创建不存在的文件。只会创建文件本身，不会自动创建父级文件夹
            async with aiofiles.open(fp, mode="w", encoding="utf-8") as f:
                await f.write(content)

            return f"已成功写入文件：{fp}（共 {len(content)} 个字符）"
        except PermissionError as e:
            return format_tool_error(
                str(e),
                attempted=f"写入文件 {path}",
                do_not_repeat="不要重复写入同一路径",
                next_action="改用工作区内允许写入的路径",
            )
        except Exception as e:
            return format_tool_error(
                f"写入文件失败：{e}",
                attempted=f"写入文件 {path}",
                do_not_repeat="不要用相同参数重复写入",
                next_action="检查父目录、权限和内容大小后再决定是否重试",
            )


def _find_match(content: str, old_text: str) -> tuple[str | None, int]:
    """在内容中定位旧文本，支持宽松匹配（忽略缩进差异）"""
    # 先尝试精确匹配
    if old_text in content:
        return old_text, content.count(old_text)  # 返回匹配文本和出现次数

    # 精确匹配失败，按行分割进行宽松匹配
    old_lines = old_text.splitlines()
    if not old_lines:
        return None, 0  # 空文本无法匹配

    # 对旧文本的每行去除首尾空白
    stripped_old = [line.strip() for line in old_lines]
    # 同样分割文件内容
    content_lines = content.splitlines()

    # 滑动窗口遍历文件内容的每一处可能匹配的位置
    candidates = []
    for i in range(len(content_lines) - len(stripped_old) + 1):
        # 取与 old_lines 等长的窗口
        window = content_lines[i : i + len(stripped_old)]
        # 对比去除空白后的行是否一致
        if [line.strip() for line in window] == stripped_old:
            candidates.append("\n".join(window))  # 记录原始匹配内容

    # 返回第一个匹配和总匹配数
    if candidates:
        return candidates[0], len(candidates)
    return None, 0  # 未找到匹配


"""根据用户输入决定从哪里开始
用户给了明确文件路径，比如"改 src/auth.py 里的 foo 函数"：
read_file → edit_file → read_file 验证
不需要搜索，直接读取修改。
用户给了函数名但没给文件，比如"把 foo 函数替换成这个"：
grep_search("def foo") → read_file → edit_file → read_file 验证
先用 grep 找到 foo 在哪个文件哪一行，再读取完整内容，再替换。
用户给了文件名模式，比如"找所有 auth 相关文件"：
glob_search("**/*auth*") → read_file
按文件名找，不需要 grep。
用户只给了业务描述，比如"帮我改登录过期逻辑"：
list_dir → glob_search("**/*login*") → grep_search("expire|token") → read_file → edit_file → 验证
从完全不了解项目开始，一步步缩小范围。

最重要的三个原则

grep 找到位置后，必须先 read_file，不能直接 edit。因为 grep 只返回匹配的那一行，不知道完整函数有多长，直接改会破坏代码。
edit_file 的 old_text 必须来自 read_file 读到的真实内容，不能自己构造，否则容易匹配失败或误替换。
        glob 不是 grep 的前置步骤，它们是两个独立维度：glob 按文件名找，grep 按内容找。
        grep 本身支持 glob 参数缩小搜索范围，不一定要单独先调用 glob_search。
        """


class EditFileTool(Tool):
    """在文件中查找指定的旧文本并替换为新文本，实现精确的局部编辑。

    核心用途：
        只修改文件中的某一段内容，而不是覆盖整个文件。
        比如改一个函数名、替换一段逻辑、修复一个 bug，都只需要改局部代码。

    典型使用场景：
        - 修改函数实现：把旧的函数体替换为新的
        - 重命名变量/函数：在文件中批量替换某个标识符
        - 修复 bug：把错误的代码行替换为正确的
        - 添加/修改 import 语句、配置项等

    与其他工具的协作关系：
        - edit_file 的 old_text 来自 read_file 的返回结果，这是铁律
        - 如果需要全量重写文件（改动超过 50%），用 write_file 更合适
        - 编辑后建议 read_file 验证修改结果
    """

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        """初始化编辑工具的工作区和访问边界。"""
        self._workspace = workspace  # 工作区根目录
        self._allowed_dir = allowed_dir  # 允许访问的目录

    @property
    def name(self) -> str:
        """返回编辑文件工具名称。"""
        return "edit_file"

    @property
    def description(self) -> str:
        """返回编辑文件工具说明。"""
        return (
            "局部编辑文件，将 old_text 替换为 new_text。"
            "old_text 必须来自 read_file 返回的真实文本；不要凭记忆构造。"
            "出现多处匹配时补充上下文，或明确设置 replace_all=true。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """返回编辑文件工具参数 Schema。"""
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要编辑的文件路径。编辑前先 read_file 确认当前内容。"},
                "old_text": {
                    "type": "string",
                    "description": "要查找并替换的原文片段，必须复制自 read_file 的真实内容。",
                },
                "new_text": {"type": "string", "description": "替换后的新文本，只包含要替换进去的片段。"},
                "replace_all": {
                    "type": "boolean",
                    "description": "是否替换所有出现（默认 false）。不确定时保持 false 并补充 old_text 上下文。",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """查找并替换文件中的指定文本。"""
        path = kwargs.get("path", "")
        old_text = kwargs.get("old_text", "")
        new_text = kwargs.get("new_text", "")
        replace_all = kwargs.get("replace_all", False)

        try:
            # 解析路径并检查是否在允许范围内
            fp = resolve_path(path, self._workspace, self._allowed_dir)
            # 检查文件是否存在
            if not fp.exists():
                return format_tool_error(
                    "文件不存在",
                    attempted=f"编辑文件 {path}",
                    observed=path_failure_hint(path, fp, expected="文件", workspace=self._workspace),
                    do_not_repeat=f"不要继续编辑不存在的路径：{path}",
                    next_action=f"先调用 list_dir 查看父目录：{fp.parent}",
                )

            # 以二进制读取，返回字节串（bytes），检测换行符类型（CRLF 还是 LF）
            async with aiofiles.open(fp, mode="rb") as f:
                raw = await f.read()
            uses_crlf = b"\r\n" in raw  # Windows 换行符
            # 统一转为 LF 处理
            content = raw.decode("utf-8").replace("\r\n", "\n")

            # 查找要替换的旧文本（也统一转为 LF）
            match, count = _find_match(content, old_text.replace("\r\n", "\n"))

            # 未找到匹配文本
            if match is None:
                return self._not_found_msg(old_text, content, path)

            # 多次出现但没开启全部替换，提示用户补充上下文
            if count > 1 and not replace_all:
                return f"警告：old_text 在文件中出现了 {count} 次。请补充更多上下文或传入 replace_all=true。"

            # 规范化新文本的换行符
            norm_new = new_text.replace("\r\n", "\n")
            # 执行替换：replace_all 替换所有，否则只替换第一次
            new_content = content.replace(match, norm_new) if replace_all else content.replace(match, norm_new, 1)

            # 如果原文件是 CRLF 换行，则恢复回去
            if uses_crlf:
                new_content = new_content.replace("\n", "\r\n")

            # 写回文件
            fp.write_bytes(new_content.encode("utf-8"))
            return f"已成功编辑文件：{fp}"

        except PermissionError as e:
            return format_tool_error(
                str(e),
                attempted=f"编辑文件 {path}",
                do_not_repeat="不要重复编辑同一路径",
                next_action="改用工作区内允许访问的路径",
            )
        except Exception as e:
            return format_tool_error(
                f"编辑文件失败：{e}",
                attempted=f"编辑文件 {path}",
                do_not_repeat="不要用相同参数重复编辑",
                next_action="先 read_file 确认当前内容，再构造更准确的 old_text",
            )

    @staticmethod
    def _not_found_msg(old_text: str, content: str, path: str) -> str:
        """生成未找到匹配文本时的详细错误消息（含最接近片段的 diff）"""
        lines = content.splitlines(keepends=True)  # 保留换行符
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)  # 滑动窗口大小

        best_ratio, best_start = 0.0, 0  # 最佳相似度和起始行
        # 滑动窗口遍历，找到与 old_text 最相似的片段
        for i in range(max(1, len(lines) - window + 1)):
            # 使用 difflib 计算文本相似度
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        # 相似度超过 50% 则展示 diff 差异
        if best_ratio > 0.5:
            diff = "\n".join(
                difflib.unified_diff(
                    old_lines,
                    lines[best_start : best_start + window],
                    fromfile="old_text（输入内容）",
                    tofile=f"{path}（文件实际内容，第 {best_start + 1} 行起）",
                    lineterm="",
                )
            )
            return format_tool_error(
                "找不到 old_text",
                attempted=f"在 {path} 中替换指定文本",
                observed=f"最接近的片段位于第 {best_start + 1} 行起（相似度 {best_ratio:.0%}）：\n{diff}",
                do_not_repeat="不要用相同 old_text 再次调用 edit_file",
                next_action="先 read_file 查看目标行附近内容，再用文件中的精确文本重试",
            )
        return format_tool_error(
            "找不到 old_text",
            attempted=f"在 {path} 中替换指定文本",
            observed="没有发现足够接近的片段",
            do_not_repeat="不要用相同 old_text 再次调用 edit_file",
            next_action="先 read_file 或搜索目标符号，确认当前文件内容后再编辑",
        )


class ListDirTool(Tool):
    """列出指定目录下的文件和子目录，帮助了解项目结构。

    核心用途：
        查看某个目录下有哪些文件和文件夹，相当于在文件管理器中打开一个目录。
        当你完全不了解项目结构时，这是第一个应该使用的工具。

    典型使用场景：
        - 初次接触项目时，用 list_dir 查看根目录，了解整体结构
        - 不确定某个文件在哪个子目录时，逐层 list_dir 缩小范围
        - 确认某个目录下是否有目标文件，再用 read_file 读取

    与其他工具的协作关系：
        - list_dir 负责"看有什么"，read_file 负责"看内容"，grep_search 负责"按内容找"
        - 通常的探索流程：list_dir 了解结构 → 缩小范围 → read_file / grep_search 定位具体内容
        - 如果知道文件名模式（如 *.py），直接用 glob_search 更高效
    """

    _DEFAULT_MAX = 200  # 默认最多返回条目数
    # 需要忽略的噪声目录（版本控制、缓存、虚拟环境等）
    _IGNORE_DIRS = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".coverage",
        "htmlcov",
    }

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        """初始化列目录工具的工作区和访问边界。"""
        self._workspace = workspace  # 工作区根目录
        self._allowed_dir = allowed_dir  # 允许访问的目录

    @property
    def name(self) -> str:
        """返回列目录工具名称。"""
        return "list_dir"

    @property
    def description(self) -> str:
        """返回列目录工具说明。"""
        return (
            "列出目录内容，用于了解项目结构或确认路径是否存在。"
            "设置 recursive=true 可递归显示；常见缓存和依赖目录会被自动忽略。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """返回列目录工具参数 Schema。"""
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要列出的目录路径。路径不存在时先列父目录定位。"},
                "recursive": {
                    "type": "boolean",
                    "description": "是否递归列出（默认 false）。项目很大时优先 false，再逐层缩小范围。",
                },
                "max_entries": {
                    "type": "integer",
                    "description": "最多返回的条目数（默认 200）。结果截断时缩小目录或提高上限。",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """列出目录内容并按上限截断返回。"""
        path = kwargs.get("path", "")
        recursive = kwargs.get("recursive", False)
        max_entries = kwargs.get("max_entries", None)

        try:
            # 解析路径并检查是否在允许范围内
            dp = resolve_path(path, self._workspace, self._allowed_dir)
            # 检查目录是否存在
            if not dp.exists():
                return format_tool_error(
                    "目录不存在",
                    attempted=f"列出目录 {path}",
                    observed=path_failure_hint(path, dp, expected="目录", workspace=self._workspace),
                    do_not_repeat=f"不要继续用相同路径调用 list_dir：{path}",
                    next_action=f"先列出存在的父目录：{dp.parent}",
                )
            # 检查是否为目录
            if not dp.is_dir():
                next_action = f"如果要读取文件，请调用 read_file：{path}" if dp.is_file() else "请确认目标路径类型"
                return format_tool_error(
                    "目标不是目录",
                    attempted=f"列出目录 {path}",
                    observed=path_failure_hint(path, dp, expected="目录", workspace=self._workspace),
                    do_not_repeat=f"不要继续用 list_dir 读取该路径：{path}",
                    next_action=next_action,
                )

            # 确定返回条目上限
            cap = max_entries or self._DEFAULT_MAX
            items: list[str] = []  # 收集结果条目
            total = 0  # 总条目计数

            if recursive:
                # 递归遍历所有子文件/目录
                for item in sorted(dp.rglob("*")):
                    # 跳过忽略目录
                    if any(p in self._IGNORE_DIRS for p in item.parts):
                        continue
                    total += 1
                    # 未达上限才加入结果
                    if len(items) < cap:
                        rel = item.relative_to(dp)
                        # 目录加 / 后缀，文件直接用名称
                        items.append(f"{rel}/" if item.is_dir() else str(rel))
            else:
                # 只列出顶层目录
                for item in sorted(dp.iterdir()):
                    # 跳过忽略目录
                    if item.name in self._IGNORE_DIRS:
                        continue
                    total += 1
                    # 未达上限才加入结果
                    if len(items) < cap:
                        pfx = "[DIR] " if item.is_dir() else "[FILE] "
                        items.append(f"{pfx}{item.name}")

            # 空目录处理
            if not items and total == 0:
                return f"目录为空：{path}"

            result = "\n".join(items)
            # 如果实际条目超过上限，提示截断信息
            if total > cap:
                result += f"\n\n（结果已截断，当前显示前 {cap} 项，共 {total} 项）"
            return result

        except PermissionError as e:
            return format_tool_error(
                str(e),
                attempted=f"列出目录 {path}",
                do_not_repeat="不要重复访问同一路径",
                next_action="改用工作区内允许访问的目录",
            )
        except Exception as e:
            return format_tool_error(
                f"列出目录失败：{e}",
                attempted=f"列出目录 {path}",
                do_not_repeat="不要用相同参数重复列目录",
                next_action="检查路径是否存在、是否为目录，再决定下一步",
            )
