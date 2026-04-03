"""
LLM提供商基础抽象接口
核心作用：定义所有大模型服务商必须实现的统一接口，屏蔽不同厂商API差异
包含：工具调用数据结构、LLM响应标准格式、通用消息清洗工具方法
"""

# 抽象基类作用： 1.强制子类必须实现父类中标记的抽象方法，否则无法创建子类对象；
              # 2.抽象类本身不能被实例化，仅作为规范模板使用；
              # 3.统一子类的接口规范，保证代码的规范性和可扩展性。
from abc import ABC,abstractmethod  # Abstract Base Class
from typing import Any
from dataclasses import dataclass,field

@dataclass
class ToolCallRequest:
    """
    LLM返回的【工具调用请求】数据结构
    标准化不同厂商的工具调用格式（OpenAI/Anthropic/Kimi等）
    """
    id: str # 工具调用唯一ID
    name: str # 工具名称
    arguments: dict[str, Any] # 工具调用参数


@dataclass
class LLMResponse:
    """
    LLM提供商返回的【标准化响应】
    统一所有厂商的响应格式，上层业务无需关心底层厂商差异
    """
    content: str | None # 文本回复内容
    tool_calls: list[ToolCallRequest] = field(default_factory=list) # 工具调用列表
    finish_reason: str = "stop" # 结束原因：stop(正常结束)/tool_calls(需要调用工具)/length(超长)
    usage: dict[str, int] = field(default_factory=dict) # Token用量统计
    reasoning_content: str | None = None # 推理内容
    thinking_blocks: list[dict] | None = None # 思考块


    @property
    def has_tool_calls(self) ->bool:
        """判断响应是否包含工具调用"""
        return len(self.tool_calls) > 0


class LLMProvider(ABC):
    """
    LLM提供商【抽象基类】，所有具体提供商（OpenAI/Anthropic等）必须继承此类
    统一接口 + 通用工具方法，屏蔽底层差异
    """
    def __init__(self, api_key: str | None = None, api_base: str | None = None):

        self.api_key = api_key  # 厂商API密钥
        self.api_base = api_base # 自定义API地址（代理/本地部署）

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str,Any]]) ->list[dict[str,Any]]:
        """
        类的静态方法，无默认参数、依赖对象，清洗空内容消息，避免LLM API返回400错误
        问题场景：MCP工具返回空内容、部分厂商拒绝空字符串消息
        处理逻辑：
        1. 空字符串内容 → 替换为(empty)或None（工具调用场景）
        2. 空文本块列表 → 过滤空项
        3. 字典格式内容 → 标准化为列表
        """
        result: list[dict[str, Any]] = []
        for msg in messages:  # 一次性发多个消息
            # 获取消息内容
            content = msg.get("content")

            # 场景1：内容是空字符串,是助手消息+工具调用 → 内容设为None，否则设为empty
            if isinstance(content,str) and not content:
                clean = dict(msg)    # 浅拷贝
                if clean.get("role") == "assistant" and msg.get("tool_calls"):
                    clean["content"] = None
                else:
                    clean["content"] = "(empty)"
                result.append(clean)
                continue
            
            # 场景2：内容是列表[字典]（多模态消息：文本+图片）
            if isinstance(content,list):
                # 过滤空的文本项
                filtered = [
                    item for item in content
                    if not (
                        isinstance(item,dict) and 
                        item.get("type") in ("text", "input_text", "output_text") and
                        not item.get("text")
                    )
                ]
                # 内容发生变化，重新构造消息
                if len(filtered) != len(content):
                    clean = dict(msg)   
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue
                
            # 场景3：内容是字典 → 标准化为列表
            if isinstance(content,dict):
                clean = dict(msg)
                clean["content"] = list(content)
                result.append(clean)
                continue
            
            result.append(msg) # 正常消息，保留
        
        return result
    

    @staticmethod
    def _sanitize_request_messages(messages: list[dict[str, Any]],
        allowed_keys: frozenset[str], # 不可变集合,不能增删改
    ) -> list[dict[str, Any]]:
        """
        消息字段清洗,只保留厂商支持的字段，删除多余字段，避免API报错
        标准化助手消息：确保必须包含content字段
        """
        sanitized = []
        for msg in messages:
            clean = {
                k:v for k,v in msg.items() 
                if k in allowed_keys
            }
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)
        return sanitized


    @abstractmethod
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
        【抽象方法】发送聊天补全请求（所有厂商必须实现）
        Args:
            messages: 对话历史列表
            tools: 可用工具定义
            model: 模型名称
            max_tokens: 最大回复Token
            temperature: 采样温度（0=确定性，1=创造性）
            reasoning_effort: 推理强度
        Returns:
            标准化LLM响应
        """
        pass

    
    @abstractmethod
    def get_default_model(self) -> str:
        """【抽象方法】获取默认模型名称"""
        pass

