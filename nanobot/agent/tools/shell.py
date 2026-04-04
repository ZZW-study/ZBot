"""Shell 命令执行工具。

这个工具是整个系统里风险最高的一类能力，因此实现重点不在“跑命令”，
而在“先做足够严格的安全限制，再去跑命令”。
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """执行 shell 命令，并在执行前做安全拦截。"""

    _MAX_TIMEOUT = 600
    _MAX_OUTPUT = 10_000

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        # 默认危险命令模式覆盖删除磁盘、关机、fork bomb 等高风险操作。
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",
            r"\bdel\s+/[fq]\b",
            r"\brmdir\s+/s\b",
            r"(?:^|[;&|]\s*)format\b",
            r"\b(mkfs|diskpart)\b",
            r"\bdd\s+if=",
            r">\s*/dev/sd",
            r"\b(shutdown|reboot|poweroff)\b",
            r":\(\)\s*\{.*\};\s*:",
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append
        # path_append: 可选附加的 PATH 字符串，用于把自定义可执行文件目录加入到 env PATH

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "执行 shell 命令并返回结果。使用前请确认命令安全且必要。"

    @property
    def parameters(self) -> dict[str, Any]:
        """返回工具参数的 JSON Schema。"""
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令。",
                },
                "working_dir": {
                    "type": "string",
                    "description": "可选。覆盖默认工作目录。",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间，单位秒。默认 60 秒，最大 600 秒。",
                    "minimum": 1,
                    "maximum": 600,
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
        **kwargs: Any,
    ) -> str:
        """执行 shell 命令并返回标准化后的输出。"""
        # 工作目录优先级：调用参数 > 工具初始化参数 > 当前进程目录。
        cwd = working_dir or self.working_dir or os.getcwd()

        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        effective_timeout = min(timeout or self.timeout, self._MAX_TIMEOUT)

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=effective_timeout)
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return f"错误：命令执行超时（{effective_timeout} 秒）"

            output_parts = []
            if stdout:
                # 解码标准输出，替换不可解码字节以避免抛出
                output_parts.append(stdout.decode("utf-8", errors="replace"))
            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"标准错误输出：\n{stderr_text}")
            output_parts.append(f"\n退出码：{process.returncode}")

            result = "\n".join(output_parts) if output_parts else "（命令没有输出内容）"
            if len(result) > self._MAX_OUTPUT:
                half = self._MAX_OUTPUT // 2
                result = (
                    result[:half]
                    + f"\n\n……（已截断 {len(result) - self._MAX_OUTPUT:,} 个字符）……\n\n"
                    + result[-half:]
                )

            return result
        except Exception as exc:
            return f"错误：执行命令失败：{str(exc)}"

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """执行前的安全检查。

        拦截策略包括三层：
        1. 匹配危险命令黑名单。
        2. 如果设置了白名单，则只允许白名单命令。
        3. 如果启用了工作区限制，则阻止路径越界。
        """
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "错误：命令被安全策略拦截，检测到高风险模式。"

        if self.allow_patterns and not any(re.search(pattern, lower) for pattern in self.allow_patterns):
            return "错误：命令被安全策略拦截，不在允许执行的白名单中。"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "错误：命令被安全策略拦截，检测到路径穿越。"

            cwd_path = Path(cwd).resolve()
            for raw in self._extract_absolute_paths(cmd):
                try:
                    expanded = os.path.expandvars(raw.strip())
                    path = Path(expanded).expanduser().resolve()
                except Exception:
                    continue

                if path.is_absolute() and (cwd_path not in path.parents and path != cwd_path):
                    return "错误：命令被安全策略拦截，访问路径超出了当前工作目录。"

        return None

    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        """从命令字符串中提取绝对路径，供路径越界检查使用。"""
        # 提取 Windows 风格、POSIX 风格以及 ~ 开头的路径，供后续 resolve 和权限检查使用
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]+", command)
        posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command)
        home_paths = re.findall(r"(?:^|[\s|>'\"])(~[^\s\"'>;|<]*)", command)
        return win_paths + posix_paths + home_paths
