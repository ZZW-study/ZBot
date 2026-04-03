"""LLM provider abstraction module."""

from nanobot.providers.base import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider"]


def __getattr__(name: str):
    if name == "LiteLLMProvider":
        from nanobot.providers.litellm_provider import LiteLLMProvider

        return LiteLLMProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
