"""
ZBot 一键启动脚本

同时启动后端 (FastAPI + uvicorn) 和前端 (Vite dev server)，
Ctrl+C 会同时终止两个进程。
"""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
from pathlib import Path

# ── 项目路径 ──────────────────────────────────────────────
# start.py 所在目录即项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "ZBot" / "frontend"

# ── 颜色（ANSI escape codes）──────────────────────────────
BLUE = "\033[34m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def _resolve_cmd(name: str) -> str:
    """
    把 'npm' 解析为实际可执行路径。

    Windows 下 npm/vite 等是 .cmd 批处理文件，
    subprocess 无法直接找到 'npm'，需要用 shutil.which 定位 'npm.cmd'。
    """
    found = shutil.which(name)
    if found:
        return found
    # 回退：Windows 上尝试 .cmd 后缀
    if sys.platform == "win32":
        found = shutil.which(name + ".cmd")
        if found:
            return found
    # 都找不到就返回原名，让 subprocess 报错（错误信息更清晰）
    return name


def start_backend(port: int, reload: bool = False) -> subprocess.Popen:
    """
    启动后端服务 (uvicorn)。

    uv run 会自动使用项目 .venv 中的 Python 环境。
    --reload: 代码变动时自动重启（开发模式）。
    stdout/stderr 通过 PIPE 捕获，由主进程统一打印并加 [后端] 前缀。
    """
    mode = " --reload" if reload else ""
    print(f"{BLUE}[后端] 启动 uvicorn (ZBot.backend.app:app :{port}{mode}) ...{RESET}")
    command = [
        _resolve_cmd("uv"), "run", "uvicorn",
        "ZBot.backend.app:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ]
    if reload:
        command.append("--reload")
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,          # 工作目录设为项目根
        stdout=subprocess.PIPE,     # 捕获 stdout
        stderr=subprocess.STDOUT,   # stderr 合并到 stdout
        text=True,                  # 输出为字符串而非 bytes
    )


def start_frontend() -> subprocess.Popen:
    """
    启动前端 Vite dev server。

    npm run dev 会启动 Vite，默认端口 5173。
    Vite 配置了 proxy，/api/* 请求会自动转发到后端。
    """
    print(f"{GREEN}[前端] 启动 Vite dev server ...{RESET}")
    return subprocess.Popen(
        [_resolve_cmd("npm"), "run", "dev"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stream_output(proc: subprocess.Popen, prefix: str, color: str) -> None:
    """
    实时打印子进程的输出，每行加颜色前缀。

    这是核心：子进程的 stdout 是逐行输出的，
    我们逐行读取并在前面加上 [后端] 或 [前端] 标记，
    这样两个进程的日志不会混在一起。
    """
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            print(f"{color}{prefix}{RESET} {line}", end="")
    except (ValueError, OSError):
        # 进程退出后 stdout 会关闭，此时忽略即可
        pass


def main() -> None:
    # ── 解析命令行参数 ────────────────────────────────────
    parser = argparse.ArgumentParser(description="ZBot 一键启动脚本")
    parser.add_argument("--port", type=int, default=8000, help="后端端口 (默认 8000)")
    parser.add_argument("--reload", action="store_true", help="启用后端热重载开发模式")
    args = parser.parse_args()

    # ── 检查前端目录是否存在 ──────────────────────────────
    if not (FRONTEND_DIR / "package.json").exists():
        print(f"{RED}[错误] 前端目录不存在: {FRONTEND_DIR}{RESET}", file=sys.stderr)
        sys.exit(1)

    # ── 启动两个子进程 ────────────────────────────────────
    backend_proc = start_backend(args.port, reload=args.reload)
    frontend_proc = start_frontend()

    # ── 打印启动信息 ──────────────────────────────────────
    print()
    print("=" * 60)
    print(f"  {GREEN}ZBot 启动中...{RESET}")
    print(f"  后端:  {BLUE}http://localhost:{args.port}{RESET}  (FastAPI + WebSocket)")
    print(f"  前端:  {GREEN}http://localhost:5173{RESET}  (Vite dev server)")
    print(f"  文档:  {BLUE}http://localhost:{args.port}/docs{RESET}  (Swagger UI)")
    print("=" * 60)
    print(f"  {RED}Ctrl+C 停止所有服务{RESET}")
    print("=" * 60)
    print()

    # ── 用线程并发读取两个进程的输出 ──────────────────────
    # 如果不用线程，读一个进程的输出时会阻塞另一个
    import threading

    t_backend = threading.Thread(
        target=stream_output, args=(backend_proc, "[后端]", BLUE), daemon=True
    )
    t_frontend = threading.Thread(
        target=stream_output, args=(frontend_proc, "[前端]", GREEN), daemon=True
    )
    t_backend.start()
    t_frontend.start()

    # ── 注册 Ctrl+C 信号处理 ──────────────────────────────
    # 收到 SIGINT（Ctrl+C）时，终止两个子进程
    def shutdown(signum, frame):
        print(f"\n{RED}[启动脚本] 正在停止所有服务...{RESET}")
        backend_proc.terminate()   # 发送 SIGTERM
        frontend_proc.terminate()
        backend_proc.wait(timeout=5)
        frontend_proc.wait(timeout=5)
        print(f"{RED}[启动脚本] 已停止。{RESET}")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    # ── 等待任一进程退出 ──────────────────────────────────
    # 主线程阻塞在这里，直到后端或前端任一退出
    while True:
        # 每秒检查一次进程状态（避免忙等）
        backend_ret = backend_proc.poll()
        frontend_ret = frontend_proc.poll()

        if backend_ret is not None:
            print(f"{RED}[后端] 进程退出 (code={backend_ret}){RESET}")
            shutdown(None, None)

        if frontend_ret is not None:
            print(f"{RED}[前端] 进程退出 (code={frontend_ret}){RESET}")
            shutdown(None, None)

        try:
            import time
            time.sleep(1)
        except KeyboardInterrupt:
            shutdown(None, None)


if __name__ == "__main__":
    main()
