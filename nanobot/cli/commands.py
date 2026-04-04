"""nanobot 的命令行入口。

这个模块负责把“命令行交互体验”和“Agent 运行时能力”接起来，主要处理四类事情：
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

# Windows 终端默认编码经常不是 UTF-8，不先修正的话，中文输出容易乱码。
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        os.environ["PYTHONENCODING"] = "utf-8"
    try:
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
    造成“明明没输入，终端却自动带出一串旧字符”的体验问题。
    """
    try:
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return
    except Exception:
        return

    # 在支持 termios 的系统里，直接清空 TTY 输入缓存。
    try:
        import termios

        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    # 兜底方案：非阻塞读掉当前已缓冲的输入。
    try:
        while True:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 4096):
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
    message: Optional[str] = typer.Option(None, "--message", "-m", help="发送给智能体的单次消息"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="会话 ID"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="是否按 Markdown 渲染回复"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="是否显示调试日志"),
):
    """启动与 nanobot 的对话。"""
    from loguru import logger

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import load_config
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService

    config = load_config()
    provider = _make_provider(config)
    bus = MessageBus()

    # CLI 模式也需要初始化定时任务服务，这样 cron 工具才能正常可用。
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    if logs:
        logger.enable("nanobot")
    else:
        logger.disable("nanobot")

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        temperature=config.agents.defaults.temperature,
        max_tokens=config.agents.defaults.max_tokens,
        max_iterations=config.agents.defaults.max_tool_iterations,
        memory_window=config.agents.defaults.memory_window,
        reasoning_effort=config.agents.defaults.reasoning_effort,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
    )

    def _thinking_ctx():
        """在前台展示“思考中”状态；调试日志开启时则关闭动画。"""
        if logs:
            from contextlib import nullcontext

            return nullcontext()
        return console.status("[dim]nanobot 正在思考...[/dim]", spinner="dots")

    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        """把模型中间进度打印到终端。"""
        prefix = "正在调用工具：" if tool_hint else "进度："
        console.print(f"[dim]↳ {prefix}{content}[/dim]")

    if message:
        async def run_once() -> None:
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id, on_progress=_cli_progress)
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
        return

    from nanobot.bus.events import InboundMessage

    _init_prompt_session()
    console.print(f"{__logo__} 已进入交互模式（输入 [bold]exit[/bold] / [bold]退出[/bold]，或按 [bold]Ctrl+C[/bold] 结束）\n")

    if ":" in session_id:
        cli_channel, cli_chat_id = session_id.split(":", 1)
    else:
        cli_channel, cli_chat_id = "cli", session_id

    def _handle_signal(signum, _frame):
        """收到系统退出信号时，优雅恢复终端并退出。"""
        sig_name = signal.Signals(signum).name
        _restore_terminal()
        console.print(f"\n收到信号 {sig_name}，程序退出。")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _handle_signal)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    async def run_interactive() -> None:
        """交互式聊天主循环。

        结构分成两条并发链路：
        1. `agent_loop.run()` 持续消费入站消息。
        2. `_consume_outbound()` 持续把回复和进度从消息总线取出来。
        """
        # 启动 AgentLoop 的后台任务，负责消费入站消息并触发工具/模型调用
        bus_task = asyncio.create_task(agent_loop.run())
        turn_done = asyncio.Event()
        turn_done.set()
        turn_response: list[str] = []

        async def _consume_outbound() -> None:
            """后台消费 nanobot 输出。"""
            while True:
                try:
                    msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
                    # 区分三类输出：进度、当前回合的最终回复、以及其他（直接打印）
                    if msg.metadata.get("_progress"):
                        # 模型或工具在执行时的进度回调
                        console.print(f"  [dim]↳ {msg.content}[/dim]")
                    elif not turn_done.is_set():
                        # 主协程正在等待当前回合的回复，把第一条回复保存并通知
                        if msg.content:
                            turn_response.append(msg.content)
                        turn_done.set()
                    elif msg.content:
                        # 其他异步到达的消息（例如工具完成后的额外输出）直接打印
                        console.print()
                        _print_agent_response(msg.content, render_markdown=markdown)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

        outbound_task = asyncio.create_task(_consume_outbound())

        try:
            while True:
                try:
                    _flush_pending_tty_input()
                    user_input = await _read_interactive_input_async()
                    command = user_input.strip()

                    if not command:
                        continue
                    if _is_exit_command(command):
                        _restore_terminal()
                        console.print("\n再见！")
                        break

                    turn_done.clear()
                    turn_response.clear()

                    await bus.publish_inbound(
                        InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                        )
                    )

                    # 发布入站消息后，AgentLoop 会异步处理并通过消息总线回传结果。
                    # 主协程在 turn_done 事件上等待，直到代理端写回回复或超时。

                    with _thinking_ctx():
                        await turn_done.wait()

                    if turn_response:
                        _print_agent_response(turn_response[0], render_markdown=markdown)
                except KeyboardInterrupt:
                    _restore_terminal()
                    console.print("\n再见！")
                    break
                except EOFError:
                    _restore_terminal()
                    console.print("\n再见！")
                    break
        finally:
            agent_loop.stop()
            outbound_task.cancel()
            await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
            await agent_loop.close_mcp()

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
