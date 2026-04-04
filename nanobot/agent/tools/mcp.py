"""
MCP 客户端核心模块
功能：连接外部 MCP 协议服务器，将服务器提供的工具包装为 Nanobot 框架的原生工具
MCP（Model Context Protocol）：模型上下文协议，用于AI模型与外部服务/工具安全通信
支持三种连接方式：stdio(进程通信)、sse(服务器推送)、streamableHttp(流式HTTP)
"""
import asyncio
# 异步上下文管理器栈：自动管理多个异步资源的创建/销毁（如连接、会话）
from contextlib import AsyncExitStack
from typing import Any

# HTTP客户端：用于SSE/流式HTTP连接MCP服务器
import httpx
# 日志工具：记录连接、工具注册、异常信息
from loguru import logger

# 继承框架原生工具基类：所有AI可用工具的父类
from nanobot.agent.tools.base import Tool
# 工具注册表：统一管理所有AI可用工具
from nanobot.agent.tools.registry import ToolRegistry


class MCPToolWrapper(Tool):
    """
    MCP 工具包装器
    核心作用：将【外部MCP服务器的工具】转换为【Nanobot框架可识别的原生工具】
    继承自Tool基类，严格遵循框架工具规范
    """
    def __init__(self, session, server_name: str, tool_def, tool_timeout: int = 30):
        """
        初始化工具包装器
        :param session: MCP客户端会话（与服务器的连接通道）
        :param server_name: MCP服务器名称（用于唯一标识工具来源）
        :param tool_def: MCP服务器返回的原始工具定义（名称、描述、入参）
        :param tool_timeout: 工具调用超时时间（默认30秒）
        """
        # MCP会话对象：用于调用远程工具
        self._session = session
        # MCP服务器上的原始工具名称
        self._original_name = tool_def.name
        # 包装后的工具名称（全局唯一）：mcp_服务器名_原始工具名
        # 作用：避免不同MCP服务器的工具重名冲突
        self._name = f"mcp_{server_name}_{tool_def.name}"
        # 工具描述：优先使用原始描述，无描述则用工具名
        self._description = tool_def.description or tool_def.name
        # 工具入参Schema：直接使用MCP工具的输入规范（JSON Schema）
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}
        # 工具调用超时时间
        self._tool_timeout = tool_timeout

    # ==================== 框架Tool基类强制要求的属性 ====================
    @property
    def name(self) -> str:
        """包装后的工具唯一名称（AI模型通过此名称调用）"""
        return self._name

    @property
    def description(self) -> str:
        """工具功能描述（供AI模型理解工具用途）"""
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        """工具入参规范（JSON Schema，供AI模型生成调用参数）"""
        return self._parameters

    # ==================== 工具执行核心方法（AI调用时触发） ====================
    async def execute(self, **kwargs: Any) -> str:
        """
        异步执行MCP远程工具
        :param kwargs: AI模型传入的工具参数
        :return: 工具执行结果（字符串格式）
        """
        # 导入MCP类型定义（延迟导入，避免启动依赖）
        from mcp import types

        try:
            # 带超时执行远程MCP工具调用，防止卡死
            result = await asyncio.wait_for(
                # 调用MCP会话的工具方法：传入原始工具名+参数
                self._session.call_tool(self._original_name, arguments=kwargs),
                timeout=self._tool_timeout,
            )
        # 异常1：工具调用超时
        except asyncio.TimeoutError:
            logger.warning("MCP 工具 '{}' 调用超时（{} 秒）", self._name, self._tool_timeout)
            return f"（MCP 工具调用超时：{self._tool_timeout} 秒）"
        # 异常2：任务被取消
        except asyncio.CancelledError:
            # 处理MCP SDK的取消异常：仅当任务被外部主动取消时才抛出
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            logger.warning("MCP 工具 '{}' 被服务端或 SDK 取消", self._name)
            return "（MCP 工具调用已被取消）"
        # 异常3：其他所有执行错误
        except Exception as exc:
            # 记录详细异常日志
            logger.exception(
                "MCP 工具 '{}' 执行失败：{}：{}",
                self._name,
                type(exc).__name__,
                exc,
            )
            return f"（MCP 工具调用失败：{type(exc).__name__}）"

        # ==================== 解析MCP工具返回结果 ====================
        # 拼接返回内容：MCP返回多块内容，统一转为字符串
        parts = []
        for block in result.content:
            # 文本内容：直接提取文本
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            # 其他类型内容：转为字符串
            else:
                parts.append(str(block))
        # 返回拼接结果，无内容时返回默认值
        return "\n".join(parts) or "（工具没有返回内容）"


# ==================== 核心函数：连接所有MCP服务器并注册工具 ====================
async def connect_mcp_servers(
    mcp_servers: dict,    # MCP服务器配置列表（多个服务器）
    registry: ToolRegistry,  # 框架工具注册表（注册后AI可调用）
    stack: AsyncExitStack   # 异步上下文栈：自动管理连接生命周期
) -> None:
    """
    连接所有配置的MCP服务器，拉取工具并注册为框架原生工具
    流程：遍历服务器配置 → 建立连接 → 初始化会话 → 拉取工具 → 包装注册 → 日志输出
    """
    # 延迟导入MCP SDK依赖（避免未配置MCP时加载无用依赖）
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    # 遍历所有MCP服务器配置（key=服务器名，value=配置）
    for name, cfg in mcp_servers.items():
        try:
            # ==================== 1. 判断MCP传输类型 ====================
            transport_type = cfg.type
            # 自动推断传输类型（未手动指定时）
            if not transport_type:
                # 有command → stdio（进程启动）
                if cfg.command:
                    transport_type = "stdio"
                # 有url → 自动判断sse/streamableHttp
                elif cfg.url:
                    # 约定：URL以/sse结尾 → SSE传输；否则→流式HTTP
                    transport_type = (
                        "sse" if cfg.url.rstrip("/").endswith("/sse") else "streamableHttp"
                    )
                # 无command/url → 跳过该服务器
                else:
                    logger.warning("MCP 服务器 '{}' 没有配置 command 或 url，已跳过", name)
                    continue

            # ==================== 2. 根据传输类型建立连接 ====================
            # 类型1：stdio → 启动子进程与MCP服务器通信（本地服务）
            if transport_type == "stdio":
                # 构建stdio服务器参数
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                # 进入异步上下文：自动管理进程读写流
                # stdio_client 返回一个异步可迭代的读/写对，交给 AsyncExitStack 管理其生命周期
                read, write = await stack.enter_async_context(stdio_client(params))

            # 类型2：sse → 服务器推送事件（远程HTTP服务）
            elif transport_type == "sse":
                # 自定义HTTP客户端工厂：合并配置的请求头
                def httpx_client_factory(
                    headers: dict[str, str] | None = None,
                    timeout: httpx.Timeout | None = None,
                    auth: httpx.Auth | None = None,
                ) -> httpx.AsyncClient:
                    merged_headers = {**(cfg.headers or {}), **(headers or {})}
                    return httpx.AsyncClient(
                        headers=merged_headers or None,
                        follow_redirects=True,
                        timeout=timeout,
                        auth=auth,
                    )

                # 建立SSE连接
                # SSE 模式由服务端推送事件到客户端，适合服务端主动推送工具更新的场景
                read, write = await stack.enter_async_context(
                    sse_client(cfg.url, httpx_client_factory=httpx_client_factory)
                )

            # 类型3：streamableHttp → 流式HTTP（兼容大部分远程MCP服务）
            elif transport_type == "streamableHttp":
                # 创建无超时HTTP客户端：避免覆盖工具级别的超时
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=cfg.headers or None,
                        follow_redirects=True,
                        timeout=None,
                    )
                )
                # 建立流式HTTP连接
                # streamable_http_client 返回 read/write/close 三元组，
                # 其中 write 用于向 MCP 发送请求，read 用于接收响应流
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(cfg.url, http_client=http_client)
                )

            # 未知传输类型 → 跳过
            else:
                logger.warning("MCP 服务器 '{}' 的传输类型 '{}' 无法识别，已跳过", name, transport_type)
                continue

            # ==================== 3. 初始化MCP客户端会话 ====================
            # 创建客户端会话：绑定读写流
            # 使用 ClientSession 包装底层读写流，并在退出时自动关闭
            session = await stack.enter_async_context(ClientSession(read, write))
            # 与服务器完成握手、能力协商等初始化流程
            await session.initialize()

            # ==================== 4. 拉取MCP服务器的所有工具 ====================
            tools = await session.list_tools()
            # 配置中启用的工具列表
            enabled_tools = set(cfg.enabled_tools)
            # 通配符* → 启用所有工具
            allow_all_tools = "*" in enabled_tools
            # 注册成功的工具计数
            registered_count = 0
            # 匹配到的启用工具（用于校验配置）
            matched_enabled_tools: set[str] = set()
            # 工具名称列表（日志提示用）
            available_raw_names = [tool_def.name for tool_def in tools.tools]
            available_wrapped_names = [f"mcp_{name}_{tool_def.name}" for tool_def in tools.tools]

            # ==================== 5. 包装并注册工具 ====================
            for tool_def in tools.tools:
                wrapped_name = f"mcp_{name}_{tool_def.name}"
                # 工具过滤：非*且不在启用列表中 → 跳过
                if (
                    not allow_all_tools
                    and tool_def.name not in enabled_tools
                    and wrapped_name not in enabled_tools
                ):
                    logger.debug(
                        "MCP：跳过服务器 '{}' 的工具 '{}'（未出现在 enabledTools 中）",
                        name,
                        wrapped_name,
                    )
                    continue

                # 创建工具包装器 → 注册到框架工具注册表
                # MCPToolWrapper 将远程工具封装为本地 Tool 实例，负责参数/调用适配
                wrapper = MCPToolWrapper(session, name, tool_def, tool_timeout=cfg.tool_timeout)
                registry.register(wrapper)
                logger.debug("MCP：已注册服务器 '{}' 提供的工具 '{}'", name, wrapper.name)
                registered_count += 1

                # 记录匹配到的启用工具
                if enabled_tools:
                    if tool_def.name in enabled_tools:
                        matched_enabled_tools.add(tool_def.name)
                    if wrapped_name in enabled_tools:
                        matched_enabled_tools.add(wrapped_name)

            # ==================== 6. 配置校验：未找到的启用工具 ====================
            if enabled_tools and not allow_all_tools:
                unmatched_enabled_tools = sorted(enabled_tools - matched_enabled_tools)
                if unmatched_enabled_tools:
                    logger.warning(
                        "MCP 服务器 '{}' 中，enabledTools 指定的这些工具未找到：{}。原始工具名：{}。包装后工具名：{}",
                        name,
                        ", ".join(unmatched_enabled_tools),
                        ", ".join(available_raw_names) or "（无）",
                        ", ".join(available_wrapped_names) or "（无）",
                    )

            # 连接成功日志
            logger.info("MCP 服务器 '{}' 已连接，注册工具 {} 个", name, registered_count)

        # 服务器连接失败：记录错误日志
        except Exception as e:
            logger.error("MCP 服务器 '{}' 连接失败：{}", name, e)
