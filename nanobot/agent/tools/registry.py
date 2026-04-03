# 核心作用：工具注册器 → 统一管理AI所有可用工具（注册、查询、执行、格式转换）
# 简单理解：AI的「工具箱」，所有工具都放这里，AI想用工具必须通过它

from typing import Any

# 导入所有工具的基类（所有工具都继承自Tool）
from nanobot.agent.tools.base import Tool


class ToolRegistry:
    """
    AI代理的工具注册器
    核心功能：
    1. 动态注册/注销工具
    2. 给大模型(LLM)提供标准格式的工具清单
    3. 接收AI指令，执行对应工具
    """

    def __init__(self):
        """初始化工具注册器"""
        # 私有字典：存储所有工具 → key=工具名称(字符串)，value=工具实例对象
        # 例如：{"read_file": ReadFileTool实例, "web_search": WebSearchTool实例}
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """
        注册一个工具到工具箱
        :param tool: 继承自Tool基类的工具实例
        """
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """
        根据工具名称，获取工具实例
        :param name: 工具名称
        :return: 工具实例 或 None（不存在时）
        """
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """
        检查工具箱中是否存在某个工具
        :param name: 工具名称
        :return: 存在返回True，否则False
        """
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """
        【核心函数】将所有工具转换为【大模型兼容的OpenAI格式】
        作用：把工具清单发给AI，告诉AI"我有这些工具可以用"
        :return: 工具定义列表（LLM能识别的JSON格式）
        """
        # 遍历所有工具，调用每个工具的to_schema()方法，生成标准格式
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """
        【核心函数】执行指定工具（AI调用工具的入口）
        :param name: 要执行的工具名称（如 read_file）
        :param params: 工具参数（如 {"path": "test.txt"}）
        :return: 工具执行结果（字符串格式）
        """
        # 错误提示后缀：执行失败时，给AI的建议
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        # 1. 查找工具是否存在
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        try:
            # 2. 类型转换：把AI传的参数，转为工具要求的类型
            params = tool.cast_params(params)
            
            # 3. 参数校验：检查参数是否符合工具要求
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            
            # 4. 【执行工具】调用工具的execute异步方法
            result = await tool.execute(**params)
            
            # 5. 结果处理：如果工具返回错误，追加提示
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        
        # 6. 异常捕获：执行失败时返回错误信息
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """
        属性方法：获取所有已注册的工具名称列表
        :return: 工具名列表，如 ["read_file", "write_file", "web_search"]
        """
        return list(self._tools.keys())

    def __len__(self) -> int:
        """魔术方法：支持 len(registry) 获取工具数量"""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """魔术方法：支持 "read_file" in registry 判断工具是否存在"""
        return name in self._tools
