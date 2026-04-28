"""
基于LiteLLM的LLM提供商实现
核心作用：通过LiteLLM统一调用所有大模型API，100%兼容注册表配置
无需为每个厂商写独立代码，所有逻辑由注册表驱动

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么大模型会返回工具参数而不是普通文本？】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

这是 OpenAI 兼容 API 的 Function Calling（工具调用）机制决定的：

1. API 层面的约定
   - 当请求中包含 `tools` 参数时，模型知道它可以调用工具
   - `tool_choice: "auto"` 让模型自己决定何时调用工具
   - 这是 API 协议层面的约定，不是提示词决定的

2. 模型训练层面
   - 模型在训练时学习了"当有 tools 参数时，用特定格式返回工具调用"
   - 返回格式是：{"tool_calls": [{"function": {"name": "xxx", "arguments": "..."}}]}
   - 这个格式是 OpenAI 定义的，所有兼容厂商都遵循

3. 工具 Schema 的作用
   - tools 参数包含每个工具的 JSON Schema（名称、描述、参数类型）
   - 模型根据 Schema 知道"有哪些工具可用"、"参数是什么类型"
   - 模型根据 Schema 生成符合格式的参数 JSON

4. 提示词的作用
   - 提示词只影响"何时调用工具"的策略决策
   - 提示词不定义"如何返回工具调用"的格式
   - 格式是 API 协议 + 模型训练决定的

【完整流程】
用户消息 → 构建消息 + 工具 Schema → 发给 API
                                        ↓
                    API 返回 tool_calls ← 模型决定调用工具
                                        ↓
                    执行工具 → 结果写回消息 → 再次调用模型
                                        ↓
                    最终返回普通文本 ← 模型完成任务

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import json
import secrets                                  # 安全随机，random伪随机
import string
from typing import Any

import json_repair
import litellm
from litellm import acompletion                 # async，调用大模型，返回回答
from loguru import logger 

from ZBot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from ZBot.providers.registry import find_by_model, find_gateway

_ALLOWED_MSG_KEYS = frozenset({"role","content","tool_calls","tool_call_id", "name", "reasoning_content"}) # 允许的消息标准字段（所有厂商通用）
_ALNUM = string.ascii_letters + string.digits  # 字母数字字符集（生成工具ID）


def _short_tool_id() ->str:
    """
    生成9位字母数字工具ID,兼容所有厂商
    """
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


class LiteLLMProvider(LLMProvider):
    """
    LiteLLM统一调用实现类
    支持所有注册表中的提供商：OpenRouter/Anthropic/OpenAI/国内厂商等
    所有提供商特殊逻辑由registry.py驱动，无硬编码if-elif
    """
    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "",
        provider_name: str | None = None,
    ):
        # 初始化父类（API密钥/地址）
        super().__init__(api_key, api_base)
        self.default_model = default_model
        # 检测网关,返回ProviderSpec类
        self._gateway = find_gateway(provider_name)
        # 监测标准提供商，返回ProviderSpec类
        self._std_provider = find_by_model(default_model)
        litellm.api_key = api_key
        litellm.api_base = api_base    
        # LiteLLM基础配置
        litellm.suppress_debug_info = True  # 关闭调试日志
        litellm.drop_params = True          # 自动删除不支持的参数

    def _resolve_model(self, model: str) -> str:
        """
        模型名称标准化：根据注册表自动添加前缀，便于litellm使用。
        """
        if self._gateway:
            # 网关模式：保证路由到网关内部的模型池
            model = f"{self._gateway.litellm_prefix}/{model}"
            return model

        # 标准厂商：自动添加前缀
        elif self._std_provider:
            model = f"{self._std_provider.litellm_prefix}/{model}"
            return model


    
    def _supports_cache_control(self) -> bool:
        """判断是否支持提示词缓存（Anthropic/OpenRouter）"""
        if self._gateway:
            return self._gateway.supports_prompt_caching
        elif self._std_provider:
            return self._std_provider.supports_prompt_caching
        

    def _apply_cache_control(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """
        注入提示词缓存控制标记

        【缓存策略】
        - system 消息：整个系统提示词缓存（包含角色设定、规则、知识库等）
        - tools 定义：工具列表缓存（函数签名、参数 schema 等）

        【为什么只缓存这两个？】
        - 它们在多轮对话中几乎不变，缓存命中率最高
        - 用户消息每轮都变，缓存无意义
        - 历史对话由 API 自动管理，无需手动标记

        【ephemeral 含义】
        - 短时缓存（约 5 分钟），适合单次会话场景
        - 区别于 persistent（持久缓存），后者适合跨会话复用
        """
        # 处理 system 消息：注入 cache_control 标记
        # API 会根据内容哈希判断是否命中缓存
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg["content"]
                # 纯文本 system 消息
                # 包装为 Anthropic 要求的 list[type=text] 格式
                # cache_control 必须放在最后一个元素上
                new_content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                new_messages.append({**msg, "content": new_content})
            else:
                # 非系统消息（user/assistant/tool）不处理，直接保留
                new_messages.append(msg)

        # 处理 tools 定义：同样注入缓存标记
        # 工具定义通常较长（包含完整的 JSON Schema），缓存收益明显
        new_tools = tools
        if tools:
            new_tools = list(tools)
            # 只在最后一个工具上标记，整个 tools 数组会被缓存
            new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

        return new_messages, new_tools


    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]], extra_keys: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
        """
        消息最终清洗：
        1. 保留标准+厂商专属字段
        2. 移除 tool 消息中的 name 字段（OpenAI 兼容 API 不接受）
        """
        allowed = _ALLOWED_MSG_KEYS | extra_keys
        sanitized = LLMProvider._sanitize_request_messages(messages, allowed)

        for clean in sanitized:
            # OpenAI 兼容 API 的 tool 消息不应包含 name 字段
            if clean.get("role") == "tool":
                clean.pop("name", None)
        return sanitized


    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4396,
        temperature: float = 0.1,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """
        【核心方法】异步发送聊天请求
        完整流程：
        1. 模型名称解析
        2. 提示词缓存注入
        3. 消息清洗
        4. 参数覆盖
        5. 调用LiteLLM
        6. 响应解析
        """
        original_model = model
        model = self._resolve_model(original_model)

        if self._supports_cache_control():
            messages, tools = self._apply_cache_control(messages, tools)

        # 最小Token限制
        # 确保 max_tokens 至少为1，避免传入0导致SDK报错
        max_tokens = max(1, max_tokens)

        # 提示词这是最终拼接 

        # 构造请求参数
        # 构造传入 litellm 的参数字典
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages)),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # 附加认证/地址/请求头
        kwargs["api_key"] = self.api_key
        kwargs["api_base"] = self.api_base
        
        # 推理强度参数
        # 区分 reasoning 强度参数（部分模型支持 chain-of-thought 强化）
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
            kwargs["drop_params"] = True
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 【工具调用配置 - 核心机制】
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 当传入 tools 参数时，API 会告诉模型"你可以调用这些工具"。
        # 模型不是通过提示词学会返回工具参数的，而是：
        #
        # 1. API 协议约定：
        #    - OpenAI 定义了 tool_calls 的返回格式
        #    - 所有兼容厂商（Anthropic、DeepSeek、阿里等）都遵循这个格式
        #
        # 2. 模型训练：
        #    - 模型在训练数据中见过大量工具调用的例子
        #    - 学会了"当有 tools 参数时，用特定 JSON 格式返回调用请求"
        #
        # 3. tool_choice: "auto"：
        #    - 让模型自己决定何时需要调用工具
        #    - 也可以设为 "required" 强制必须调用，或 "none" 禁止调用
        #
        # tools 的内容是每个工具的 JSON Schema，例如：
        # {
        #   "type": "function",
        #   "function": {
        #     "name": "read_file",
        #     "description": "读取文件内容",
        #     "parameters": {
        #       "type": "object",
        #       "properties": {"path": {"type": "string"}},
        #       "required": ["path"]
        #     }
        #   }
        # }
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if tools:
            kwargs["tools"] = tools   # 工具列表（JSON Schema 格式）
            kwargs["tool_choice"] = "auto"

        try:
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 【核心 API 调用】
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # acompletion 是 LiteLLM 的异步调用接口，统一封装了所有厂商的 API。
            #
            # 当请求中包含 tools 参数时，模型可能返回两种格式：
            #
            # 1. 普通文本回复（不需要调用工具）：
            #    {
            #      "role": "assistant",
            #      "content": "你好！有什么我可以帮助你的？"
            #    }
            #
            # 2. 工具调用请求（需要执行工具）：
            #    {
            #      "role": "assistant",
            #      "content": "让我读取这个文件...",  // 可能有思考内容
            #      "tool_calls": [
            #        {
            #          "id": "call_abc123",
            #          "type": "function",
            #          "function": {
            #            "name": "read_file",
            #            "arguments": "{\"path\": \"src/main.py\"}"  // JSON 字符串
            #          }
            #        }
            #      ]
            #    }
            #
            # 关键点：模型返回 tool_calls 是 API 协议决定的，不是提示词！
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            logger.debug("发送给模型的消息：{}", json.dumps(kwargs.get("messages", []), ensure_ascii=False, indent=2))
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            # 捕获调用中的任意异常并以 LLMResponse 错误形式返回，避免上层抛出
            return LLMResponse(
                content=f"调用大模型失败：{str(e)}",
                finish_reason="error",
            )



    def _parse_response(self, response: Any) -> LLMResponse:
        """
        解析LiteLLM响应 → 标准化LLMResponse

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        【模型返回的两种格式】
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        1. 普通回复（不需要工具）：
           response.choices[0].message = {
             "content": "你好！",
             "tool_calls": None
           }

        2. 工具调用请求：
           response.choices[0].message = {
             "content": "让我搜索一下...",
             "tool_calls": [
               {
                 "id": "call_xxx",
                 "type": "function",
                 "function": {
                   "name": "web_search",
                   "arguments": "{\"query\": \"Python教程\"}"  // JSON 字符串
                 }
               }
             ]
           }

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
        choice = response.choices[0]
        message = choice.message
        content = message.content
        finish_reason = choice.finish_reason

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 【解析工具调用】
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 如果模型返回了 tool_calls，说明模型决定调用工具。
        # 我们需要提取：
        #   - name: 工具名称（如 "read_file"）
        #   - arguments: 工具参数（JSON 字符串 → 解析为 dict）
        #
        # 这些参数是由模型根据 tools Schema 生成的，格式符合我们定义的参数类型。
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                # 有些厂商会返回不合规的字符串 JSON，需要恢复为 dict
                if isinstance(args, str):
                    args = json_repair.loads(args)
                tool_calls.append(ToolCallRequest(
                    id=_short_tool_id(),
                    name=tc.function.name,
                    arguments=args,
                ))

        # Token统计
        # 收集 Token 使用统计（如果厂商返回了 usage 字段）
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # 思考内容
        # 某些厂商会携带中间思考链，需要保留以便调试/展示
        reasoning_content = getattr(message, "reasoning_content", None)

        # 返回标准化响应
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
        )

    def get_default_model(self) -> str:
        """获取默认模型"""
        return self.default_model
