"""
ZBot 一键启动脚本
"""

from __future__ import annotations

import argparse  # 解析命令行参数库，让脚本在终端运行时，通过命令行传入参数（如文件路径、开关、数值），替代硬编码变量。
import shutil    # 文件、文件夹的批量操作，比如复制、移动、删除、打包、权限操作，
import signal    # 捕获、处理操作系统发送的信号（如终止、中断、超时等系统指令），常用于服务端、后台程序、守护进程。
import subprocess  # 在 Python 代码里调用、执行系统命令 / 外部程序。
import sys
import time        # time.sleep() 让主线程每秒暂停一次，避免空转浪费 CPU
from pathlib import Path

# ── 项目路径 ──────────────────────────────────────────────
# start.py 所在目录即项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "ZBot" / "frontend"

# ── 颜色（ANSI escape codes）──────────────────────────────
# 让终端打印颜色
# \033 是 ESC 字符（八进制33 = 十进制27），终端看到它后，不会把后面的内容当普通字符打印，而是当作控制指令解析。
# \033  [  31  m
#  ↑    ↑   ↑  ↑
# ESC  [  颜色码  结束符，转义序列 \033[31m → 到 m 就结束了，但它的作用是设置终端的当前颜色状态，这个状态会一直保持，直到被新的指令覆盖
# 终端识别这个序列后，也就是打印的时候，就把后续文字渲染成对应颜色。
BLUE = "\033[34m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"  # 状态重置，后续恢复默认


def _resolve_cmd(name: str) -> str:
    """
    把 'npm' 解析为实际可执行路径。

    Windows 下 npm/vite 等是 .cmd 批处理文件，
    subprocess 无法直接找到 'npm'，需要用 shutil.which 定位 'npm.cmd'。
    """
    # 查找可执行程序的完整路径，模拟系统 which 命令，name是要查找的程序名,返回类似 C:\Users\xxx\.cargo\bin\uv.exe
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
    # 
    print(f"{BLUE}[后端] 启动 uvicorn (ZBot.backend.app:app :{port}{mode}) ...{RESET}")
    # 要执行的终端命令
    command = [
        _resolve_cmd("uv"), "run", "uvicorn",
        "ZBot.backend.app:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ]
    if reload:
        command.append("--reload")
    # 子进程类，创建并运行独立子进程，执行系统命令、外部程序
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,           # 此子进程运行的目录
        stdout=subprocess.PIPE,     # 捕获 stdout,将子进程的标准输出重定向到一个管道，让父进程（ Python 代码）可以读取它。
                                    # 没有它 → 子进程的输出直接打印到终端，Python 无法捕获
                                    # 有了它 → 输出被"截住"，你可以通过 process.stdout.read() 或逐行读取
        stderr=subprocess.STDOUT,   # stderr 合并到 stdout
                                    # 将子进程的标准错误合并到标准输出里，即两个流合成一路。
                                    # 没有它 → 错误信息和正常输出是两条独立的流，需要分别处理
                                    # 有了它 → 错误信息也会出现在 process.stdout 里，一起被捕获
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
        cwd=FRONTEND_DIR,                      # 此子进程运行的目录
        stdout=subprocess.PIPE,                # 截获子进程的 stdout，父进程通过 proc.stdout 读取
        stderr=subprocess.STDOUT,              # stderr 合并到 stdout，错误信息也走同一条流
        text=True,                             # 输出为字符串而非 bytes
    )


def stream_output(proc: subprocess.Popen, prefix: str, color: str) -> None:
    """
    实时打印子进程的输出，每行加颜色前缀。

    这是核心：子进程的 stdout 是逐行输出的，
    我们逐行读取并在前面加上 [后端] 或 [前端] 标记，
    这样两个进程的日志不会混在一起。
    """
    try:
        # 因为 Popen 的 stdout 类型是 IO[str] | None，但我们在创建时指定了
        # stdout=subprocess.PIPE，所以运行时一定是 IO[str]，不会是 None。
        for line in proc.stdout:  # type: ignore[union-attr]
            print(f"{color}{prefix}{RESET} {line}", end="")
    except (ValueError, OSError):
        # 进程退出后 stdout 管道会关闭，此时抛出异常，忽略即可
        pass


def main() -> None:
    # ── 解析命令行参数 ────────────────────────────────────
    parser = argparse.ArgumentParser(description="ZBot 一键启动脚本")
    # 创建一个命令行参数解析器实例，description 是运行 python start.py --help 时显示的描述文字。
    parser.add_argument("--port", type=int, default=8000, help="后端端口 (默认 8000)")
    # 注册一个可选参数 --port：
    # type=int → 自动把输入的字符串转成整数
    # default=8000 → 用户不传时默认值为 8000
    # 用法：python start.py --port 9000
    parser.add_argument("--reload", action="store_true", help="启用后端热重载开发模式")
    # 注册一个开关型参数 --reload：
    # action="store_true" → 不需要传值，出现就是 True，不出现就是 False
    # 用法：python start.py --reload
    args = parser.parse_args()
    # 实际去读取命令行输入，解析后存入 args 对象，之后通过 args.port、args.reload 取值。

    # ── 检查前端目录是否存在 ──────────────────────────────
    # package.json 是前端项目的"身份证"，npm 读取它来知道：
    #   - 装哪些依赖（react、vite 等）
    #   - 怎么启动项目（scripts 里定义了 dev、build 等命令）
    # 没有它 npm install 和 npm run dev 都无法工作。
    #
    # package-lock.json 是 npm 自动生成的"依赖锁定文件"，
    # 记录每个包的精确版本号，保证所有人装到完全一致的依赖。
    # 如果丢失，npm install 会重新解析版本，可能导致不同环境装出不同结果。
    if not (FRONTEND_DIR / "package.json").exists():
        print(f"{RED}[错误] 前端目录不存在: {FRONTEND_DIR}{RESET}", file=sys.stderr)
        sys.exit(1)

    # ── 启动两个子进程 ────────────────────────────────────
    # subprocess.Popen() 在创建实例的同时就启动了子进程。
    # 返回的 Popen 对象是进程的"句柄"，后续用于：
    #   - .stdout      → 读取子进程的输出（由线程实时打印到终端）
    #   - .terminate() → Ctrl+C 时终止子进程
    #   - .wait()      → 等待子进程退出
    #   - .poll()      → 检查子进程是否还在运行
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
        target=stream_output, args=(backend_proc, "[后端]", BLUE), daemon=True # 设置为守护线程：主线程退出时，这些线程自动跟着死，不会卡住程序。
    )
    t_frontend = threading.Thread(
        target=stream_output, args=(frontend_proc, "[前端]", GREEN), daemon=True
    )
    t_backend.start()
    t_frontend.start()

    # ── 注册 Ctrl+C 信号处理 ──────────────────────────────
    # signal.signal() 告诉操作系统：收到 SIGINT 信号时，执行 shutdown 函数。
    # SIGINT = 用户按 Ctrl+C 时系统发送的中断信号。
    # 这样 Ctrl+C 不会直接杀掉主进程，而是先优雅地终止子进程再退出。
    def shutdown(signum, frame):
        # signum: 信号编号（SIGINT=2），frame: 当前栈帧（此处未用）
        print(f"\n{RED}[启动脚本] 正在停止所有服务...{RESET}")
        backend_proc.terminate()   # 向子进程发送 SIGTERM 信号，请求它自行退出
        frontend_proc.terminate()
        backend_proc.wait(timeout=5)   # 等待子进程退出，最多等 5 秒
        frontend_proc.wait(timeout=5)
        print(f"{RED}[启动脚本] 已停止。{RESET}")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    # ── 等待任一进程退出 ──────────────────────────────────
    # 主线程卡在这个循环里，持续监控两个子进程的状态。
    # 任一子进程意外退出时，自动终止另一个并退出整个程序。
    while True:
        # .poll() 返回 None 表示还在运行，返回整数表示已退出（0=正常，非0=异常）
        backend_ret = backend_proc.poll()
        frontend_ret = frontend_proc.poll()

        if backend_ret is not None:
            print(f"{RED}[后端] 进程退出 (code={backend_ret}){RESET}")
            shutdown(None, None)   # signum/frame 此处未用，传 None 即可

        if frontend_ret is not None:
            print(f"{RED}[前端] 进程退出 (code={frontend_ret}){RESET}")
            shutdown(None, None)

        try:
            time.sleep(1)   # 每秒检查一次，避免空转浪费 CPU
        except KeyboardInterrupt:
            # 兜底：如果 signal.SIGINT 处理失败，这里也能捕获 Ctrl+C
            shutdown(None, None)


if __name__ == "__main__":
    main()
