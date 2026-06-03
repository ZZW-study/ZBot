"""记忆相关提示词和工具 schema。"""

from typing import Any

from ZBot.services.formatting.messages import format_messages


# 系统提示词 + 用户提示词 + 工具定义 --> 大模型返回给的工具定义的参数内容
# 工具定义，一定是你写你想要大模型返回什么的内容,然后你去解析工具参数内容，拿到你想要的结果。
SAVE_SESSION_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "保存更新后的会话记忆",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_update": {
                        "type": "string",
                        "description": ("更新后的 SESSION_MEMORY.md 内容。\nMarkdown 格式，按 ## 二级标题分区组织。"),
                    },
                },
                "required": ["memory_update"],
            },
        },
    }
]

SESSION_MEMORY_SYSTEM_PROMPT = (
    "你是会话记忆归档助手，负责压缩对话历史以解决上下文过长问题。\n"
    "⚠️ 必须调用 save_memory 工具返回结果。\n"
    "只提取当前会话专属状态，不提取跨会话通用偏好或长期知识。"
)


def build_session_memory_prompt(current_memory: str, messages: list[dict[str, Any]]) -> str:
    """把会话记忆和待归档对话整理成提示词。"""
    # 格式化消息列表为转录文本
    transcript = "\n".join(format_messages(messages))
    return (
        "请从以下待归档对话中提取当前会话专属状态，生成更新后的 SESSION_MEMORY.md。\n\n"
        "【提取范围】\n"
        "- 项目状态：本会话已经确认的目录、文件、技术栈、架构线索\n"
        "- 任务进度：已完成、未完成、失败原因、下一步待办\n"
        "- 临时要求：只在当前会话有效的约束、计划和用户要求\n"
        "- 环境信息：本会话用到的路径、命令、服务地址、配置位置\n\n"
        "【不提取】\n"
        "- 用户长期偏好、协作习惯、通用知识：由日常记忆处理\n"
        "- 反复验证后长期有效的事实和偏好：由长期记忆处理\n"
        "- 可从代码重新推导的普通细节、一次性工具输出、无结论的猜测\n\n"
        "【合并规则】\n"
        "- 已有内容无变化的，完整保留\n"
        "- 已有内容有更新/推翻的，原地覆盖更新\n"
        "- 新增信息插入对应分区\n"
        "- 每条尽量短、具体、可验证\n\n"
        "## 当前 SESSION_MEMORY.md 已有内容\n"
        f"{current_memory or '(当前会话记忆为空，首次生成)'}\n\n"
        "## 本次待归档的对话内容\n"
        f"{transcript}"
    )


# 日常记忆工具定义
SAVE_DAILY_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_daily_memory",
            "description": "保存一条跨会话可复用的日常记忆记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "跨会话通用信息的结构化内容。\n必须包含【事实】【偏好】【任务】三个部分，用方括号标题分隔。"
                        ),
                    },
                },
                "required": ["content"],
            },
        },
    },
]

DAILY_MEMORY_SYSTEM_PROMPT = (
    "你是日常记忆提取助手，负责从对话中提取跨会话可复用的通用信息。\n"
    "⚠️ 必须调用 save_daily_memory 工具返回结果。\n"
    "只提取跨会话可复用信息，不提取当前会话专属状态。"
)


def build_daily_memory_prompt(messages: list[dict[str, Any]], memory_snapshot: str) -> str:
    """构建每日记忆的提示词"""
    formatted_messages = "\n".join(format_messages(messages)) if messages else ""

    return (
        "请从以下对话中提取跨会话可复用的通用信息。\n\n"
        "【提取范围】\n"
        "- 用户偏好：编码风格、语言习惯、工作习惯、输出格式要求\n"
        "- 用户背景：用户稳定的人设、职业背景、技术栈偏好、值得长期参考的个人细节\n"
        "- 协作方式：用户对助手行为的稳定期待、工作风格偏好、希望的协作模式\n"
        "- 通用知识：未来会复用的工具用法、最佳实践、踩坑经验、技术结论\n"
        "- 长期任务线索：跨会话仍需继续关注的任务及其当前状态\n\n"
        "【不提取】\n"
        "- 当前会话专属信息：项目临时配置、本次临时约定、当前上下文压缩进度\n"
        "- 可从仓库重新推导的普通代码细节\n"
        "- 一次性工具输出、失败流水、未经确认的猜测\n"
        "- 已经出现在已有记忆快照里的重复内容\n\n"
        "【输出格式】直接使用此结构，不要加 Markdown 标记：\n"
        "【事实】\n"
        "- [提取的事实条目]\n\n"
        "【偏好】\n"
        "- [提取的偏好条目]\n\n"
        "【任务】\n"
        "- [提取的任务及状态条目]\n\n"
        "已有记忆快照（不要重复提取）：\n"
        f"{memory_snapshot}\n\n"
        "对话内容：\n"
        f"{formatted_messages}"
    )


SAVE_LONG_TERM_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_long_term_memory",
            "description": "保存从高频召回的日常记忆中提炼的长期记忆精华",
            "parameters": {
                "type": "object",
                "properties": {
                    "long_term_memory": {
                        "type": "string",
                        "description": (
                            "长期记忆精华内容。\n"
                            "每条以 [YYYY-MM-DD HH:MM] 时间戳开头。\n"
                            "只包含经过多次验证的【事实】和【偏好】两部分，不包含任务状态。"
                        ),
                    },
                },
            },
            "required": ["long_term_memory"],
        },
    },
]

LONG_TERM_MEMORY_SYSTEM_PROMPT = (
    "你是长期记忆提炼助手，负责从高频召回的日常记忆中提炼长期有价值的精华信息。\n"
    "⚠️ 必须调用 save_long_term_memory 工具返回结果。\n"
    "只保留经过多次验证、长期有效的信息，不保留临时性、项目特定或任务状态信息。"
)


def build_long_term_memory_prompt(old_memory: str, new_memory: str) -> str:
    """构建提示词，指导模型如何更新长期记忆。"""

    return (
        "请从以下高频召回的日常记忆中提炼长期记忆精华。\n\n"
        "【提炼原则】\n"
        "- 信息已被多次召回（验证了其价值）\n"
        "- 经过时间验证仍然有效、稳定\n"
        "- 合并相似内容，去除冗余\n"
        "- 保留原有仍然有效的长期记忆，并把新信息合并进去\n"
        "- 不复制日常记忆流水，只沉淀短、具体、可验证的长期事实\n\n"
        "【提取范围】\n"
        "- 事实：通用知识、工具用法、最佳实践、踩坑经验\n"
        "- 偏好：用户编码风格、语言习惯、工作习惯\n\n"
        "【不提取】\n"
        "- 任务状态：任务有时效性，完成后无意义\n"
        "- 临时性、项目特定、时效性强的信息\n\n"
        "【冲突处理】新信息与原有记忆冲突时，以新信息为准\n\n"
        "【现有的长期记忆】\n"
        f"{old_memory or '(长期记忆为空，首次生成)'}\n\n"
        "【待提炼的日常记忆】（已多次召回）\n"
        f"{new_memory}\n\n"
        "请返回更新后的完整长期记忆内容，每条以 [YYYY-MM-DD HH:MM] 时间戳开头，只包含【事实】和【偏好】两部分。"
    )
