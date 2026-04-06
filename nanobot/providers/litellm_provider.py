"""
基于LiteLLM的LLM提供商实现
核心作用：通过LiteLLM统一调用所有大模型API，100%兼容注册表配置
无需为每个厂商写独立代码，所有逻辑由注册表驱动
"""

import hashlib
import json
import os
import secrets  # 安全随机，random伪随机
import string
from typing import Any

import json_repair
import litellm
from litellm import acompletion  # async，调用大模型，返回回答
from loguru import logger 

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway


_ALLOWED_MSG_KEYS = frozenset({"role","content","tool_calls","tool_call_id", "name", "reasoning_content"}) # 允许的消息标准字段（所有厂商通用）
_ANTHROPIC_EXTRA_KEYS = frozenset({"thinking_blocks"})  # Anthropic专属额外字段
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
        default_model: str = "anthropic/claude-opus-4-5",
        provider_name: str | None = None,
    ):
        # 初始化父类（API密钥/地址）
        super().__init__(api_key, api_base)
        self.default_model = default_model

        # 自动检测网关/本地部署,返回ProviderSpec类
        self._gateway = find_gateway(provider_name)

        if api_key:  #  设置环境变量（API密钥）
            self._setup_env(api_key,api_base,default_model)

        if api_base: # 设置api地址
            litellm.api_base = api_base
            
        # LiteLLM基础配置
        litellm.suppress_debug_info = True  # 关闭调试日志
        litellm.drop_params = True  # 自动删除不支持的参数

    def _setup_env(self,api_key: str,api_base: str | None,model: str) ->None:
        """ 
        根据注册表配置，自动设置环境变量
        网关：覆盖环境变量；标准厂商：仅设置默认值
        """
        # 保证有模型类且有环境变量名
        spec = self._gateway or find_by_model(model)
        if not spec or not spec.env_key:
            return
        
        # 如果是网关模式，覆盖对应的 env 变量；否则保守设置（不覆盖已有）
        if self._gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key,api_key)

        # 解析扩展环境变量占位符
        # 解析注册表中定义的额外环境变量占位符（例如某些厂商需要多个变量）
        effective_base = api_base or spec.default_api_base
        for env_name,env_value in spec.env_extras:
            resolved_name = env_name.replace("{api_key}", api_key).replace("{api_base}", effective_base)
            resolved_value = env_value.replace("{api_key}", api_key).replace("{api_base}", effective_base)
            os.environ.setdefault(resolved_name, resolved_value)


    def _resolve_model(self, model: str) -> str:
        """
        模型名称标准化：根据注册表自动添加/剥离前缀
        网关模式：应用网关前缀
        标准模式：应用厂商前缀
        """
        if self._gateway:
            # 网关模式：有些网关要求去掉厂商前缀再加上网关前缀，保证路由到网关内部的模型池
            prefix = self._gateway.litellm_prefix
            if self._gateway.strip_model_prefix:
                model = model.split("/")[-1]
            if prefix and not model.startswith(f"{prefix}/"):
                model = f"{prefix}/{model}"
            return model

        # 标准厂商：自动添加前缀
        # 标准厂商模式：根据注册表将厂商前缀规范化（例如把 github-copilot 映射为 canonical 前缀）
        spec = find_by_model(model)
        if spec and spec.litellm_prefix:
            model = self._canonicalize_explicit_prefix(model, spec.name, spec.litellm_prefix)
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"

        return model


    @staticmethod
    def _canonicalize_explicit_prefix(model: str,spec_name: str,canonical_prefix: str) ->str:
        """标准化显式前缀（如github-copilot/ → github_copilot/）"""
        if "/" not in model:
            return model

        prefix,remainder = model.split("/",1)
        if prefix.lower().replace("-", "_") != spec_name:
            return model
        return f"{canonical_prefix}/{remainder}"

    
    def _supports_cache_control(self, model: str) -> bool:
        """判断是否支持提示词缓存（Anthropic/OpenRouter）"""
        if self._gateway is not None:
            return self._gateway.supports_prompt_caching
        spec = find_by_model(model)
        return spec is not None and spec.supports_prompt_caching

    def _apply_cache_control(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """
        注入提示词缓存控制
        为系统消息和最后一个工具添加缓存标记，降低Token费用
        """
        # 为 system 消息和最后一个工具注入 cache_control 字段，提示网关/SDK 进行短期缓存
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg["content"]
                if isinstance(content, str):
                    # 把纯文本包装为 list[type=text]，并标记为 ephemeral（短期缓存）
                    new_content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                else:
                    # 如果已经是 list 结构则只在最后一项注入 cache_control
                    new_content = list(content)
                    new_content[-1] = {**new_content[-1], "cache_control": {"type": "ephemeral"}}
                new_messages.append({**msg, "content": new_content})
            else:
                new_messages.append(msg)

        # 给最后一个工具也加上 cache_control，减少模型重复调用成本
        new_tools = tools
        if tools:
            new_tools = list(tools)
            new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

        return new_messages, new_tools

    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """应用模型专属参数（如Kimi强制温度1.0）"""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return


    @staticmethod
    def _normalize_tool_call_id(tool_call_id: Any) -> Any:
        """
        工具ID标准化：
        不符合9位字母数字的ID → 哈希截取为9位
        兼容所有严格厂商
        """
        if not isinstance(tool_call_id, str):
            return tool_call_id
        if len(tool_call_id) == 9 and tool_call_id.isalnum():
            return tool_call_id
        return hashlib.sha1(tool_call_id.encode()).hexdigest()[:9]

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]], extra_keys: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
        """
        消息最终清洗：
        1. 保留标准+厂商专属字段
        2. 标准化工具ID，保证工具调用链路完整
        3. 移除 tool 消息中的 name 字段（OpenAI 兼容 API 不接受）
        """
        # 允许的字段集合 = 通用字段 + 厂商额外字段
        allowed = _ALLOWED_MSG_KEYS | extra_keys
        sanitized = LLMProvider._sanitize_request_messages(messages, allowed)
        # id_map 用于把任意工具调用ID规范化为短ID，并保证同一原始ID映射到同一短ID
        id_map: dict[str, str] = {}

        def map_id(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            # 如果之前已经映射过则复用，否则用标准化函数生成9位ID
            return id_map.setdefault(value, LiteLLMProvider._normalize_tool_call_id(value))

        # 标准化工具调用ID
        for clean in sanitized:
            # 标准化消息中嵌套的 tool_calls 字段（如果存在）
            if isinstance(clean.get("tool_calls"), list):
                normalized_tool_calls = []
                for tc in clean["tool_calls"]:
                    if not isinstance(tc, dict):
                        normalized_tool_calls.append(tc)
                        continue
                    tc_clean = dict(tc)
                    tc_clean["id"] = map_id(tc_clean.get("id"))
                    normalized_tool_calls.append(tc_clean)
                clean["tool_calls"] = normalized_tool_calls

            # 标准化消息级别的 tool_call_id（如模型直接返回tool_call_id）
            if "tool_call_id" in clean and clean["tool_call_id"]:
                clean["tool_call_id"] = map_id(clean["tool_call_id"])

            # OpenAI 兼容 API 的 tool 消息不应包含 name 字段
            if clean.get("role") == "tool":
                clean.pop("name", None)
        return sanitized

    def _extra_msg_keys(self, original_model: str, resolved_model: str) -> frozenset[str]:
        """根据模型类型返回额外的允许消息字段。"""
        # Anthropic 模型支持 thinking_blocks 字段
        if "anthropic" in original_model.lower() or "anthropic" in resolved_model.lower():
            return _ANTHROPIC_EXTRA_KEYS
        return frozenset()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
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
        original_model = model or self.default_model
        model = self._resolve_model(original_model)
        extra_msg_keys = self._extra_msg_keys(original_model, model)

        # 开启提示词缓存
        # 若厂商/网关支持提示词缓存，则注入 cache_control 优化 token 使用
        if self._supports_cache_control(original_model):
            messages, tools = self._apply_cache_control(messages, tools)

        # 最小Token限制
        # 确保 max_tokens 至少为1，避免传入0导致SDK报错
        max_tokens = max(1, max_tokens)

        # 构造请求参数
        # 构造传入 litellm 的参数字典
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages), extra_keys=extra_msg_keys),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # 应用模型专属参数
        self._apply_model_overrides(model, kwargs)

        # 附加认证/地址/请求头
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        
        # 推理强度参数
        # 区分 reasoning 强度参数（部分模型支持 chain-of-thought 强化）
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
            kwargs["drop_params"] = True
        
        # 工具调用配置
        # 如果传入 tools 配置，启用自动工具选择（由模型决定何时调用工具）
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            # 异步调用 LiteLLM SDK 的 acompletion 接口
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
        兼容多Choice响应、工具调用合并、Token统计、思考内容
        """
        # 解析第一个 choice（多数 SDK 保证至少有一个 choice，会有多种回复，选第一个）
        choice = response.choices[0]  
        message = choice.message
        content = message.content
        finish_reason = choice.finish_reason

        # 合并多Choice的工具调用（Copilot等厂商）
        # 合并所有 choice 里的 tool_calls（一些厂商可能把工具调用分散在多个候选里）
        raw_tool_calls = []
        for ch in response.choices:
            msg = ch.message
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                raw_tool_calls.extend(msg.tool_calls)
                if ch.finish_reason in ("tool_calls", "stop"):
                    finish_reason = ch.finish_reason
            # 如果主 choice 没有 content，回退到其他候选的 content
            if not content and msg.content:
                content = msg.content

        # 日志：多Choice合并
        if len(response.choices) > 1:
            logger.debug(
                "LiteLLM 返回了 {} 个候选结果，已合并 {} 个工具调用",
                len(response.choices),
                len(raw_tool_calls),
            )

        # 构造工具调用列表
        # 把 raw_tool_calls 转为内部的 ToolCallRequest 结构，统一 id/name/arguments 字段
        tool_calls = []
        for tc in raw_tool_calls:
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
        # 某些厂商会携带中间思考链或扩展的 thinking_blocks，需要保留以便调试/展示
        reasoning_content = getattr(message, "reasoning_content", None)
        thinking_blocks = getattr(message, "thinking_blocks", None)

        # 返回标准化响应
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        )

    def get_default_model(self) -> str:
        """获取默认模型"""
        return self.default_model
