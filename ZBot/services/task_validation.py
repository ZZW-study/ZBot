# 设计hook机制
# 任务完成时，进行检验，看是否真的完成
import json
from typing import Any

from loguru import logger

from ZBot.prompts.validation import TASK_VALIDATION_SYSTEM_PROMPT, build_task_validation_user_prompt
from ZBot.providers.base import LLMProvider, LLMResponse


async def validate_before_task_complete_hook(
    provider: LLMProvider,
    model: str,
    user_message: str,
    final_content: str,
    filter_message: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    在任务完成前进行最终验收。

    返回 True 表示可以结束任务。
    返回 False 表示任务证据不足或尚未完成，agent 应继续执行。
    """

    system_prompt = TASK_VALIDATION_SYSTEM_PROMPT
    user_prompt = build_task_validation_user_prompt(user_message, final_content, filter_message)

    prompt_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt + "\n\n" + user_prompt},
    ]

    response: LLMResponse = await provider.chat(
        messages=prompt_messages,
        model=model,
    )

    if not response.content:
        logger.warning("任务验收器没有返回内容，跳过自动验收")
        return {}

    try:
        content = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning("任务验收器返回了非 JSON 内容，跳过自动验收：{}", response.content[:200])
        return {}

    if not isinstance(content, dict):
        logger.warning("任务验收器返回的 JSON 不是对象，跳过自动验收：{}", type(content).__name__)
        return {}
    return content
