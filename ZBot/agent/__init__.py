"""Agent 核心模块导出入口。

这个包对外暴露的主要能力有三类：
1. `ContextBuilder`：负责拼装送给模型的上下文。
2. `MemoryStore`：负责长期记忆和历史归档。
3. `SkillsLoader`：负责发现与加载技能。

`AgentLoop` 会依赖更多运行时组件，因此改成懒加载，避免在仅做静态导入时提前触发可选依赖。
"""

from ZBot.agent.context import ContextBuilder
from ZBot.agent.memory import MemoryStore
from ZBot.agent.skills import SkillsLoader

__all__ = ["ContextBuilder", "MemoryStore", "SkillsLoader", "AgentLoop"]


def __getattr__(name: str):
    """仅在真正访问时导入 `AgentLoop`。"""
    if name == "AgentLoop":
        from ZBot.agent.loop import AgentLoop

        return AgentLoop
    raise AttributeError(f"模块 {__name__!r} 中不存在属性 {name!r}")
