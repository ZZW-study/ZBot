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
# 导入 AsyncExitStack：上下文管理器，用于自动管理多个异步资源的生命周期
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
# 正则表达式：用于匹配大模型输出中的思考块（），怎么匹配，
# re.IGNORECASE 表示不区分大小写，可以匹配 、 各种变体
# 思考块是模型在推理过程中产生的中间内容，用户通常不需要看到
# <think>：字面匹配开始标签。
# [\s\S]*?：
# [\s\S] 表示匹配任意字符：\s 匹配空白（空格、换行、制表符等），\S 匹配非空白，两者合在一起覆盖所有字符（包括换行符，而单独的 . 不匹配换行）。
# *? 是非贪婪（懒惰）量词，表示匹配尽可能少的字符，只要能让整个表达式成功。例如对于 <think>aaa</think>bbb</think>，它会匹配第一个 </think> 就停止，而不是一直匹配到最后一个。
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
    4. 处理长期记忆归档
    5. 连接 MCP 服务器（如有）
    """

    # 工具返回结果的最大字符数限制
    # 当工具返回结果很长时（如读取大文件），会截断到这个长度
    # 目的是防止会话历史无限膨胀
    _TOOL_RESULT_MAX_CHARS = 2000

    # ==================== 初始化方法 ====================
    def __init__(
        self,
        provider: LLMProvider,          # 大模型提供者（必填）
        workspace: Path,                # 工作区目录（必填）
        model: str | None = None,       # 使用的模型名称（可选，默认使用提供商的默认模型）
        max_iterations: int = 50,       # 最大工具调用迭代次数（防止无限循环）
        temperature: float = 0.1,       # 采样温度（越低越确定，越高越随机）
        max_tokens: int = 4096,         # 模型最大输出 token 数
        memory_window: int = 25,       # 记忆窗口大小（保留最近多少条历史消息）
        reasoning_effort: str | None = None,               # 推理强度参数（某些模型支持）
        web_search_config: WebSearchConfig | None = None,  # 网页搜索配置
        web_proxy: str | None = None,                      # HTTP 代理地址
        exec_config: ExecToolConfig | None = None,         # Shell 执行配置
        cron_service: CronService | None = None,           # 定时任务服务（可选）
        restrict_to_workspace: bool = False,               # 是否限制文件操作在工作区内
        mcp_servers: dict[str, Any] | None = None,         # MCP 服务器配置字典
    ):
        

        from ZBot.config.schema import ExecToolConfig, WebSearchConfig

        # ==================== 基础配置 ====================
        self.provider = provider    # LLM 提供者实例，用于调用大模型 API
        self.workspace = workspace  # 工作目录路径
        self.model = model
        self.max_iterations = max_iterations    # 防止无限循环的最大迭代次数
        self.temperature = temperature          # 采样温度控制输出确定性
        self.max_tokens = max_tokens            # 单次回复最大 token 数
        self.memory_window = memory_window      # 记忆窗口大小

        # ==================== 可选配置 ====================
        self.reasoning_effort = reasoning_effort  # 推理强度（如支持）
        # 如果未提供搜索配置，创建默认配置
        self.web_search_config = web_search_config or WebSearchConfig()
        self.web_proxy = web_proxy  # HTTP 代理
        # 如果未提供执行配置，创建默认配置
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service  # 定时任务服务实例
        self.restrict_to_workspace = restrict_to_workspace  # 是否限制工作区

        # ==================== 核心组件 ====================
        # 上下文构造器：负责构建发送给模型的 messages 列表
        # 包含：system prompt、历史对话、当前用户消息
        self.context = ContextBuilder(workspace)

        # 会话管理器：负责会话的持久化和加载
        self.sessions = SessionManager(workspace)

        # 工具注册中心：统一管理所有可用工具
        self.tools = ToolRegistry()

        # ==================== MCP 相关状态 ====================
        # MCP（Model Context Protocol）允许 AI 连接外部服务获取更多工具
        self._mcp_servers = mcp_servers or {}           # MCP 服务器配置
        self._mcp_stack: AsyncExitStack | None = None   # MCP 连接的生命周期管理
        self._mcp_connected = False                     # 是否已连接
        self._mcp_connecting = False                    # 是否正在连接中

        # ==================== 归档相关状态 ====================
        # 长期记忆归档：将会话历史压缩后存入记忆文件，减轻上下文负担
        self._consolidating: set[str] = set()                       # 正在归档的会话 key 集合
        self._consolidation_tasks: set[asyncio.Task[Any]] = set()   # 后台归档任务集合
        self._consolidation_locks: dict[str, asyncio.Lock] = {}     # 每个会话的归档锁（防止并发冲突）
        self._processing_lock = asyncio.Lock()                      # 全局消息处理锁

        # ==================== 注册默认工具 ====================
        # 注册 AI 可以使用的各种工具
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """注册默认工具：文件、Exec、Web，若提供 CronService 则注册 CronTool。
        这些工具会注册到 ToolRegistry 中，AI 可以直接调用。
        """
        # 如果限制了工作区，文件工具只能访问工作区内的文件
        # 否则可以访问任意目录（有一定安全风险）
        allowed_dir = self.workspace if self.restrict_to_workspace else None

        # 注册文件操作工具：读取文件
        for tool_cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(tool_cls(workspace=self.workspace, allowed_dir=allowed_dir))

        # 注册 Shell 执行工具：允许 AI 运行终端命令
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),                   # 默认工作目录
                timeout=self.exec_config.timeout,                  # 命令超时时间
                restrict_to_workspace=self.restrict_to_workspace,  # 是否限制在 workspace 内
                path_append=self.exec_config.path_append,          # 额外的 PATH 路径
            )
        )

        # 注册网页搜索工具：使用bocha搜索网页
        self.tools.register(WebSearchTool(config=self.web_search_config, proxy=self.web_proxy))

        # 注册网页抓取工具：抓取网页内容并提取正文
        self.tools.register(WebFetchTool(proxy=self.web_proxy))

        # 如果提供了定时任务服务，注册定时任务工具
        # 这允许 AI 创建和管理定时提醒
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """懒连接(用到时才连接) MCP：仅在首次需要 MCP 工具时建立连接以减少启动开销。
        """
        # 如果已经连接、正在连接、或者没有配置 MCP，则直接返回
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        from ZBot.agent.tools.mcp import connect_mcp_servers
        # 标记为正在连接，防止重复尝试
        self._mcp_connecting = True
        try:
            # 使用 AsyncExitStack 管理多个异步上下文的生命周期
            self._mcp_stack = AsyncExitStack()
            # 连接 MCP 服务器并注册工具
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)

            # 连接成功，标记状态
            self._mcp_connected = True
        except Exception as exc:
            # 连接失败，记录错误日志
            logger.error("连接 MCP 服务器失败（下次收到消息时会重试）：{}", exc)
            # 清理可能部分创建的连接
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            # 无论成功还是失败，都重置连接状态
            self._mcp_connecting = False

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """移除模型输出中的思考块并返回清理后的文本。
        大模型（如 Claude）在推理过程中会产生思考内容，用<think>和<think>包裹。
        这些内容对用户通常没有价值，反而会增加上下文长度和 token 费用。
        例如输入：
        "我来帮你写这个程序。首先需要..."
        返回：
        "我来帮你写这个程序。"
        """
        # 如果输入为空或 None，直接返回 None
        if not text:
            return None
        # 使用正则替换去除所有思考块，然后去除首尾空白
        cleaned = _THINK_BLOCK_RE.sub("", text).strip()
        # 如果清理后为空，返回 None
        return cleaned or None

    @staticmethod
    def _tool_hint(tool_calls: list[ToolCallRequest]) -> str:
        """把工具调用列表压缩成一行简短提示，便于在 CLI 中展示进度。"""
        hints: list[str] = []  # 存储每个工具的简短描述

        # 遍历所有工具调用
        for tool_call in tool_calls:
            args = tool_call.arguments
            preview: str | None = None # 尝试从参数中提取第一个字符串值作为预览
            # 找到第一个非空的字符串值
            preview = next((value for value in args.values() if isinstance(value, str) and value), None)
            # 根据预览内容生成提示文本
            if preview is None:
                # 没有预览，只显示工具名
                hints.append(tool_call.name)
            elif len(preview) > 40:
                # 预览过长，截断并添加省略号
                hints.append(f'{tool_call.name}("{preview[:40]}...")')
            else:
                # 正常显示工具名和预览
                hints.append(f'{tool_call.name}("{preview}")')

        # 用逗号连接所有提示
        return ",".join(hints)

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

        messages = list(initial_messages)    # 浅拷贝，保护原列表不被追加操作影响
        tools_used: list[str] = []           # 记录本轮对话中实际调用过的工具名称（用于后续存档和统计）
        final_content: str | None = None     # 最终返回给用户的文本内容（初始为 None，表示尚未产生回复）

        # ========== 主交互循环 ==========
        # 最多执行 max_iterations 次迭代，防止工具调用进入死循环
        for _ in range(self.max_iterations):
            # 记录调试日志：当前是第几次迭代，消息链长度
            logger.debug("Agent循环迭代: {}, 消息长度: {}", _ + 1, len(messages))

            # 调用大模型（核心 API 调用）
            response = await self.provider.chat(
                messages=messages,                      # 消息历史列表（包含用户消息、assistant 回复、工具结果）
                tools=self.tools.get_definitions(),     # 当前可用的工具定义列表（JSON Schema 格式）
                model=self.model,                       # 使用的模型名称（如 "claude-sonnet-4-6-20250929"）
                temperature=self.temperature,           # 温度参数（控制随机性，越高越有创造力）
                max_tokens=self.max_tokens,             # 最大 token 数（限制回复长度）
                reasoning_effort=self.reasoning_effort, # 推理努力程度（仅部分模型支持）
            )

            # 记录调试日志：模型响应详情
            logger.debug(
                "模型回复: 是否包含工具调用={}, 结束原因={}, 回复内容的前100字符={}",
                response.has_tool_calls,              # 是否包含工具调用
                response.finish_reason,               # 结束原因（"stop"、"tool_calls"、"error"等）
                (response.content or "")[:100] if response.content else None,  # 回复内容前 100 字符预览
            )

            if response.has_tool_calls:
                # 模型决定调用工具（可能一边思考一边调用），打印完就直接下一步

                # 如果有进度回调函数，向 CLI/前端推送当前状态
                if on_progress:
                    # 提取思考内容（去除 <think>...</think> 块，只保留可见文本）
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)  # 推送思考进度
                    # 推送工具调用提示（如"🔍 正在使用 web_search..."）
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                # 将模型返回的 tool_calls 转换为标准格式，以便写入消息链
                # 执行工具前先记录 assistant 的调用意图，工具执行完成后模型能看到完整对话
                tool_call_dicts = [
                    {
                        "id": tool_call.id,                    # 工具调用的唯一标识符
                        "type": "function",                    # 固定为"function"类型
                        "function": {
                            "name": tool_call.name,            # 工具名称（如"web_search"）
                            "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),  # 参数 JSON 字符串
                        },
                    }
                    for tool_call in response.tool_calls  # 遍历所有工具调用（可能一次调用多个工具）
                ]

                # 将 assistant 的工具调用意图写入消息链
                self.context.add_assistant_message(
                    messages,
                    response.content,                               # 模型原始回复（可能包含思考内容）
                    tool_call_dicts,                                # 工具调用列表（标准格式）
                    reasoning_content=response.reasoning_content,   # 推理内容（部分模型支持）
                )
                

                # 逐个执行工具调用
                for tool_call in response.tool_calls:
                    # 记录已使用的工具名称（用于后续统计和存档）
                    tools_used.append(tool_call.name)
                    # 将工具参数转换为 JSON 字符串（用于日志记录）
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    # 记录日志：调用哪个工具、参数是什么（前 200 字符）
                    logger.info("调用工具：{}({})", tool_call.name, args_str[:200])

                    # 执行工具（核心：调用工具注册表中的对应方法）
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)

                    # 将工具执行结果作为一条新消息追加到消息链
                    self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)

                # 继续下一轮迭代（工具执行完毕后，需要再次请求模型以获取下一步指示）
                continue

            # ========== 处理最终回复 ==========
            # 没有工具调用时，说明模型已给出最终回复，本轮对话结束
            # _strip_think 会移除模型可能包含的 <think>...</think> 思考块，只保留对外输出的文本
            clean = self._strip_think(response.content)

            # 检查模型是否返回错误
            if response.finish_reason == "error":
                # 记录错误日志（前 200 字符）
                logger.error("大模型返回错误：{}", (clean or "")[:200])
                # 设置最终回复（错误提示或默认消息）
                final_content = clean or "抱歉，调用大模型时发生了错误。 "
                break  

            # 将最终回复写入消息链（不包含工具调用，纯文本回复）
            self.context.add_assistant_message(
                messages,
                clean,                                         # 清理后的回复文本
                reasoning_content=response.reasoning_content,  # 推理内容
            )
            final_content = clean                              # 设置为最终回复
            break                                              # 跳出循环（已完成任务，无需继续迭代）

        # ========== 循环结束检查 ==========
        if final_content is None:
            # 如果循环结束仍未产生最终内容，说明已达到 max_iterations 限制
            # 这是安全保护机制：防止模型与工具进入无穷回路（如工具调用 - 返回 - 再调用 - 再返回...）
            logger.warning("已达到最大工具迭代次数：{}", self.max_iterations)
            # 向用户说明情况并给出建议
            final_content = (
                f"我已达到最大工具调用轮数（{self.max_iterations} 次），仍未完成任务。"
                "你可以把任务拆成更小的步骤后再试。"
            )
            
        return final_content, tools_used, messages

    async def close_mcp(self) -> None:
        """关闭 MCP 连接栈并清理资源。"""
        # 如果没有 MCP 连接栈，直接返回（无需关闭）
        if not self._mcp_stack:
            return
        try:
            # 异步关闭 MCP 连接栈（关闭所有注册的 MCP 服务器连接）
            await self._mcp_stack.aclose()
        except BaseException as exc:
            # 忽略某些预期的异常（如运行时错误、异常组）
            # 确保关闭过程的异常不会向上传播影响主流程
            if not (isinstance(exc, RuntimeError) or exc.__class__.__name__ == "BaseExceptionGroup"):
                raise
        finally:
            # 无论是否发生异常，都要清理状态
            self._mcp_stack = None      # 清空连接栈引用
            self._mcp_connected = False  # 标记为未连接状态

    async def _process_message(
        self,
        content: str,
        session_name: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None, # 调用后返回一个可等待的异步对象
    ) -> str:
        """
        处理单条消息，并返回最终回复；支持内置命令处理。
        这是处理用户消息的入口方法，负责：
        1. 记录日志（消息预览）
        2. 获取或创建会话
        3. 处理内置命令（/new、/help）
        4. 触发后台记忆归档
        5. 执行实际对话逻辑
        Args:
            content: 用户消息内容
            session_name: 会话名称（如"default"、"work"）
            on_progress: 可选的进度回调函数
        Returns:
            最终回复文本
        """

        preview = content[:80] + "..." if len(content) > 80 else content   # 生成消息预览（超过 80 字符则截断）
        logger.info("正在处理消息：{}", preview)                            # 记录日志：正在处理什么消息
        session = await self.sessions.get_or_create(session_name) 
        command = content.strip().lower()                                  # 将消息转为小写并去除首尾空白（用于命令匹配）

        # ========== 处理内置命令 ==========
        if command == "/new":
            # /new 的语义不是简单清空，而是"先归档，再开始新会话"
            # 这样可以保留之前的对话历史到长期记忆中
            if not await self._archive_and_reset_session(session):
                return "长期记忆归档失败，会话未清空，请稍后重试。"
            return "已开始新的会话。"


        # 只有会话累计到一定长度时，才在后台触发长期记忆归档
        # 这样可以避免频繁归档，同时确保长对话不会丢失重要信息
        self._schedule_consolidation(session)

        # 执行实际的对话逻辑（调用 _run_turn）
        final_content = await self._run_turn(
            session,
            content=content,
            on_progress=on_progress,
        )
        # 生成回复预览（超过 120 字符则截断）
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        # 记录日志：回复内容预览
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
        # 从会话中获取历史消息列表（最多 memory_window 条，防止上下文过长）
        history = session.get_history(max_messages=self.memory_window)

        # 构造完整的消息链（包含 system prompt、历史消息、当前消息）
        initial_messages = await self.context.build_messages(
            history=history,          # 历史消息列表
            current_message=content,  # 当前用户消息
        )

        # 执行 Agent 交互循环（核心：与模型对话、调用工具）
        final_content, tools_used, all_messages = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress,
        )
        # 如果没有返回内容，使用默认提示
        final_content = final_content or "我已经完成处理，但没有需要额外返回的内容。"

        # 将本轮新增的消息写回会话（skip 参数跳过历史部分，只写新增的）
        self._save_turn(session, all_messages, 1 + len(history), tools_used)
        # 保存会话到持久化存储（JSONL 文件）
        await self.sessions.save(session)
        return final_content

    async def _archive_and_reset_session(self, session: Session) -> bool:
        """
        归档当前会话未归档消息并清空会话。
        此方法用于 /new 命令的实现，确保在清空会话之前先将未归档的消息
        保存到长期记忆中，防止对话历史丢失。
        Returns:
            True 表示归档成功，False 表示失败
        """
        # 获取此会话的归档锁（防止并发归档同一会话）
        lock = self._get_consolidation_lock(session.session_name)
        try:
            async with lock:
                # 获取未归档的消息片段（从 last_consolidated 到最新）
                snapshot = session.messages[session.last_consolidated :]
                if snapshot:
                    # 创建临时会话对象（只包含未归档的消息）
                    temp = Session(session_name=session.session_name, messages=list(snapshot))
                    # 执行归档（archive_all=True 表示强制归档所有消息）
                    if not await self._consolidate_memory(temp, archive_all=True):
                        return False  # 归档失败
        except Exception:
            logger.exception("会话 {} 在执行 /new 归档时失败", session.session_name)
            return False

        # 清空会话消息（重置为新会话状态）
        session.clear()
        # 保存到持久化存储
        await self.sessions.save(session)
        return True

    def _schedule_consolidation(self, session: Session) -> None:
        """当未归档消息达到阈值时，安排后台归档任务。"""

        # 计算未归档的消息数量（总消息数 - 最后已归档位置）
        unconsolidated = len(session.messages) - session.last_consolidated
        # 如果未归档消息不足阈值，或会话已在归档中，则直接返回
        if unconsolidated < self.memory_window or session.session_name in self._consolidating:
            return

        # 将会话标记为"正在归档中"（避免重复触发）
        self._consolidating.add(session.session_name)
        # 创建异步任务执行归档（后台运行，不阻塞）
        task = asyncio.create_task(self._run_consolidation(session))
        # 将任务加入跟踪集合（防止被垃圾回收）
        self._consolidation_tasks.add(task)
        # 任务完成后自动从跟踪集合中移除（使用回调）
        task.add_done_callback(self._consolidation_tasks.discard)

    async def _run_consolidation(self, session: Session) -> None:
        """执行后台归档任务并确保状态回收。"""

        try:
            async with self._get_consolidation_lock(session.session_name):
                # 执行实际归档（调用 MemoryStore 进行摘要和持久化）
                await self._consolidate_memory(session)
        finally:
            # 无论归档成功与否，都要从"正在归档"集合中移除
            # 确保状态不会永远卡住
            self._consolidating.discard(session.session_name)

    def _get_consolidation_lock(self, session_name: str) -> asyncio.Lock:
        """
        返回指定 session 的归档锁，若不存在则创建并返回。
        每个会话都有独立的锁，允许多个会话并发归档，
        但同一会话不会被同时归档多次（防止数据竞争）。
        Args:
            session_name: 会话名称
        Returns:
            该会话对应的异步锁对象
        """
        # 尝试从锁字典中获取现有锁
        lock = self._consolidation_locks.get(session_name,None)
        if lock is None:
            # 不存在则创建新锁并存入字典
            lock = asyncio.Lock()
            self._consolidation_locks[session_name] = lock
        return lock

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
        # `skip` 通常等于 1 + len(history)，用于跳过 system + 已有历史，
        # 仅把本轮新增的 assistant/tool/user 消息写进 session。
        # 标注本轮使用过的工具（挂到最后一条 assistant 消息上）
        self._annotate_tools_used(turn_messages, tools_used or [])

        # 逐条处理新增消息
        for entry in turn_messages:
            role = entry.get("role")       # 消息角色（user/assistant/tool）
            content = entry.get("content") # 消息内容

            # 跳过空的 assistant 消息（没有内容且没有工具调用）
            # 这种消息通常是无意义的中间状态
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue

            # tool 结果通常最容易失控增长，落盘前在这里做统一截断
            # 防止某个工具返回超大文本导致存储膨胀
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n……（内容已截断）"
            elif role == "user":
                entry["content"] = content

            # 添加时间戳（如果消息中还没有）
            entry.setdefault("timestamp", datetime.now().isoformat())
            # 将处理后的消息追加到会话中
            session.messages.append(entry)

        # 更新会话的最后修改时间
        session.updated_at = datetime.now()

    @staticmethod
    def _annotate_tools_used(messages: list[dict[str, Any]], tools_used: list[str]) -> None:
        """把本轮使用过的工具集合挂到最后一条 assistant 消息上。"""

        if not tools_used:
            return

        # 去重但保持顺序（先使用的工具排在前面）
        # 使用 dict.fromkeys() 是 Python 中去重保序的标准写法 *
        unique_tools = list(dict.fromkeys(tools_used))
        # 从后向前查找第一条 assistant 消息（最后一条助手回复）
        for message in reversed(messages):
            if message.get("role") == "assistant":
                # 将工具列表挂到消息上（作为自定义字段）
                message["tools_used"] = unique_tools
                return  # 找到并标注后立即返回


    async def _consolidate_memory(self, session: Session, archive_all: bool = False) -> bool:
        """ 把会话交给 `MemoryStore` 做长期记忆归档。"""
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
        session_name: str = "default",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """
        供 CLI 调用的入口。
        """
        await self._connect_mcp()
        return await self._process_message(content, session_name=session_name, on_progress=on_progress)
