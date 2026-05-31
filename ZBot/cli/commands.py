"""ZBot 命令行入口。"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import typer
from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown

from ZBot import __logo__, __version__
from ZBot.config.loader import load_config
from ZBot.config.paths import get_cli_history_path
from ZBot.config.schema import Config
from ZBot.service.utils.helpers import ensure_dir, ensure_workspace_dirs

app = typer.Typer(name="ZBot", help="ZBot -- 你的个人 AI 助手", no_args_is_help=True)
console = Console()
EXIT_COMMAND = {"exit", "quit", "/exit", "/quit", ":q", "退出", "再见"}
_PROMPT_SESSION: PromptSession | None = None


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=lambda value: version_callback(value),
        is_eager=True,
        help="显示版本信息",
    ),
) -> None:
    """ZBot 主入口，默认不带参数时显示帮助信息。"""
    _ = version


@app.command()
def onboard() -> None:
    """初始化配置文件和工作区。"""
    from ZBot.config.loader import save_config
    from ZBot.config.paths import get_config_path

    config_path = get_config_path()
    if config_path.exists():
        console.print(f"[blue]检测到已有配置文件：{config_path}[/blue]")
        console.print("[bold]y[/bold] = 创建全新配置并覆盖当前文件")
        console.print("[bold]N[/bold] = 只刷新缺失字段")
        if typer.confirm("是否覆盖现有配置？"):
            config = Config()
            save_config(config)
        else:
            config = load_config(config_path=config_path) or Config()
            save_config(config)
            console.print(f"[green]已刷新配置：{config_path}[/green]")
    else:
        config = Config()
        save_config(config)
        console.print(f"[green]已创建配置文件：{config_path}[/green]")

    ensure_workspace_dirs(workspace=config.workspace_path)
    console.print(f"[green]已准备工作区：{config.workspace_path}[/green]")
    console.print(f"\n{__logo__} ZBot 已准备就绪。")
    console.print("\n建议下一步：")
    console.print(f"1. 在 [cyan]{config_path}[/cyan] 中填写模型名称")
    console.print(f"2. 在 [cyan]{config_path}[/cyan] 中填写 API 密钥和 API 地址")
    console.print('3. 开始对话：[cyan]python -m ZBot agent -m "你好"[/cyan]')
    console.print('4. 指定会话：[cyan]python -m ZBot agent -s "work"[/cyan]')


@app.command()
def agent(
    message: Optional[str] = typer.Option(None, "--message", "-m", help="发送给智能体的单次消息"),
    session_name: str = typer.Option("default", "--session", "-s", help="会话名称"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="是否显示调试日志"),
) -> None:
    """启动 ZBot 对话。"""
    if not logs:
        logger.disable("ZBot")

    config = _load_cli_config()
    if message:
        asyncio.run(_run_once(config, message, session_name))
        return

    _init_prompt_session()
    console.print(f"{__logo__} 已进入交互模式，输入 [bold]exit[/bold] 或按 [bold]Ctrl+C[/bold] 结束。\n")
    asyncio.run(_run_interactive(config, session_name))


def version_callback(value: bool) -> None:
    """处理 --version 参数。"""
    if value:
        console.print(f"{__logo__} ZBot 版本 [cyan]{__version__}[/cyan]")
        raise typer.Exit()


def _init_prompt_session() -> None:
    """初始化交互式输入会话。"""
    global _PROMPT_SESSION
    history_file = get_cli_history_path()
    ensure_dir(history_file.parent)
    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),
        multiline=False,
    )


async def _run_once(config: Config, message: str, session_name: str) -> None:
    """执行单次 CLI 对话。"""
    service = _create_cli_service(config)
    try:
        await service.start(session_name, event_sink=_cli_event_sink)
        with _thinking_ctx():
            response = await service.ask(
                message,
                session_name,
                event_sink=_cli_event_sink,
            )
        _print_agent_response(response)
    finally:
        await service.close(session_name)


async def _run_interactive(config: Config, session_name: str) -> None:
    """持续读取用户输入并串行执行 Agent run。"""
    service = _create_cli_service(config)
    await service.start(session_name, event_sink=_cli_event_sink)
    try:
        while True:
            try:
                command = (await _read_interactive_input_async()).strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n再见。")
                return

            if not command:
                continue
            if _is_exit_command(command):
                console.print("\n再见。")
                return

            try:
                with _thinking_ctx():
                    response = await service.ask(
                        command,
                        session_name,
                        event_sink=_cli_event_sink,
                    )
            except KeyboardInterrupt:
                console.print("\n本轮任务已取消。")
                continue
            _print_agent_response(response)
    finally:
        await service.close(session_name)


def _create_cli_service(config: Config):
    """创建 CLI 使用的 AgentRunService；初始化失败在这里统一展示。"""
    from ZBot.service.agent_run.agent_factory import AgentSetupError, create_agent_bundle
    from ZBot.service.agent_run.agent_run_service import AgentRunService

    try:
        return AgentRunService(create_agent_bundle(config))
    except AgentSetupError as exc:
        console.print(f"[red]{exc.message}[/red]")
        raise typer.Exit(1) from exc


async def _read_interactive_input_async() -> str:
    """异步读取用户输入。"""
    if _PROMPT_SESSION is None:
        raise RuntimeError("PromptSession 尚未初始化。")
    with patch_stdout():
        return await _PROMPT_SESSION.prompt_async(HTML("<b fg='ansiblue'>你：</b> "))


async def _cli_event_sink(event: Any) -> None:
    """把结构化事件渲染到终端。"""
    if event.type == "cron.reminder":
        console.print(f"\n[yellow]提醒：{event.message}[/yellow]")
        return
    if event.type in {
        "run.started",
        "run.completed",
        "turn.started",
        "turn.completed",
        "model.started",
        "model.completed",
        "run.closed",
    }:
        return

    if event.type in {"tool.progress", "tool.started"}:
        label = event.agent_label or "主 Agent"
        console.print(f"[bold green]→ {label} 正在调用工具：{event.message}[/bold green]")
        return

    if event.type == "tool.completed":
        label = event.agent_label or "主 Agent"
        console.print(f"[green]✓ {label} 工具完成：{event.message}[/green]")
        return

    if event.type == "tool.failed":
        label = event.agent_label or "主 Agent"
        console.print(f"[yellow]⚠ {label} 工具失败：{event.message}[/yellow]")
        return

    if event.type in {"compaction.started", "compaction.completed"}:
        console.print(f"[yellow]{event.message}[/yellow]")
        return

    if event.type.startswith("subagent."):
        label = event.agent_label or "子 Agent"
        console.print(f"[cyan]{label}：{event.message}[/cyan]")
        return

    if event.type == "agent.progress":
        console.print(f"[green]{event.message}[/green]")
        return

    style = "yellow" if event.type == "run.cancelled" else "red"
    console.print(f"[{style}]{event.message}[/{style}]")


def _load_cli_config() -> Config:
    """加载 CLI 配置，失败时给出友好错误。"""
    config = load_config()
    if config is None:
        console.print("[red]无法加载配置文件，请先运行 'python -m ZBot onboard' 初始化配置。[/red]")
        raise typer.Exit(1)
    return config


def _print_agent_response(response: str) -> None:
    """打印 ZBot 的最终回复。"""
    console.print()
    console.print(f"[cyan]{__logo__} ZBot[/cyan]")
    console.print(Markdown(response))
    console.print()


def _is_exit_command(command: str) -> bool:
    """判断用户输入是否为退出命令。"""
    return command.lower() in EXIT_COMMAND


def _thinking_ctx():
    """返回 CLI 思考状态上下文。"""
    return console.status("[bold green]ZBot 正在思考...[/bold green]", spinner="dots")
