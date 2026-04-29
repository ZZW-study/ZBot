"""Agent 主循环与单轮消息处理。
核心流程：
用户消息 → 构建上下文 → 大模型推理 → [需要工具？] → 执行工具 → 写回结果 → [循环直到完成]
                              ↓
                         不需要工具 → 返回最终回复
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Awaitable, Callable
from loguru import logger

from ZBot.agent.context import ContextBuilder                    
from ZBot.agent.tools.cron import CronTool                       
from ZBot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from ZBot.agent.tools.registry import ToolRegistry              
from ZBot.agent.tools.shell import ExecTool                     
from ZBot.agent.tools.web import WebFetchTool, WebSearchTool     
from ZBot.providers.base import LLMProvider                      
from ZBot.session.manager import Session, SessionManager        
from ZBot.config.schema import ExecToolConfig, WebSearchConfig   
from ZBot.cron.service import CronService                       
from ZBot.providers.base import ToolCallRequest                 


# ==================== 模块级常量 ====================
# 正则表达式：用于匹配大模型输出中的思考块（）<think><think>aaa</think>bbb</think>，它会匹配第一个 </think> 就停止，而不是一直匹配到最后一个。
# </think>：字面匹配结束标签。
_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)  # 方括号 [ ] 表示字符类（character class），用来匹配方括号内列出的任意一个字符。


# ==================== 核心类：AgentLoop ====================
class AgentLoop:
    """运行中的 Agent 实例：构建上下文、调用模型、执行工具并写回会话。
    这是 ZBot 的核心运行时类，类似于一个"AI 助手"的实例。
    每次用户启动对话时，都会创建一个 AgentLoop 实例（或者复用已有的实例）。
    主要职责：
    1. 管理工具注册和执行
    2. 维护会话历史
    3. 执行模型-工具循环
    4. 处理会话记忆归档
    5. 连接 MCP 服务器（如有）
    """

    # 工具返回结果的最大字符数限制（防止会话历史无限膨胀）
    _TOOL_RESULT_MAX_CHARS = 2000

    # ==================== 循环检测配置 ====================
    # 同一工具连续调用相同参数的最大次数
    _MAX_SAME_CALL = 3
    # 循环模式检测窗口大小（检测 A→B→A→B 这种模式）
    _LOOP_PATTERN_WINDOW = 4

    # ==================== 初始化方法 ====================
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        model: str,
        max_iterations: int = 50,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 25,
        reasoning_effort: str | None = None,
        web_search_config: WebSearchConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        mcp_servers: dict[str, Any] | None = None,
    ):


        # ==================== 基础配置 ====================
        self.provider = provider
        self.workspace = workspace
        self.model = model
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window

        # ==================== 可选配置 ====================
        self.reasoning_effort = reasoning_effort
        self.web_search_config = web_search_config or WebSearchConfig()
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        # ==================== 核心组件 ====================
        # 上下文构造器：负责构建发送给模型的 messages 列表
        self.context = ContextBuilder(workspace)

        # 会话管理器：负责会话的持久化和加载
        self.sessions = SessionManager(workspace)

        # 工具注册中心：统一管理所有可用工具
        self.tools = ToolRegistry()

        # ==================== MCP 相关状态 ====================
        # MCP（Model Context Protocol）允许 AI 连接外部服务获取更多工具
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False

        # ==================== 归档相关状态 ====================
        self._is_consolidating: bool = False  # 是否正在归档

        # ==================== 注册默认工具 ====================
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """注册默认工具：文件、Exec、Web，若提供 CronService 则注册 CronTool。"""
        # 如果限制了工作区，文件工具只能访问工作区内的文件
        allowed_dir = self.workspace if self.restrict_to_workspace else None

        # 注册文件操作工具
        for tool_cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(tool_cls(workspace=self.workspace, allowed_dir=allowed_dir))

        # 注册 Shell 执行工具
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )

        # 注册网页搜索工具
        self.tools.register(WebSearchTool(config=self.web_search_config, proxy=self.web_proxy))

        # 注册网页抓取工具
        self.tools.register(WebFetchTool(proxy=self.web_proxy))

        # 如果提供了定时任务服务，注册定时任务工具
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """懒连接 MCP：仅在首次需要 MCP 工具时建立连接以减少启动开销。"""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        from ZBot.agent.tools.mcp import connect_mcp_servers
        self._mcp_connecting = True
        try:
            self._mcp_stack = AsyncExitStack()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
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
        """移除模型输出中的思考块并返回清理后的文本。<think>和<think>包裹。
        这些内容对用户通常没有价值，反而会增加上下文长度和 token 费用。
        例如输入：
        "我来帮你写这个程序。首先需要..."
        返回：
        "我来帮你写这个程序。"
        """
        if not text:
            return None
        cleaned = _THINK_BLOCK_RE.sub("", text).strip()
        return cleaned or None

    @staticmethod
    def _strip_runtime_context(content: str | None) -> str:
        """剥离用户消息中的运行时上下文标签，只保留纯净的用户消息。

        运行时上下文（如当前时间）只在当前轮推理有意义，
        不应被持久化到会话历史中，避免污染会话记忆。

        Args:
            content: 原始用户消息内容（可能包含运行时上下文标签）

        Returns:
            剥离运行时上下文后的纯净用户消息
        """
        if not content:
            return content or ""

        # 使用 ContextBuilder 的运行时上下文标签常量
        runtime_tag = ContextBuilder._RUNTIME_CONTEXT_TAG

        # 如果消息以运行时上下文标签开头，剥离整个上下文块
        if content.startswith(runtime_tag):
            # 找到第一个空行（上下文块与用户消息的分隔）
            lines = content.split("\n\n", 1)
            if len(lines) > 1:
                return lines[1].strip()
            return ""

        return content

    @staticmethod
    def _tool_hint(tool_calls: list[ToolCallRequest]) -> str:
        """把工具调用列表压缩成一行简短提示，便于在 CLI 中展示进度。"""
        hints: list[str] = []

        for tool_call in tool_calls:
            args = tool_call.arguments
            preview = next((value for value in args.values() if isinstance(value, str) and value), None)
            if preview is None:
                hints.append(tool_call.name)
            elif len(preview) > 40:
                hints.append(f'{tool_call.name}("{preview[:40]}...")')
            else:
                hints.append(f'{tool_call.name}("{preview}")')

        return ",".join(hints)

    def _detect_tool_loop(
        self,
        tool_call_history: list[tuple[str, dict[str, Any]]],
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> str | None:
        """检测工具循环调用，返回检测到的循环类型描述，无循环则返回 None。"""
        current_call = (tool_name, tool_args)
        history = tool_call_history + [current_call]

        # ========== 检测连续重复调用 ==========
        same_count = 1
        for i in range(len(history) - 2, -1, -1):
            if history[i] == current_call:
                same_count += 1
            else:
                break

        if same_count >= self._MAX_SAME_CALL:
            return f"连续重复调用 {tool_name} {same_count} 次（相同参数）"

        # ========== 检测交替循环模式 ==========
        if len(history) >= self._LOOP_PATTERN_WINDOW:
            recent = history[-self._LOOP_PATTERN_WINDOW:]
            names = [call[0] for call in recent]
            if names[0] == names[2] and names[1] == names[3] and names[0] != names[1]:
                return f"检测到循环模式: {names[0]} → {names[1]} → {names[0]} → {names[1]}"

        return None

    async def _run_agent_loop(
        self,
        initial_messages: list[dict[str, Any]],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict[str, Any]]]:
        """
        核心方法：执行模型与工具的交互循环。

        这是 Agent 的"大脑"，负责：
        1. 向大模型发送请求（包含消息历史 + 工具定义）
        2. 解析模型响应（判断是否需要调用工具）
        3. 执行工具并回填结果
        4. 循环直到模型给出最终回复或达到迭代上限

        Args:
            initial_messages: 初始消息列表（已包含 system prompt + 历史对话 + 当前用户消息）
            on_progress: 可选的回调函数，用于向 CLI/前端推送进度（如"正在搜索..."提示）

        Returns:
            (final_content, tools_used, messages) 三元组：
            - final_content: 最终返回给用户的文本回复
            - tools_used: 本轮对话中实际使用过的工具名称列表
            - messages: 完整的消息链（包含所有中间工具调用和结果）
        """

        messages = list(initial_messages)
        tools_used: list[str] = []
        final_content: str | None = None
        tool_call_history: list[tuple[str, dict[str, Any]]] = []

        # ========== 主交互循环 ==========
        for _ in range(self.max_iterations):
            logger.debug("Agent循环迭代: {}, 消息长度: {}", _ + 1, len(messages))

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort, # 推理努力程度（仅部分模型支持）
            )

            # 记录调试日志：模型响应详情
            logger.debug(
                "模型回复: 是否包含工具调用={}, 结束原因={}, 回复内容的前100字符={}",
                response.has_tool_calls,
                response.finish_reason,
                (response.content or "")[:100] if response.content else None,
            )

            if response.has_tool_calls:
                if on_progress:
                    # 提取思考内容（去除 <think>...</think> 块，只保留可见文本）
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                # 将模型返回的 tool_calls 转换为标准格式
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

                # 将 assistant 的工具调用意图写入消息链
                self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )


                # 逐个执行工具调用
                for tool_call in response.tool_calls:
                    # ========== 循环检测 ==========
                    loop_detected = self._detect_tool_loop(
                        tool_call_history, tool_call.name, tool_call.arguments
                    )
                    if loop_detected:
                        logger.warning("检测到工具循环调用：{}", loop_detected)
                        result = (
                            f"错误：检测到工具循环调用（{loop_detected}）。\n"
                            "请换一种方式完成任务，或者直接告诉用户当前无法完成。"
                        )
                        self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
                        tools_used.append(tool_call.name)
                        continue

                    tools_used.append(tool_call.name)
                    tool_call_history.append((tool_call.name, tool_call.arguments))
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("调用工具：{}({})", tool_call.name, args_str[:200])

                    # 执行工具
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)

                    # 将工具执行结果追加到消息链
                    self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)

                # 继续下一轮迭代
                continue

            # ========== 处理最终回复 ==========
            # _strip_think 会移除模型可能包含的<think>...</think> 思考块，只保留对外输出的文本
            clean = self._strip_think(response.content)

            if response.finish_reason == "error":
                logger.error("大模型返回错误：{}", (clean or "")[:200])
                final_content = clean or "抱歉，调用大模型时发生了错误。 "
                break

            # 将最终回复写入消息链
            self.context.add_assistant_message(
                messages,
                clean,
                reasoning_content=response.reasoning_content,
            )
            final_content = clean
            break

        # ========== 循环结束检查 ==========
        if final_content is None:
            logger.warning("已达到最大工具迭代次数：{}", self.max_iterations)
            final_content = (
                f"我已达到最大工具调用轮数（{self.max_iterations} 次），仍未完成任务。"
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

    async def consolidate_all(self,session_name: str) -> None:
        """对所有会话执行记忆归档，适用于定期维护或系统关闭前的清理。"""
        session,is_load = await self.sessions.get_or_create(session_name)
        await self.context.memory.consolidate(
            session,
            self.provider,
            self.model,
            memory_window=self.memory_window,
            consolidate_all=True,
        )
        await self.sessions.save(session)

    async def _process_message(
        self,
        content: str,
        session_name: str,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        """处理单条消息，并返回最终回复"""
        logger.info("正在处理消息：{}", content[:80] + "..." if len(content) > 80 else content)
        session,is_load = await self.sessions.get_or_create(session_name)
        if is_load:
            logger.info("会话 '{}' 已加载，包含 {} 条历史消息", session_name, len(session.messages))
            await self.context.memory.write_session_memory(session.memory_snapshot or "无记忆快照")

        # 只有会话累计到一定长度时，才在后台触发会话记忆归档
        self._schedule_consolidation(session)

        # 执行实际的对话逻辑
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
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        """执行一轮标准对话：构造上下文、运行 agent_loop、写回会话。"""
        # 从会话中获取历史消息列表
        history = session.get_history(max_messages=self.memory_window)

        # 构造完整的消息链
        initial_messages = await self.context.build_messages(
            history=history,
            current_message=content,
        )

        # 执行 Agent 交互循环
        final_content, tools_used, all_messages = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress,
        )
        final_content = final_content or "我已经完成处理，但没有需要额外返回的内容。"

        # 将本轮新增的消息写回会话
        self._save_turn(session, all_messages, 1 + len(history), tools_used)
        await self.sessions.save(session)
        return final_content

    def _schedule_consolidation(self, session: Session) -> None:
        """当未归档消息达到阈值时，安排后台归档任务。"""
        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated < self.memory_window or self._is_consolidating:
            return

        async def _run_consolidation() -> None:
            """执行后台归档任务并确保状态回收。"""
            try:
                await self.context.memory.consolidate(
                    session,
                    self.provider,
                    self.model,
                    memory_window=self.memory_window,
                )
            finally:
                self._is_consolidating = False
        # 标记为正在归档
        self._is_consolidating = True
        # 创建异步任务执行归档
        asyncio.create_task(_run_consolidation())


    def _save_turn(
        self,
        session: Session,
        messages: list[dict[str, Any]],
        skip: int,
        tools_used: list[str] | None = None,
    ) -> None:
        """
        把本轮新增消息写回 session（跳过历史部分）。

        此方法负责将 agent_loop 执行后产生的新消息持久化到会话中。
        主要处理：
        1. 跳过已存在的历史消息（由 skip 参数控制）
        2. 标注使用的工具（便于后续查询）
        3. 截断过长的 tool 结果（防止存储膨胀）
        4. 清理 user 消息中的运行时元信息（只保留纯净的对话内容）
        5. 添加时间戳

        Args:
            session: 目标会话对象
            messages: 完整的消息链（包含历史和新增）
            skip: 要跳过的消息数量（通常为 1 + len(history)）
            tools_used: 本轮使用的工具名称列表
        """
        from datetime import datetime

        # 截取本轮新增的消息（跳过 system + 历史部分）
        turn_messages = [dict(message) for message in messages[skip:]]
        # 标注本轮使用过的工具（挂到最后一条 assistant 消息上）
        self._annotate_tools_used(turn_messages, tools_used or [])

        # 逐条处理新增消息
        for entry in turn_messages:
            role = entry.get("role")
            content = entry.get("content")

            # 跳过空的 assistant 消息
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue

            # 截断过长的 tool 结果
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n……（内容已截断）"
            elif role == "user":
                # 剥离运行时上下文标签，只保留纯净的用户消息
                entry["content"] = self._strip_runtime_context(content)

            # 添加时间戳
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)

        # 更新会话的最后修改时间
        session.updated_at = datetime.now()

    @staticmethod
    def _annotate_tools_used(messages: list[dict[str, Any]], tools_used: list[str]) -> None:
        """把本轮使用过的工具集合挂到最后一条 assistant 消息上。"""
        if not tools_used:
            return

        # 去重但保持顺序
        unique_tools = list(dict.fromkeys(tools_used))
        # 从后向前查找第一条 assistant 消息
        for message in reversed(messages):
            if message.get("role") == "assistant":
                message["tools_used"] = unique_tools
                return



    async def process_direct(
        self,
        content: str,
        session_name: str = "default",
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        """供 CLI 调用的入口。"""
        await self._connect_mcp()
        return await self._process_message(content, session_name=session_name, on_progress=on_progress)
