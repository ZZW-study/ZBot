"""Agent 运行依赖工厂。

这个模块只负责把全局配置装配成一次可运行的 Agent 环境，不负责打印、
HTTP/WebSocket 通信或前端展示。
"""

from __future__ import annotations

from dataclasses import dataclass

from ZBot.agent.core_agent import CoreAgent
from ZBot.config.agent_runtime import AgentRuntimeConfig
from ZBot.config.paths import get_config_path, get_runtime_subdir
from ZBot.config.schema import Config, ProviderConfig
from ZBot.cron.service import CronService
from ZBot.providers.litellm_provider import LiteLLMProvider


# 可以自己配置错误，可以自己决定如何展示,raise之后，里面的属性，你可以外部捕获
class AgentSetupError(RuntimeError):
    """Agent 运行环境初始化失败。"""

    def __init__(self, message: str, code: str = "agent_setup_failed") -> None:
        """保存可展示消息和稳定错误码，供 CLI/HTTP/WebSocket 统一消费。"""
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(slots=True)
class AgentBundle:
    """一次 Agent 运行所需的依赖集合。"""

    provider: LiteLLMProvider
    runtime_config: AgentRuntimeConfig
    cron: CronService
    agent: CoreAgent


def create_agent_bundle(
    config: Config,
    *,
    on_cron_job=None,
) -> AgentBundle:
    """根据全局配置创建 provider、runtime config、cron 和 CoreAgent。"""
    provider = create_provider(config)
    runtime_config = AgentRuntimeConfig.from_app_config(
        config=config,
        model=provider.default_model,
    )
    cron_store_path = get_runtime_subdir("cron") / "jobs.json"
    cron = CronService(cron_store_path, on_job=on_cron_job)
    agent = CoreAgent(
        provider=provider,
        runtime_config=runtime_config,
        cron_service=cron,
    )
    return AgentBundle(
        provider=provider,
        runtime_config=runtime_config,
        cron=cron,
        agent=agent,
    )


def create_provider(config: Config) -> LiteLLMProvider:
    """根据配置创建 LLM Provider。"""
    provider_config, provider_name, is_gateway, model = resolve_provider_config(config)
    provider_model = model.split("/", 1)[1] if is_gateway and model.startswith(f"{provider_name}/") else model
    return LiteLLMProvider(
        api_key=provider_config.api_key,
        api_base=provider_config.api_base,
        default_model=provider_model,
        provider_name=provider_name,
    )


def resolve_provider_config(config: Config) -> tuple[ProviderConfig, str, bool, str]:
    """解析并校验模型对应的 provider 配置。"""
    config_path = get_config_path()
    model = config.model
    if not model:
        raise AgentSetupError(f"未填写模型名称，请到配置 {config_path} 中填写 model。")

    provider_config, provider_name, is_gateway = config.get_provider(model)
    if not provider_name or provider_config is None:
        # 对外抛出异常，可有外部捕获处理
        raise AgentSetupError(f"无法为模型 {model} 自动匹配提供商，请检查 provider 配置和模型名称前缀。")
    if not provider_config.api_key:
        raise AgentSetupError(f"尚未配置 {provider_name} 的 API 密钥，请检查 {config_path}。")
    if not provider_config.api_base:
        raise AgentSetupError(f"尚未配置 {provider_name} 的 API 地址，请检查 {config_path}。")

    return provider_config, provider_name, bool(is_gateway), model
