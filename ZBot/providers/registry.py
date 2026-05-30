"""
LLM提供商注册中心：所有大模型服务商的【唯一元数据来源】
核心作用：
1. 集中管理所有提供商的配置（API密钥、前缀、检测规则等）
2. 自动匹配模型→提供商，无需硬编码
3. 控制匹配优先级，支持网关/本地/标准厂商分类

新增提供商只需两步：
1. 在PROVIDERS元组添加ProviderSpec
2. 在配置schema添加对应字段
自动适配：环境变量、模型前缀、状态展示、自动检测
"""
from __future__ import annotations
from dataclasses import dataclass


MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "kimi-k2.6": 262_144,
    "moonshotai/kimi-k2.6": 262_144,
    "qwen3.6-max-preview": 262_144,
    "qwen/qwen3.6-max-preview": 262_144,
}


@dataclass(frozen=True)
class ProviderSpec:
    """
    单个LLM提供商的【元数据定义】（不可变）
    所有提供商的配置都通过此类标准化，集中管理
    """
    name: str                                                       # 提供商名字（如dashscope、openai）
    litellm_prefix: str = ""                                        # LiteLLM路由前缀（如dashscope/ → 模型名加前缀,告诉 LiteLLM 用哪个厂商的 SDK 调用）
    is_gateway: bool = False                                        # 是否为网关（OpenRouter/AiHubMix，支持任意模型）
    keywords: tuple[str,...] = ()                                   # 模型名称匹配关键词
    supports_prompt_caching: bool = False                           # 是否支持提示词缓存
    context_windows: dict[str, int] | None = None                    # LiteLLM 未收录的新模型窗口兜底


# 【核心注册表】所有提供商配置
PROVIDERS: tuple[ProviderSpec, ...] = (   # ... 表示任意长度，主要是表达0个也可以

    # ==================== 网关提供商（最高优先级） ====================
    # OpenRouter
    ProviderSpec(
        name="openrouter",
        litellm_prefix="openrouter",
        is_gateway=True,
        supports_prompt_caching=True,
    ),

    # 硅基流动
    ProviderSpec(
        name="siliconflow",
        litellm_prefix="openai",
        is_gateway=True,
        supports_prompt_caching=True,
    ),

    # ==================== 标准厂商 ====================
    # 深度求索
    ProviderSpec(
        name="deepseek",
        litellm_prefix="deepseek",
        keywords=("deepseek","DeepSeek",)
    ),


    # 阿里通义千问
    ProviderSpec(
        name="dashscope",
        litellm_prefix="dashscope",
        keywords=("qwen","tongyi","Qwen",),
        context_windows={
            "qwen3.6-max-preview": 262_144,
            "qwen-max": 32_768,
            "qwen-plus": 131_072,
            "qwen-turbo": 1_000_000,
        },
    ),
)



def find_by_model(model: str) -> ProviderSpec | None:
    """
    根据【模型名称】自动匹配标准厂商提供商
    匹配规则:关键词匹配
    """
    if not model:
        return None

    for spec in PROVIDERS:
        for keyword in spec.keywords:
            if keyword in model:
                return spec
    
    return None


def find_gateway(provider_name: str | None) -> ProviderSpec | None:
    """
    查找网关提供商（OpenRouter/SiliconFlow等）
    用于统一调用多模型网关
    """
    if not provider_name:
        return None
    
    for spec in PROVIDERS:
        if spec.name == provider_name and spec.is_gateway:
            return spec
        
    return None


def context_window_for_model(model: str, provider: ProviderSpec | None = None) -> int | None:
    """Return a locally maintained context window for models missing from LiteLLM metadata."""
    for candidate in (model, model.split("/", 1)[-1]):
        if candidate in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[candidate]

    specs = (provider,) if provider is not None else PROVIDERS
    for spec in specs:
        windows = spec.context_windows or {}
        if model in windows:
            return windows[model]

        normalized = model
        prefix = f"{spec.litellm_prefix}/" if spec.litellm_prefix else ""
        if prefix and normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
        if normalized in windows:
            return windows[normalized]
    return None

