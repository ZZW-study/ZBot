"""大模型提供商模块导出入口。

这里做了一个小的懒加载处理：
- 基础类型 `LLMProvider`、`LLMResponse` 直接导出。
- `LiteLLMProvider` 只有在真正访问时才导入。

这样即使运行环境暂时没装完整的 LiteLLM 依赖，导入基础模块时也不会立刻报错。
"""

from nanobot.providers.base import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider"]


def __getattr__(name: str):
    """按需懒加载 `LiteLLMProvider`。"""
    if name == "LiteLLMProvider":
        from nanobot.providers.litellm_provider import LiteLLMProvider

        return LiteLLMProvider
    raise AttributeError(f"模块 {__name__!r} 中不存在属性 {name!r}")
