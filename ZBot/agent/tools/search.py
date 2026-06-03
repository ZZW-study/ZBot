import json
import subprocess
from pathlib import Path
from typing import Any

from ZBot.agent.tools.base import Tool, format_tool_error


class glob_search(Tool):
    """按文件名模式搜索文件，返回匹配的文件路径列表。只看文件名，不看文件内容。

    核心用途：
        根据文件名关键词或扩展名，在目录树中查找匹配的文件。
        它只搜索文件路径和文件名，不会打开文件读取内容。
        适合回答"项目里有哪些 Python 文件"、"哪个文件名带 auth"这类问题。

    典型使用场景：
        - 查找特定类型的文件：如所有 .py、.md、.ts 文件
        - 按文件名关键词定位：如找文件名中包含 auth、login、config 的文件
        - 组合条件搜索：同时指定文件名关键词 + 扩展名，如"找所有包含 test 的 .py 文件"
        - 在子目录中搜索：指定 search_path 缩小搜索范围

    与其他工具的协作关系：
        - glob_search 按文件名找，grep_search 按文件内容找，两者是独立维度
        - glob_search 返回文件路径后，通常需要 read_file 读取具体内容
        - 如果你知道要找的内容在文件里（如函数名、变量），直接用 grep_search 更精准
        - grep_search 本身也支持 glob 参数来过滤文件类型，不一定要先 glob 再 grep
    """

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self.workspace = workspace
        self.allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "glob_search"

    @property
    def description(self) -> str:
        return "按文件名搜索文件，可以指定文件名关键词和扩展名，返回匹配的文件路径列表。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name_contains": {
                    "type": "string",
                    "description": "文件名中包含的关键词，例如 auth、login、config，不需要通配符。",
                },
                "extension": {
                    "type": "string",
                    "description": "文件扩展名，例如 .py、.md、.ts，不需要通配符。留空则匹配所有类型。",
                },
                "search_path": {
                    "type": "string",
                    "description": "搜索的根目录路径，留空则搜索整个工作区。",
                },
            },
            "anyOf": [
                {"required": ["name_contains"]},
                {"required": ["extension"]},
            ],
        }

    async def execute(self, **kwargs: Any) -> str:
        """执行 glob 搜索，返回匹配的文件路径列表,转化为字符串。"""
        from ZBot.services.formatting import resolve_path

        name_contains = kwargs.get("name_contains", "")
        extension = kwargs.get("extension", "")
        search_path = kwargs.get("search_path", "")

        if search_path:
            allowed_search_path: Path = resolve_path(search_path, self.workspace, self.allowed_dir)
        else:
            allowed_search_path: Path = Path(self.workspace) if self.workspace else Path(".")

        normalized_extension = extension[1:] if extension.startswith(".") else extension

        if name_contains and normalized_extension:
            # 如果说，有文件名的关键词和扩展名，则直接搜索符合条件的文件路径列表
            result: list[Path] = list(allowed_search_path.rglob(f"*{name_contains}*.{normalized_extension}"))
            if not result:
                return (
                    f"没有找到符合条件的文件：文件名包含 '{name_contains}'，"
                    f"扩展名为 '{normalized_extension}'，搜索路径为 '{allowed_search_path}'。"
                )
            else:
                return "\n".join(str(p) for p in result)
        elif name_contains:
            # 只需要找文件名包含关键词的文件
            result: list[Path] = list(allowed_search_path.rglob(f"*{name_contains}*"))
            if not result:
                return f"没有找到文件名包含 '{name_contains}' 的文件，搜索路径为 '{allowed_search_path}'。"
            else:
                return "\n".join(str(p) for p in result)
        elif normalized_extension:
            # 只需要找特定扩展名的文件
            result: list[Path] = list(allowed_search_path.rglob(f"*.{normalized_extension}"))
            if not result:
                return f"没有找到扩展名为 '{normalized_extension}' 的文件，搜索路径为 '{allowed_search_path}'。"
            else:
                return "\n".join(str(p) for p in result)
        else:
            """大模型俩个参数都没有，则报错"""
            return format_tool_error(
                "glob_search 工具至少需要一个参数：name_contains 或 extension",
                attempted="调用 glob_search 工具，但没有提供任何搜索条件",
                observed="glob_search 需要至少一个参数来执行搜索",
                do_not_repeat="不要再调用 glob_search 时忘记提供搜索条件",
                next_action="请提供 name_contains 或 extension 参数来指定搜索条件",
            )


class grep_search(Tool):
    """按文件内容搜索文件，返回匹配的文件路径和行号。会打开文件逐行扫描内容。

    核心用途：
        在文件内容中查找关键词，告诉你"这个内容在哪个文件的哪一行"。
        比如找 def foo 在哪里定义、找某个变量在哪里被引用、找某段配置在哪里写过。
        底层使用 ripgrep（rg）执行搜索，速度快、支持正则。

    典型使用场景：
        - 按函数/变量名定位：如搜索 "def foo" 找到函数定义在哪个文件第几行
        - 按 import 语句定位：如搜索 "import pandas" 找到哪些文件用了 pandas
        - 按错误信息定位：如搜索某个报错信息，找到抛出异常的位置
        - 按配置项定位：如搜索 "DATABASE_URL" 找到数据库配置在哪里
        - 配合文件类型过滤：只在 .py 文件中搜索，或只在文件名包含 test 的文件中搜索

    与其他工具的协作关系：
        - grep_search 找到位置后，必须先 read_file 读取完整内容，不能直接 edit_file
          因为 grep 只返回匹配的那一行，不知道完整函数有多长，直接改会破坏代码
        - glob_search 按文件名找，grep_search 按内容找，两者互补
        - grep_search 自带 glob 过滤能力（name_contains + extension），不一定需要先调用 glob_search

    与 glob_search 的区别：
        - glob_search：看文件名 → 返回"哪些文件叫这个名字"
        - grep_search：看文件内容 → 返回"哪些文件里写了这个内容，在第几行"
    """

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self.workspace = workspace
        self.allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "grep_search"

    @property
    def description(self) -> str:
        return (
            "按文件内容搜索，返回匹配文件路径、行号和匹配行。"
            "适合定位函数、变量、配置项或报错文本；拿到位置后再用 read_file 读取上下文。"
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content_contains": {
                    "type": "string",
                    "description": "文件内容中包含的关键词，例如函数名、变量名、特定语句等。",
                },
                "name_contains": {
                    "type": "string",
                    "description": "文件名中包含的关键词，例如 auth、login、config，不需要通配符。",
                },
                "extension": {
                    "type": "string",
                    "description": "文件扩展名，例如 .py、.md、.ts，不需要通配符。留空则匹配所有类型。",
                },
                "search_path": {
                    "type": "string",
                    "description": "搜索的根目录路径，留空则搜索整个工作区。",
                },
            },
            "required": ["content_contains"],
        }

    async def execute(self, **kwargs: Any) -> str:
        """执行 grep 搜索，返回匹配的文件路径列表,转化为字符串。"""
        from ZBot.services.formatting import resolve_path

        content_contains = kwargs.get("content_contains", "")
        if not content_contains:
            return format_tool_error(
                "grep_search 工具需要 content_contains 参数来指定搜索关键词",
                attempted="调用 grep_search 工具，但没有提供 content_contains 参数",
                observed="grep_search 需要 content_contains 参数来执行搜索",
                do_not_repeat="不要再调用 grep_search 时忘记提供 content_contains 参数",
                next_action="请提供 content_contains 参数来指定搜索关键词",
            )
        name_contains = kwargs.get("name_contains", "")
        extension = kwargs.get("extension", "")
        search_path = kwargs.get("search_path", "")

        if search_path:
            allowed_search_path: Path = resolve_path(search_path, self.workspace, self.allowed_dir)
        else:
            allowed_search_path: Path = self.workspace if self.workspace else Path(".")

        # 构建 ripgrep 命令
        normalized_extension = extension[1:] if extension.startswith(".") else extension

        if name_contains and normalized_extension:
            # 同时有文件名关键词和扩展名过滤
            glob_pattern: str | None = f"*{name_contains}*.{normalized_extension}"
        elif name_contains:
            # 只有文件名关键词
            glob_pattern: str | None = f"*{name_contains}*"
        elif normalized_extension:
            # 只有扩展名过滤
            glob_pattern: str | None = f"*.{normalized_extension}"
        else:
            glob_pattern: str | None = None

        if glob_pattern:
            cmd: list[str] = [
                "rg",
                "--json",
                "--line-number",
                content_contains,
                str(allowed_search_path),
                "--glob",
                glob_pattern,
            ]
        else:
            cmd: list[str] = ["rg", "--json", "--line-number", content_contains, str(allowed_search_path)]

        # 执行 ripgrep 命令。rg 退出码 1 表示没有匹配，不算执行错误。
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return format_tool_error(
                "未找到 rg 命令，无法执行 grep_search",
                attempted="调用 grep_search 底层 ripgrep",
                observed="系统 PATH 中没有 rg 可执行文件",
                do_not_repeat="不要继续重复调用 grep_search",
                next_action="改用 read_file/list_dir 手动定位，或先安装 ripgrep",
            )

        if result.returncode not in (0, 1):
            return format_tool_error(
                "ripgrep 执行失败",
                attempted=" ".join(cmd),
                observed=(result.stderr or result.stdout or "无输出").strip()[:1000],
                do_not_repeat="不要用相同参数重复调用 grep_search",
                next_action="检查搜索路径和 glob 条件，或缩小搜索范围",
            )

        matches: list[str] = []
        for line in result.stdout.splitlines():
            try:
                per_line: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            if per_line.get("type") != "match":
                continue
            data = per_line.get("data", {})
            path_text = data.get("path", {}).get("text", "")
            line_number = data.get("line_number", "?")
            line_text = data.get("lines", {}).get("text", "").rstrip()
            matches.append(f"{path_text}:{line_number}: {line_text}")

        if not matches:
            return f"没有找到文件内容包含 '{content_contains}' 的文件，搜索路径为 '{allowed_search_path}'。"
        else:
            return "\n".join(matches)
