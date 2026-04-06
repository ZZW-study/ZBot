"""nanobot 的命令行入口。

这个模块负责把"命令行交互体验"和"Agent 运行时能力"接起来，主要处理四类事情：
1. 初始化配置与工作区。
2. 创建大模型提供商与 AgentLoop。
3. 提供单次消息模式和交互式聊天模式。
4. 负责终端输入、历史记录、退出信号等 CLI 细节。
"""

from __future__ import annotations

import asyncio
import os
import select
import signal
import sys
from typing import Optional

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from nanobot import __logo__, __version__
from nanobot.config.paths import get_workspace_path
from nanobot.config.schema import Config
from nanobot.utils.helpers import sync_workspace_templates

# Windows 终端默认编码经常不是 UTF-8，不先修正的话，中文输入输出容易乱码。
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


app = typer.Typer(name="nanobot", help="nanobot -- 你的个人 AI 助手", no_args_is_help=True)
console = Console()

# 同时保留英文和中文退出词，兼顾终端习惯与本地化体验。
EXIT_COMMAND = {"exit", "quit", "/exit", "/quit", ":q", "退出", "再见"}

# PromptSession 负责提供输入历史、编辑能力和更稳定的终端交互。
_PROMPT_SESSION: PromptSession | None = None
# 保存终端原始属性，退出时尽量恢复，避免终端状态残留。
_SAVED_TERM_ATTRS = None


def _flush_pending_tty_input() -> None:
    """清理标准输入里已经残留但还没被消费的内容。

    在模型输出期间，用户可能已经敲了字。如果不清理，这些残留字符会混进下一次 prompt，
    造成"明明没输入，终端却自动带出一串旧字符"的体验问题。
    """
    try:
        fd = sys.stdin.fileno()  # 获得标准输入流的文件描述符，万物皆文件
        if not os.isatty(fd):  # 判断该文件描述符是否对应 真实的终端(TTY)，因为你有可能在qq打字，不对应终端
            return
    except Exception:
        return

    # 在支持 termios（Linux/macOS/Unix） 的系统里，直接清空 TTY 输入缓存。
    try:
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    # 兜底方案：非阻塞读掉当前已缓冲的输入。
    try:
        while True:  # 无限循环，直到清空所有缓冲输入
            ready, _, _ = select.select([fd], [], [], 0)  # IO 监听工具：监听文件 / 终端 / 网络等，判断有没有数据可读、能不能写、是否报错；# 参数：[读列表], [写列表], [异常列表], 超时时间(0=非阻塞)
            if not ready:
                break
            if not os.read(fd, 4096):  # 读取4096字节的输入数据（读取后不使用，直接丢弃）
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """尽量恢复终端原始状态，避免程序退出后终端表现异常。"""
    if _SAVED_TERM_ATTRS is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """初始化交互式输入会话。

    这里会做两件关键事情：
    1. 记住终端原始状态，便于后续恢复。
    2. 为 prompt_toolkit 配置历史记录文件，让上下键能回看旧输入。
    """
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS

    try:
        import termios

        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    from nanobot.config.paths import get_cli_history_path

    history_file = get_cli_history_path()
    history_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        _PROMPT_SESSION = PromptSession(
            history=FileHistory(str(history_file)),
            enable_open_in_editor=False,
            multiline=False,
        )
    except Exception as exc:
        # 某些 Windows 终端（例如 Git Bash）下 prompt_toolkit 可能初始化失败。
        # 此时回退到最基础的 input()，保证 CLI 仍可用。
        # 此分支确保在受限环境或某些终端上仍能使用最基础的输入函数
        if sys.platform == "win32":
            _PROMPT_SESSION = None
        else:
            raise exc


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """统一打印 nanobot 的回复内容。"""
    content = response or ""
    # 当 render_markdown=True 时，优先用 Markdown 渲染以支持富文本输出（代码块/列表等）
    body = Markdown(content) if render_markdown else Text(content)
    console.print()
    console.print(f"[cyan]{__logo__}nanobot[/cyan]")
    console.print(body)
    console.print()


def _is_exit_command(command: str) -> bool:
    """判断用户输入是否属于退出指令。"""
    return command.lower() in EXIT_COMMAND or command in EXIT_COMMAND


def version_callback(value: bool) -> None:
    """处理 `--version/-v` 参数。"""
    if value:
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()


async def _read_interactive_input_async() -> str:
    """异步读取一行用户输入。"""
    if _PROMPT_SESSION is None:
        try:
            return await asyncio.to_thread(input, "你：")
        except EOFError as exc:
            raise KeyboardInterrupt from exc

    try:
        # patch_stdout 可以避免程序其他输出把输入行顶乱。
        with patch_stdout():
            return await _PROMPT_SESSION.prompt_async(HTML("<b fg='ansiblue'>你：</b> "))
    except EOFError as exc:
        raise KeyboardInterrupt from exc


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(None, "--version", "-v", callback=version_callback, is_eager=True)
):
    """CLI 根命令回调。

    Typer 要求所有命令都会先经过这里，因此哪怕函数体为空也要保留，
    否则 `--version` 这类全局参数就没有统一入口。
    """
    return None


@app.command()
def onboard():
    """初始化 nanobot 的配置文件和工作区。"""
    from nanobot.config.loader import get_path_config, load_config, save_config
    from nanobot.config.schema import Config

    config_path = get_path_config()
    if config_path.exists():
        console.print(f"[blue]检测到已有配置文件：{config_path}[/blue]")
        console.print("[bold]y[/bold] = 覆盖现有配置（原配置会被重置）")
        console.print("[bold]N[/bold] = 仅刷新缺失字段，保留现有值")
        if typer.confirm("是否覆盖现有配置？"):
            config = Config()
            save_config(config)
        else:
            config = load_config()
            save_config(config)
            console.print(f"[green]✓[/green] 已刷新配置：{config_path}（原有值已保留）")
    else:
        config = Config()
        save_config(config)
        console.print(f"[green]✓[/green] 已创建配置文件：{config_path}")

    workspace = get_workspace_path(str(config.workspace_path))
    console.print(f"[green]✓[/green] 已准备工作区：{workspace}")

    # 只同步缺失模板，不覆盖用户已经自定义过的文件。
    sync_workspace_templates(workspace=workspace)

    console.print(f"\n{__logo__} nanobot 已准备就绪！")
    console.print("\n建议下一步：")
    console.print(f"  1. 在 [cyan]{config_path}[/cyan] 中填写你的 API 密钥")
    console.print("  2. 如果使用 OpenRouter，可在 https://openrouter.ai/keys 获取密钥")
    console.print('  3. 直接开始对话： [cyan]nanobot agent -m "你好！"[/cyan]')


def _make_provider(config: Config):
    """根据配置创建当前应使用的大模型提供商实例。"""
    model = config.agents.defaults.model
    provider_config, provider_name = config.get_provider(model)

    from nanobot.config.loader import get_path_config
    from nanobot.providers.litellm_provider import LiteLLMProvider

    config_path = get_path_config()
    if not provider_name or provider_config is None:
        console.print(f"[red]错误：无法为模型 {model} 自动匹配提供商。[/red]")
        console.print("[red]请检查 `agents.defaults.provider`，或改用受支持的模型前缀。[/red]")
        raise typer.Exit(1)

    if not provider_config.api_key:
        console.print(f"[red]错误：尚未配置 {provider_name} 的 API 密钥。[/red]")
        console.print(f"[red]请在配置文件中补充密钥：{config_path}[/red]")
        raise typer.Exit(1)

    return LiteLLMProvider(
        api_key=provider_config.api_key,
        api_base=provider_config.api_base,
        default_model=model,
        provider_name=provider_name,
    )

# AgentLoop 包含完整的代理运行时：消息总线、模型提供商、工具调用和记忆管理

@app.command()
def agent(
    # message: 用户通过 -m 参数传入的单次消息，如果提供则只执行一次就退出，不进入交互模式
    message: Optional[str] = typer.Option(None, "--message", "-m", help="发送给智能体的单次消息"),
    # session_id: 会话标识符，格式为 "channel:chat_id"，默认 "cli:direct"，用于区分不同对话
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="会话 ID"),
    # markdown: 是否用 Rich 的 Markdown 渲染器渲染模型回复，默认开启，让代码块、列表等更美观
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="是否按 Markdown 渲染回复"),
    # logs: 是否开启 nanobot 内部的调试日志，默认关闭，开启后可以看到更详细的运行信息
    logs: bool = typer.Option(False, "--logs/--no-logs", help="是否显示调试日志"),
):
    """启动与 nanobot 的对话。

    支持两种模式：
    1. 单次模式：nanobot agent -m "你好" -> 执行一次对话后退出
    2. 交互模式：nanobot agent -> 进入持续对话，直到用户输入 exit 或按 Ctrl+C
    """
    # ============ 导入依赖模块 ============
    from loguru import logger  # 日志库，用于控制调试输出

    from nanobot.agent.loop import AgentLoop  # Agent 主循环，核心运行时
    from nanobot.bus.queue import MessageBus  # 消息总线，入站/出站消息队列
    from nanobot.config.loader import load_config  # 配置加载器
    from nanobot.config.paths import get_cron_dir  # 获取定时任务存储目录
    from nanobot.cron.service import CronService  # 定时任务服务

    # ============ 初始化配置与提供商 ============
    config = load_config()  # 从配置文件加载所有配置（API密钥、模型、工具设置等）
    provider = _make_provider(config)  # 根据配置创建 LLM 提供商实例（LiteLLMProvider）
    bus = MessageBus()  # 创建消息总线，用于入站/出站消息的异步传递

    # ============ 初始化定时任务服务 ============
    # CLI 模式也需要初始化定时任务服务，这样 cron 工具才能正常可用。
    cron_store_path = get_cron_dir() / "jobs.json"  # 定时任务持久化存储路径
    cron = CronService(cron_store_path)  # 创建定时任务服务实例

    # ============ 配置日志输出 ============
    if logs:
        logger.enable("nanobot")  # 开启调试日志，会打印详细的内部运行信息
    else:
        logger.disable("nanobot")  # 关闭调试日志，只显示用户可见的输出

    # ============ 创建 AgentLoop 实例 ============
    # AgentLoop 是 Agent 的核心运行时，包含消息处理、工具调用、记忆管理等所有逻辑
    agent_loop = AgentLoop(
        bus=bus,  # 消息总线，用于接收用户消息和发送回复
        provider=provider,  # LLM 提供商，负责调用大模型 API
        workspace=config.workspace_path,  # 工作目录，文件工具在此目录下操作
        model=config.agents.defaults.model,  # 默认使用的模型名称
        temperature=config.agents.defaults.temperature,  # 模型采样温度，控制回答随机性
        max_tokens=config.agents.defaults.max_tokens,  # 模型返回的最大 token 数
        max_iterations=config.agents.defaults.max_tool_iterations,  # 单轮最大工具调用次数，防止无限循环
        memory_window=config.agents.defaults.memory_window,  # 会话历史窗口大小
        reasoning_effort=config.agents.defaults.reasoning_effort,  # 推理强度参数（部分模型支持）
        web_search_config=config.tools.web.search,  # 网络搜索工具配置
        web_proxy=config.tools.web.proxy or None,  # 网络代理设置
        exec_config=config.tools.exec,  # Shell 命令执行工具配置
        cron_service=cron,  # 定时任务服务实例
        restrict_to_workspace=config.tools.restrict_to_workspace,  # 是否限制文件工具只能在工作目录操作
        mcp_servers=config.tools.mcp_servers,  # MCP 服务器配置（扩展工具来源）
    )

    # ============ 定义辅助函数 ============
    def _thinking_ctx():
        """在前台展示"思考中"状态；调试日志开启时则关闭动画。

        返回一个上下文管理器：
        - 调试模式：nullcontext()，什么都不做
        - 正常模式：console.status()，显示旋转动画和"思考中"提示
        """
        if logs:
            from contextlib import nullcontext  # 空上下文管理器，不做任何事
            return nullcontext()
        # console.status 会显示一个旋转动画 + 提示文字，让用户知道程序在运行
        return console.status("[dim]nanobot 正在思考...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        """把模型中间进度打印到终端。

        当模型在执行工具调用时，会通过这个回调打印进度信息，
        让用户知道 Agent 正在做什么。

        Args:
            content: 进度内容（如工具调用提示）
            tool_hint: 是否是工具调用提示，用于区分不同前缀
        """
        prefix = "正在调用工具：" if tool_hint else "进度："  # 根据类型选择前缀
        console.print(f"[dim]↳ {prefix}{content}[/dim]")  # 用灰色字体打印，不干扰主要输出

    # ============ 单次消息模式 ============
    # 如果用户通过 -m 参数提供了消息，执行一次对话后直接退出
    if message:
        async def run_once() -> None:
            """单次消息模式的异步入口。"""
            with _thinking_ctx():  # 显示"思考中"动画
                # process_direct 是 AgentLoop 的直接调用入口，不经过消息队列
                # 适合 CLI/脚本一次性调用，返回模型的最终回复文本
                response = await agent_loop.process_direct(
                    message,  # 用户消息
                    session_id,  # 会话 ID
                    on_progress=_cli_progress  # 进度回调，打印中间状态
                )
            # 打印模型的回复，根据 markdown 参数决定是否渲染
            _print_agent_response(response, render_markdown=markdown)
            # 关闭 MCP 连接，释放资源
            await agent_loop.close_mcp()

        # asyncio.run 是同步入口，会创建事件循环并运行异步函数
        asyncio.run(run_once())
        return  # 单次模式执行完毕，直接返回，不进入交互模式

    # ============ 交互模式初始化 ============
    from nanobot.bus.events import InboundMessage  # 入站消息类型

    _init_prompt_session()  # 初始化交互式输入会话（历史记录、终端状态保存等）
    # 打印欢迎信息，告诉用户如何退出
    console.print(f"{__logo__} 已进入交互模式（输入 [bold]exit[/bold] / [bold]退出[/bold]，或按 [bold]Ctrl+C[/bold] 结束）\n")

    # 解析 session_id，格式为 "channel:chat_id"
    if ":" in session_id:
        cli_channel, cli_chat_id = session_id.split(":", 1)  # 按第一个冒号分割
    else:
        cli_channel, cli_chat_id = "cli", session_id  # 如果没有冒号，默认 channel 为 "cli"

    # ============ 注册信号处理函数 ============
    def _handle_signal(signum, _frame):
        """收到系统退出信号时，优雅恢复终端并退出。

        处理 SIGINT (Ctrl+C)、SIGTERM (kill) 等信号，
        确保终端状态被正确恢复，避免退出后终端显示异常。
        """
        sig_name = signal.Signals(signum).name  # 获取信号名称（如 SIGINT）
        _restore_terminal()  # 恢复终端原始状态
        console.print(f"\n收到信号 {sig_name}，程序退出。")
        sys.exit(0)  # 退出程序

    # 注册各种退出信号的处理函数
    signal.signal(signal.SIGINT, _handle_signal)       # Ctrl+C 触发的信号
    signal.signal(signal.SIGTERM, _handle_signal)      # kill 命令触发的信号
    if hasattr(signal, "SIGHUP"):                      # 终端关闭时触发（仅 Unix）
        signal.signal(signal.SIGHUP, _handle_signal)
    if hasattr(signal, "SIGPIPE"):                     # 管道破裂时触发（仅 Unix）
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)  # 忽略，避免程序崩溃

    # ============ 交互式主循环 ============
    async def run_interactive() -> None:
        """交互式聊天主循环。

        结构分成两条并发链路：
        1. `agent_loop.run()` 持续消费入站消息（后台任务）
        2. `_consume_outbound()` 持续把回复和进度从消息总线取出来（后台任务）

        主协程负责：读取用户输入 → 发布到入站队列 → 等待回复 → 打印结果
        """
        # ---------- 启动后台任务 ----------
        # bus_task: AgentLoop 的主循环，持续从入站队列消费消息并处理
        bus_task = asyncio.create_task(agent_loop.run())
        # turn_done: 事件对象，用于同步主协程和出站消费者
        # 当收到模型回复时，出站消费者会 set() 这个事件，通知主协程
        turn_done = asyncio.Event()
        turn_done.set()  # 初始状态为已设置，表示当前没有在等待回复
        # turn_response: 存储当前回合收到的回复内容
        turn_response: list[str] = []

        async def _consume_outbound() -> None:
            """后台消费 nanobot 输出。

            持续从出站队列取消息，根据消息类型做不同处理：
            1. 进度消息：直接打印（灰色）
            2. 当前回合的回复：保存并通知主协程
            3. 其他消息：直接打印
            """
            while True:
                try:
                    # 从出站队列取消息，最多等待 1 秒
                    msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                    # 区分三类输出：进度、当前回合的最终回复、以及其他（直接打印）
                    if msg.metadata.get("_progress"):
                        # 进度消息：模型或工具在执行时的中间状态
                        console.print(f"  [dim]↳ {msg.content}[/dim]")
                    elif not turn_done.is_set():
                        # 主协程正在等待当前回合的回复，把第一条回复保存并通知
                        if msg.content:
                            turn_response.append(msg.content)  # 保存回复内容
                        turn_done.set()  # 通知主协程：回复已收到
                    elif msg.content:
                        # 其他异步到达的消息（例如工具完成后的额外输出）直接打印
                        console.print()
                        _print_agent_response(msg.content, render_markdown=markdown)
                except asyncio.TimeoutError:
                    # 超时是正常的，继续循环检查
                    continue
                except asyncio.CancelledError:
                    # 任务被取消（程序退出时），跳出循环
                    break

        # outbound_task: 出站消息消费者，持续从队列取回复并打印
        outbound_task = asyncio.create_task(_consume_outbound())

        # ---------- 主交互循环 ----------
        try:
            while True:  # 无限循环，直到用户退出
                try:
                    # 清理终端输入缓冲区，避免之前的误输入影响本次输入
                    _flush_pending_tty_input()
                    # 异步读取用户输入，显示 "你：" 提示符
                    user_input = await _read_interactive_input_async()
                    command = user_input.strip()  # 去除首尾空白

                    if not command:
                        continue  # 空输入，跳过，继续等待
                    if _is_exit_command(command):
                        # 用户输入了退出命令，恢复终端并退出
                        _restore_terminal()
                        console.print("\n再见！")
                        break

                    # ---------- 发送消息并等待回复 ----------
                    turn_done.clear()  # 清除事件，表示开始等待回复
                    turn_response.clear()  # 清空之前的回复

                    # 将用户消息发布到入站队列
                    # AgentLoop.run() 会从队列取出这条消息并处理
                    await bus.publish_inbound(
                        InboundMessage(
                            channel=cli_channel,  # 渠道标识（如 "cli"）
                            sender_id="user",  # 发送者 ID
                            chat_id=cli_chat_id,  # 聊天 ID
                            content=user_input,  # 用户输入的内容
                        )
                    )

                    # 发布入站消息后，AgentLoop 会异步处理并通过消息总线回传结果。
                    # 主协程在 turn_done 事件上等待，直到代理端写回回复或超时。
                    with _thinking_ctx():  # 显示"思考中"动画
                        await turn_done.wait()  # 阻塞等待，直到出站消费者 set() 这个事件

                    # 如果收到了回复，打印出来
                    if turn_response:
                        _print_agent_response(turn_response[0], render_markdown=markdown)

                except KeyboardInterrupt:
                    # 用户按了 Ctrl+C，退出程序
                    _restore_terminal()
                    console.print("\n再见！")
                    break
                except EOFError:
                    # 输入流结束（如管道输入结束），退出程序
                    _restore_terminal()
                    console.print("\n再见！")
                    break
        finally:
            # ---------- 清理资源 ----------
            # finally 块确保无论正常退出还是异常退出，都会执行清理
            agent_loop.stop()  # 通知 AgentLoop 停止主循环
            outbound_task.cancel()  # 取消出站消费者任务
            # 等待两个后台任务结束，return_exceptions=True 表示不抛出异常
            await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
            await agent_loop.close_mcp()  # 关闭 MCP 连接

    # 运行交互式主循环
    asyncio.run(run_interactive())


@app.command()
def status():
    """查看当前配置、工作区和模型提供商状态。"""
    from nanobot.config.loader import get_path_config, load_config

    config_path = get_path_config()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot 状态\n")
    console.print(f"配置文件：{config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"工作区：{workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from nanobot.providers.registry import PROVIDERS

        console.print(f"当前模型：{config.agents.defaults.model}")

        for spec in PROVIDERS:
            provider = getattr(config.providers, spec.name, None)
            if provider is None:
                continue
            if spec.is_gateway:
                if provider.api_base:
                    console.print(f"{spec.display_name}： [green]✓ {provider.api_base}[/green]")
                else:
                    console.print(f"{spec.display_name}： [dim]未设置[/dim]")
            else:
                has_key = bool(provider.api_key)
                console.print(f"{spec.display_name}： {'[green]✓[/green]' if has_key else '[dim]未设置[/dim]'}")


if __name__ == "__main__":
    app()
