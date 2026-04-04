"""工具注册与调度中心。

`ToolRegistry` 的职责很单纯：
1. 保存所有可被 Agent 调用的工具实例。
2. 输出给模型看的工具 schema。
3. 在真正执行前集中完成参数转换、参数校验和错误包装。

这样 Agent 主循环就不需要重复关心每个工具的细节。
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool


_RETRY_HINT = "\n\n[请先分析上面的报错原因，再尝试另一种处理方式。]"


class ToolRegistry:
    """保存工具实例并提供统一执行入口。"""

    def __init__(self):
        # 内部工具映射：name -> Tool 实例
        # 通过注册（register）注入工具，执行时统一从这里取出实例。
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具。

        同名工具会被后注册的实例覆盖，这是刻意保留的行为，
        方便外部注入定制版本。
        """
        # 直接以工具名覆盖已有实例，允许外部通过同名工具替换默认实现
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名称取回工具实例。"""
        # 返回对应名称的工具实例或 None（调用方需处理 None 情况）
        return self._tools.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        """返回所有工具 schema，供大模型决定是否进行函数调用。"""
        # 将所有工具转换为模型可识别的 schema（name/parameters/description），
        # 这些 schema 会随 messages 一并下发给 LLM，允许模型做函数调用决策。
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """执行指定工具并统一包装错误。"""
        tool = self._tools.get(name)
        if tool is None:
            # 列出可用工具名提示用户（_tools 的迭代默认返回键名）
            available = "、".join(self._tools)
            return f"错误：找不到工具“{name}”。当前可用工具：{available}"

        try:
            # 先把用户/模型传入的原始参数做类型转换（cast）和规范化，
            # 例如把 JSON 数字转换为 int、把字符串解析为期望的子结构等。
            cast_params = tool.cast_params(params)
            # 然后进行语义/格式校验，返回错误列表（若有）
            errors = tool.validate_params(cast_params)
            if errors:
                # 参数不合法时直接返回可读的错误提示，并带上重试建议
                return f"错误：工具“{name}”的参数不合法：{'；'.join(errors)}{_RETRY_HINT}"

            # 调用工具的异步执行函数，执行过程中工具可能抛出异常或返回错误字符串
            result = await tool.execute(**cast_params)
            # 若工具以字符串形式返回错误（以 `错误：` 开头），附加重试提示并返回
            if isinstance(result, str) and result.startswith("错误："):
                return result + _RETRY_HINT
            return result
        except Exception as exc:
            # 捕获执行期异常并统一格式化为错误返回，避免抛到上层导致崩溃
            return f"错误：执行工具“{name}”时发生异常：{exc}{_RETRY_HINT}"

    @property
    def tool_names(self) -> list[str]:
        """返回当前已注册工具名，主要给外层做遍历和上下文注入。"""
        # 返回工具名列表，顺序由 dict 的内部迭代顺序决定（Python 3.7+ 保持插入顺序）
        return list(self._tools)
