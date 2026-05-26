"""AgentRunService 工厂：集中构建 AgentRunService 实例。"""

from __future__ import annotations

from ZBot.config.schema import Config
from ZBot.service.agent_run.agent_factory import create_agent_bundle
from ZBot.service.agent_run.agent_run_service import AgentRunService


def create_agent_run_service(config: Config) -> AgentRunService:
    """从 Config 创建 AgentRunService。

    调用 create_agent_bundle + 包装为 AgentRunService。
    失败时抛出 AgentSetupError，由调用方决定如何上报错误。
    """
    return AgentRunService(create_agent_bundle(config))
