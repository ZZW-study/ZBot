"""Agent 主循环与单轮消息处理。"""

from __future__ import annotations  # 使用推迟注解，避免运行时的前置导入成本

import asyncio  # 异步支持
import json  # JSON 编解码
import re  # 正则处理
from contextlib import AsyncExitStack  # 管理多个异步上下文
from pathlib import Path  # 文件/路径处理
from typing import TYPE_CHECKING, Any, Awaitable, Callable  # 类型注解

from loguru import logger  # 日志

from nanobot.agent.context import ContextBuilder  # 上下文构造器
from nanobot.agent.tools.cron import CronTool  # 定时任务工具
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool  # 文件工具
from nanobot.agent.tools.registry import ToolRegistry  # 工具注册中心
from nanobot.agent.tools.shell import ExecTool  # 执行 shell 的工具
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool  # web 工具
from nanobot.providers.base import LLMProvider  # 大模型提供者接口
from nanobot.session.manager import Session, SessionManager  # 会话管理

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig, WebSearchConfig
    from nanobot.cron.service import CronService
    from nanobot.providers.base import ToolCallRequest


_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)  # 匹配模型的思考块


class AgentLoop:
    """运行中的 Agent 实例：构建上下文、调用模型、执行工具并写回会话。"""

    _TOOL_RESULT_MAX_CHARS = 2000  # 写回时 tool 内容截断阈值

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        reasoning_effort: str | None = None,
        web_search_config: WebSearchConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict[str, Any] | None = None,
    ):
        """初始化运行时依赖与内部状态。"""
        from nanobot.config.schema import ExecToolConfig, WebSearchConfig

        self.provider = provider  # LLM 提供者实例
        self.workspace = workspace  # 工作目录
        self.model = model or provider.get_default_model()  # 使用显式或默认模型
        self.max_iterations = max_iterations  # 单轮最大迭代次数
        self.temperature = temperature  # 采样温度
        self.max_tokens = max_tokens  # 模型返回 token 限制
        self.memory_window = memory_window  # 构建上下文时保留的历史条目数

        self.reasoning_effort = reasoning_effort  # 可选的推理强度参数
        self.web_search_config = web_search_config or WebSearchConfig()  # web 搜索配置
        self.web_proxy = web_proxy  # HTTP 代理
        self.exec_config = exec_config or ExecToolConfig()  # Exec 工具配置
        self.cron_service = cron_service  # 可选的定时服务实例
        self.restrict_to_workspace = restrict_to_workspace  # 是否限制文件工具到 workspace

        self.context = ContextBuilder(workspace)  # 构造模型需要的 messages

        self.sessions = session_manager or SessionManager(workspace)  # 会话管理器

        self.tools = ToolRegistry()  # 工具注册中心

        self._mcp_servers = mcp_servers or {}  # MCP 配置
        self._mcp_stack: AsyncExitStack | None = None  # MCP 连接的上下文栈
        self._mcp_connected = False  # MCP 是否已连接
        self._mcp_connecting = False  # MCP 是否在连接中

        self._consolidating: set[str] = set()  # 当前正在归档的 session keys
        self._consolidation_tasks: set[asyncio.Task[Any]] = set()  # 后台归档任务集合
        self._consolidation_locks: dict[str, asyncio.Lock] = {}  # 每个 session 的归档锁
        self._processing_lock = asyncio.Lock()  # 全局消息处理锁

        self._register_default_tools()  # 注册默认工具

    def _register_default_tools(self) -> None:
        """注册默认工具：文件、Exec、Web，若提供 CronService 则注册 CronTool。"""
        allowed_dir = self.workspace if self.restrict_to_workspace else None  # 文件工具允许目录

        for tool_cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(tool_cls(workspace=self.workspace, allowed_dir=allowed_dir))  # 注册文件工具

        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
            )
        )  # 注册执行工具

        self.tools.register(WebSearchTool(config=self.web_search_config, proxy=self.web_proxy))  # 注册搜索工具
        self.tools.register(WebFetchTool(proxy=self.web_proxy))  # 注册抓取工具

        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))  # 注册定时任务工具（若可用）

    async def _connect_mcp(self) -> None:
        """懒连接 MCP：仅在首次需要 MCP 工具时建立连接以减少启动开销。"""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return

        from nanobot.agent.tools.mcp import connect_mcp_servers

        self._mcp_connecting = True
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)  # 注册远程工具
            self._mcp_connected = True
        except Exception as exc:
            logger.error("连接 MCP 服务器失败（下次收到消息时会重试）：{}", exc)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """移除模型输出中的 `<think>...</think>` 思考块并返回清理后的文本（或 None）。"""
        if not text:
            return None
        cleaned = _THINK_BLOCK_RE.sub("", text).strip()
        return cleaned or None

    @staticmethod
    def _tool_hint(tool_calls: list[ToolCallRequest]) -> str:
        """把工具调用列表压缩成一行简短提示，便于进度展示。"""
        hints: list[str] = []
        for tool_call in tool_calls:
            args = tool_call.arguments
            if isinstance(args, list) and args:
                args = args[0]

            preview: str | None = None
            if isinstance(args, dict):
                preview = next((value for value in args.values() if isinstance(value, str) and value), None)

            if preview is None:
                hints.append(tool_call.name)
            elif len(preview) > 40:
                hints.append(f'{tool_call.name}("{preview[:40]}...")')
            else:
                hints.append(f'{tool_call.name}("{preview}")')
        return ", ".join(hints)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict[str, Any]],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict[str, Any]]]:
        """执行模型与工具的交互循环，直到得到最终回复或达到迭代上限。"""

        messages = list(initial_messages)  # 复制消息链以免修改输入参数
        tools_used: list[str] = []  # 本轮实际调用过的工具名
        final_content: str | None = None  # 最终返回给用户的文本

        for _ in range(self.max_iterations):
            logger.debug("Agent loop iteration {}, messages count: {}", _ + 1, len(messages))
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
            )
            logger.debug(
                "Model response: has_tool_calls={}, finish_reason={}, content_preview={}",
                response.has_tool_calls,
                response.finish_reason,
                (response.content or "")[:100] if response.content else None,
            )

            if response.has_tool_calls:
                # 如果模型一边思考一边决定调用工具，这里把精简后的状态向外发送，
                # 让 CLI 或前端能够展示"正在做什么"。
                if on_progress:
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                # 将模型返回的 tool_calls 转为写入消息链的"函数调用"结构，
                # 这样在执行工具前，消息链中就包含了 assistant 的调用意图，
                # 便于下一轮模型看到自己的调用历史。
                tool_call_dicts = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                        },
                    }
                    for tool_call in response.tool_calls
                ]

                self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    # 逐个执行工具，并把结果回填给模型。工具可能涉及网络/IO/子进程，故需 await。
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("调用工具：{}({})", tool_call.name, args_str[:200])
                    # 执行工具，得到任意可序列化的结果（字符串或结构化对象）
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    # 将工具执行结果作为一条 role=tool 的消息追加到 messages，供模型下一轮消费
                    self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
                continue

            # 没有工具调用时，本轮对话结束，clean 后的文本就是最终回复。
            # `_strip_think` 会移除模型可能包含的 <think>...</think> 思考块，只保留最终输出。
            clean = self._strip_think(response.content)
            if response.finish_reason == "error":
                logger.error("大模型返回错误：{}", (clean or "")[:200])
                final_content = clean or "抱歉，调用大模型时发生了错误。 "
                break

            self.context.add_assistant_message(
                messages,
                clean,
                reasoning_content=response.reasoning_content,
                thinking_blocks=response.thinking_blocks,
            )
            final_content = clean
            break

        if final_content is None:
            # 如果循环结束仍未产生最终内容，说明已达到 max_iterations 限制。
            # 这是为了防止模型与工具进入无穷回路。向用户说明原因并建议拆分任务。
            logger.warning("已达到最大工具迭代次数：{}", self.max_iterations)
            final_content = (
                f"我已经达到最大工具调用轮数（{self.max_iterations} 次），仍未完成任务。"
                "你可以把任务拆成更小的步骤后再试。"
            )

        return final_content, tools_used, messages

    async def close_mcp(self) -> None:
        """关闭 MCP 连接栈并清理资源。"""
        if not self._mcp_stack:
            return
        try:
            await self._mcp_stack.aclose()
        except BaseException as exc:
            if not (isinstance(exc, RuntimeError) or exc.__class__.__name__ == "BaseExceptionGroup"):
                raise
        finally:
            self._mcp_stack = None
            self._mcp_connected = False

    async def _process_message(
        self,
        content: str,
        session_key: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """处理单条消息，并返回最终回复；支持内置命令处理。"""
        preview = content[:80] + "..." if len(content) > 80 else content
        logger.info("正在处理消息：{}", preview)

        session = self.sessions.get_or_create(session_key)
        command = content.strip().lower()

        if command == "/new":
            # /new 的语义不是简单清空，而是"先归档，再开始新会话"。
            if not await self._archive_and_reset_session(session):
                return "长期记忆归档失败，会话未清空，请稍后重试。"
            return "已开始新的会话。"

        if command == "/help":
            return "nanobot 可用命令：\n/new - 开始新会话\n/help - 查看帮助"

        # 只有会话累计到一定长度时，才在后台触发长期记忆归档。
        self._schedule_consolidation(session)

        final_content = await self._run_turn(
            session,
            content=content,
            on_progress=on_progress,
        )
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("回复：{}", preview)

        return final_content

    async def _run_turn(
        self,
        session: Session,
        *,
        content: str,
        media: list[str] | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        """执行一轮标准对话：构造上下文、运行 agent_loop、写回会话。"""
        history = session.get_history(max_messages=self.memory_window)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=content,
            media=media,
        )

        final_content, tools_used, all_messages = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress,
        )
        final_content = final_content or "我已经完成处理，但没有需要额外返回的内容。"

        self._save_turn(session, all_messages, 1 + len(history), tools_used)
        self.sessions.save(session)
        return final_content

    async def _archive_and_reset_session(self, session: Session) -> bool:
        """归档当前会话未归档消息并清空会话。"""
        lock = self._get_consolidation_lock(session.key)
        self._consolidating.add(session.key)
        try:
            async with lock:
                snapshot = session.messages[session.last_consolidated :]
                if snapshot:
                    temp = Session(key=session.key, messages=list(snapshot))
                    if not await self._consolidate_memory(temp, archive_all=True):
                        return False
        except Exception:
            logger.exception("会话 {} 在执行 /new 归档时失败", session.key)
            return False
        finally:
            self._consolidating.discard(session.key)

        session.clear()
        self.sessions.save(session)
        self.sessions.invalidate(session.key)
        return True

    def _schedule_consolidation(self, session: Session) -> None:
        """当未归档消息达到阈值时，安排后台归档任务。"""
        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated < self.memory_window or session.key in self._consolidating:
            return

        self._consolidating.add(session.key)
        task = asyncio.create_task(self._run_consolidation(session))
        self._consolidation_tasks.add(task)
        task.add_done_callback(self._consolidation_tasks.discard)

    async def _run_consolidation(self, session: Session) -> None:
        """执行后台归档任务并确保状态回收。"""
        try:
            async with self._get_consolidation_lock(session.key):
                await self._consolidate_memory(session)
        finally:
            self._consolidating.discard(session.key)

    def _get_consolidation_lock(self, session_key: str) -> asyncio.Lock:
        """返回指定 session 的归档锁，若不存在则创建并返回。"""
        lock = self._consolidation_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._consolidation_locks[session_key] = lock
        return lock

    def _save_turn(
        self,
        session: Session,
        messages: list[dict[str, Any]],
        skip: int,
        tools_used: list[str] | None = None,
    ) -> None:
        """把本轮新增消息写回 session（跳过历史部分）。"""
        from datetime import datetime

        turn_messages = [dict(message) for message in messages[skip:]]
        # `skip` 通常等于 1 + len(history)，用于跳过 system + 已有历史，
        # 仅把本轮新增的 assistant/tool/user 消息写进 session。
        self._annotate_tools_used(turn_messages, tools_used or [])

        for entry in turn_messages:
            role = entry.get("role")
            content = entry.get("content")

            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue

            # tool 结果通常最容易失控增长，落盘前在这里做统一截断。
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n……（内容已截断）"
            elif role == "user":
                # user 消息里会混入当前轮的运行时元信息，写回历史前必须去掉。
                stripped = self._strip_runtime_context(content)
                if stripped is None:
                    continue
                entry["content"] = stripped

            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)

        session.updated_at = datetime.now()

    @staticmethod
    def _annotate_tools_used(messages: list[dict[str, Any]], tools_used: list[str]) -> None:
        """把本轮使用过的工具集合挂到最后一条 assistant 消息上。"""
        if not tools_used:
            return

        unique_tools = list(dict.fromkeys(tools_used))
        for message in reversed(messages):
            if message.get("role") == "assistant":
                message["tools_used"] = unique_tools
                return

    @staticmethod
    def _strip_runtime_context(content: Any) -> str | list[dict[str, Any]] | None:
        """从 user 消息里移除运行时元信息。

        运行时信息只对当前轮推理有意义，长期保留在 session 里会污染历史，
        所以这里在落盘前主动清理。
        """
        if isinstance(content, str):
            if content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG) or content.startswith(ContextBuilder._LEGACY_RUNTIME_CONTEXT_TAG):
                parts = content.split("\n\n", 1)
                return parts[1] if len(parts) > 1 and parts[1].strip() else None
            return content

        if not isinstance(content, list):
            return content

        # 对于 list 形式的混合内容（例如图片+文本），逐项过滤运行时上下文并把图片替换为占位
        filtered: list[dict[str, Any]] = []
        for item in content:
            if (
                item.get("type") == "text"
                and isinstance(item.get("text"), str)
                and (
                    item["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
                    or item["text"].startswith(ContextBuilder._LEGACY_RUNTIME_CONTEXT_TAG)
                )
            ):
                continue
            if (
                item.get("type") == "image_url"
                and item.get("image_url", {}).get("url", "").startswith("data:image/")
            ):
                filtered.append({"type": "text", "text": "[image]"})
            else:
                filtered.append(item)
        return filtered or None

    async def _consolidate_memory(self, session: Session, archive_all: bool = False) -> bool:
        """把会话交给 `MemoryStore` 做长期记忆归档。"""
        # 这里把 session 的未归档段落交给 MemoryStore 处理，
        # MemoryStore 负责生成摘要、向持久化/向量库落盘并决定是否归档到长期记忆。
        return await self.context.memory.consolidate(
            session,
            self.provider,
            self.model,
            archive_all=archive_all,
            memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """供 CLI 或脚本直接调用的一次性入口。"""
        # 用于脚本/测试/CLI 的同步入口：确保 MCP 已连接（若需要），然后同步处理一条消息并返回文本。
        await self._connect_mcp()
        return await self._process_message(content, session_key=session_key, on_progress=on_progress)
