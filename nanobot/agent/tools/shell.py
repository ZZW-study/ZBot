import asyncio  # 异步I/O库，用于非阻塞执行shell命令
import os       # 操作系统接口，处理路径、环境变量等
import re       # 正则表达式，用于命令安全过滤
from pathlib import Path  # 路径操作，安全路径解析
from typing import Any  # 类型提示，增强代码可读性
from nanobot.agent.tools.base import Tool  # 基础工具类，继承自父类

class ExecTool(Tool):
    """Tool to execute shell commands with strict safety guards."""
    
    def __init__(
        self,
        timeout: int = 60,  # 默认超时时间（秒）
        working_dir: str | None = None,  # 默认工作目录（None表示当前目录）
        deny_patterns: list[str] | None = None,  # 拒绝的危险命令正则模式列表
        allow_patterns: list[str] | None = None,  # 允许的命令白名单正则模式
        restrict_to_workspace: bool = False,  # 是否限制在工作区路径内
        path_append: str = "",  # 额外追加到PATH环境变量的路径
    ):
        self.timeout = timeout  # 有效超时时间（用户指定或默认）
        self.working_dir = working_dir  # 工作目录（优先级：用户 > 初始化 > 当前目录）
        self.deny_patterns = deny_patterns or [  # 默认危险命令模式（严格过滤）
            r"\brm\s+-[rf]{1,2}\b",          # 匹配 rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # 匹配 del /f, del /q（Windows）
            r"\brmdir\s+/s\b",               # 匹配 rmdir /s（Windows）
            r"(?:^|[;&|]\s*)format\b",       # 匹配 format（独立命令）
            r"\b(mkfs|diskpart)\b",          # 匹配磁盘操作工具
            r"\bdd\s+if=",                   # 匹配 dd if=（写入磁盘）
            r">\s*/dev/sd",                  # 匹配重定向到磁盘设备（/dev/sd*）
            r"\b(shutdown|reboot|poweroff)\b",  # 匹配系统关机命令
            r":\(\)\s*\{.*\};\s*:",          # 匹配 fork bomb（Bash恶意代码）
        ]
        self.allow_patterns = allow_patterns or []  # 允许的命令白名单
        self.restrict_to_workspace = restrict_to_workspace  # 路径限制开关
        self.path_append = path_append  # 额外PATH路径（如：/usr/local/bin）

    @property
    def name(self) -> str:
        return "exec"  # 工具名称（用于调用时标识）
    
    _MAX_TIMEOUT = 600  # 最大允许超时（600秒=10分钟）
    _MAX_OUTPUT = 10_000  # 最大输出长度（避免大输出阻塞）
    
    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."  # 工具描述
    
    @property
    def parameters(self) -> dict[str, Any]:
        """返回工具参数的JSON Schema描述（用于API调用）"""
        return {
            "type": "object",
            "properties": {
                "command": {  # 必填参数：要执行的shell命令
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "working_dir": {  # 可选参数：覆盖工作目录
                    "type": "string",
                    "description": "Optional working directory for the command",
                },
                "timeout": {  # 可选参数：覆盖超时时间（1-600秒）
                    "type": "integer",
                    "description": (
                        "Timeout in seconds. Increase for long-running commands "
                        "like compilation or installation (default 60, max 600)."
                    ),
                    "minimum": 1,
                    "maximum": 600,
                },
            },
            "required": ["command"],  # 必填字段
        }


    async def execute(
        self, command: str, working_dir: str | None = None,
        timeout: int | None = None, **kwargs: Any,
    ) -> str:
        """执行shell命令并返回安全过滤后的输出（异步）"""
        # 1. 确定工作目录（优先级：用户参数 > 初始化参数 > 当前目录）
        cwd = working_dir or self.working_dir or os.getcwd()
        
        # 2. 安全检查：命令是否被禁止或不在白名单
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error  # 直接返回错误（不执行命令）
        
        # 3. 确定有效超时时间（取用户指定/默认值与最大值的最小值）
        effective_timeout = min(timeout or self.timeout, self._MAX_TIMEOUT)
        
        # 4. 准备环境变量（追加PATH路径）
        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append
        
        try:
            # 5. 创建异步子进程执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,  # 重定向标准输出
                stderr=asyncio.subprocess.PIPE,  # 重定向标准错误
                cwd=cwd,  # 工作目录
                env=env,  # 环境变量
            )
            
            # 6. 等待命令完成（带超时）
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),  # 等待所有输出
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                # 超时处理：强制终止进程
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)  # 等待进程退出
                except asyncio.TimeoutError:
                    pass
                return f"Error: Command timed out after {effective_timeout} seconds"
            
            # 7. 组装输出结果
            output_parts = []
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))  # 解码输出
            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():  # 非空错误输出
                    output_parts.append(f"STDERR:\n{stderr_text}")
            output_parts.append(f"\nExit code: {process.returncode}")  # 添加退出码
            
            # 8. 输出截断（防止过长输出）
            result = "\n".join(output_parts) if output_parts else "(no output)"
            if len(result) > self._MAX_OUTPUT:
                half = self._MAX_OUTPUT // 2
                result = (
                    result[:half] +  # 前半部分
                    f"\n\n... ({len(result) - self._MAX_OUTPUT:,} chars truncated) ...\n\n" +  # 截断提示
                    result[-half:]  # 后半部分
                )
            
            return result  # 返回安全过滤后的结果
        
        except Exception as e:
            return f"Error executing command: {str(e)}"  # 其他异常处理


    def _guard_command(self, command: str, cwd: str) -> str | None:
        """安全检查：阻止危险命令/路径越界（返回错误字符串或None）"""
        cmd = command.strip()
        lower = cmd.lower()  # 转小写统一匹配
        
        # 1. 检查是否匹配危险模式（deny_patterns）
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"
        
        # 2. 检查是否在允许的白名单中（allow_patterns）
        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"
        
        # 3. 路径限制检查（如果启用了restrict_to_workspace）
        if self.restrict_to_workspace:
            # 检查路径遍历（.. 或 ../）
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"
            
            # 解析工作目录绝对路径
            cwd_path = Path(cwd).resolve()
            
            # 提取命令中的所有绝对路径（Windows/POSIX）
            for raw in self._extract_absolute_paths(cmd):
                try:
                    # 展开环境变量和用户家目录（如~）
                    expanded = os.path.expandvars(raw.strip())
                    p = Path(expanded).expanduser().resolve()
                except Exception:
                    continue  # 跳过解析失败的路径
                
                # 检查路径是否在工作目录外
                if p.is_absolute() and (cwd_path not in p.parents and p != cwd_path):
                    return "Error: Command blocked by safety guard (path outside working dir)"
        
        return None  # 通过所有安全检查
    
    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        """从命令中提取所有绝对路径（支持Windows/POSIX）"""
        # Windows: C:\... 或 D:\...
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]+", command)
        # POSIX: /absolute/path
        posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command)
        # POSIX/Windows: ~path（家目录展开）
        home_paths = re.findall(r"(?:^|[\s|>'\"])(~[^\s\"'>;|<]*)", command)
        return win_paths + posix_paths + home_paths