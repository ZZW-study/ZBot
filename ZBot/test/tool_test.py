# pyright: reportCallIssue=false
"""
==============================================================================
工具层测试文件 —— Tool 基类、ToolRegistry、具体工具
==============================================================================


这个文件测的是什么？
────────────────────

ZBot 的工具系统有三层：

    1. Tool 基类（base.py）
       - 参数类型转换（cast_params）
       - 参数校验（validate_params）
       - Schema 导出（to_schema）
       - 错误格式化（format_tool_error）

    2. ToolRegistry（registry.py）
       - 工具注册与查找
       - 统一执行入口（自动 cast → validate → execute → 错误包装）
       - 从其他 registry 复制工具（给子 agent 用）

    3. 具体工具（filesystem.py, shell.py）
       - ReadFileTool：读取文件
       - WriteFileTool：写入文件
       - EditFileTool：查找替换
       - ListDirTool：列目录
       - ExecTool：执行 shell 命令（含安全拦截）

测试策略：
    - 第 1、2 层用"假工具"测，不依赖文件系统
    - 第 3 层用 tmp_path（pytest 内置临时目录）测真实文件操作
    - ExecTool 用安全命令（echo、dir）测正常流程，用危险命令测拦截


为什么工具测试重要？
────────────────────

工具是 agent 的"手和脚"。如果工具层有 bug：
    - 参数类型错误 → agent 拿到错误结果，继续瞎跑
    - 校验遗漏 → 模型传入非法参数，工具崩溃
    - 安全拦截失效 → rm -rf 穿透到生产环境
    - 错误信息不可读 → 模型看不懂错误，反复重试同一操作


pytest 用法提醒
───────────────

    pytest ZBot/test/tool_test.py -v              # 跑所有工具测试
    pytest ZBot/test/tool_test.py::TestToolCast   # 只跑参数转换测试
    pytest ZBot/test/tool_test.py -v -s           # 详细输出 + print


==============================================================================
下面开始实际的测试代码
==============================================================================
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from ZBot.agent.tools.base import Tool, format_tool_error
from ZBot.agent.tools.registry import ToolRegistry
from ZBot.agent.tools.filesystem import (
    ReadFileTool,
    WriteFileTool,
    EditFileTool,
    ListDirTool,
    _find_match,
)
from ZBot.service.utils.helpers import resolve_path
from ZBot.agent.tools.shell import ExecTool


# =============================================================================
# 测试用的假工具
#
# 说明：
#   Tool 是抽象类，不能直接实例化。
#   我们创建一个最小的子类 FakeTool，用于测试 Tool 基类的方法。
#   它的 parameters 定义了一个简单的 schema，方便测试 cast 和 validate。
# =============================================================================


class FakeTool(Tool):
    """用于测试 Tool 基类方法的假工具。

    定义了一个包含多种参数类型的 schema：
    - name: string（必填）
    - count: integer（可选，有最小值限制）
    - score: number（可选）
    - enabled: boolean（可选）
    - tags: array of string（可选，有最小项数限制）
    """

    @property
    def name(self) -> str:
        return "fake_tool"

    @property
    def description(self) -> str:
        return "用于测试的假工具"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "名称"},
                "count": {
                    "type": "integer",
                    "description": "数量",
                    "minimum": 0,
                    "maximum": 100,
                },
                "score": {"type": "number", "description": "分数"},
                "enabled": {"type": "boolean", "description": "是否启用"},
                "tags": {
                    "type": "array",
                    "description": "标签列表",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return f"executed with {kwargs}"


class SimpleTool(Tool):
    """最简单的工具，只有一个 string 参数。"""

    @property
    def name(self) -> str:
        return "simple_tool"

    @property
    def description(self) -> str:
        return "简单工具"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "消息"},
            },
            "required": ["message"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return kwargs.get("message", "")


class AlwaysFailTool(Tool):
    """总是执行失败的工具，用于测试 ToolRegistry 的错误包装。"""

    @property
    def name(self) -> str:
        return "always_fail"

    @property
    def description(self) -> str:
        return "总是失败的工具"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
            },
            "required": ["input"],
        }

    async def execute(self, **kwargs: Any) -> str:
        raise RuntimeError("模拟执行失败")


class ErrorStringTool(Tool):
    """返回错误字符串的工具（以"错误："开头）。"""

    @property
    def name(self) -> str:
        return "error_string"

    @property
    def description(self) -> str:
        return "返回错误字符串的工具"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
            },
            "required": ["input"],
        }

    async def execute(self, **kwargs: Any) -> str:
        return "错误：文件不存在"


# =============================================================================
# pytest fixture：可复用的测试前置资源
# =============================================================================


@pytest.fixture
def fake_tool() -> FakeTool:
    """创建一个 FakeTool 实例。"""
    return FakeTool()


@pytest.fixture
def simple_tool() -> SimpleTool:
    """创建一个 SimpleTool 实例。"""
    return SimpleTool()


@pytest.fixture
def registry() -> ToolRegistry:
    """创建一个空的 ToolRegistry。"""
    return ToolRegistry()


@pytest.fixture
def registry_with_tools() -> ToolRegistry:
    """创建一个注册了多个工具的 ToolRegistry。"""
    reg = ToolRegistry()
    reg.register(FakeTool())
    reg.register(SimpleTool())
    reg.register(AlwaysFailTool())
    return reg


# =============================================================================
# 第一部分：format_tool_error 测试
#
# format_tool_error 是工具错误格式化的基础函数，
# 所有工具的错误信息都通过它生成。
# =============================================================================


class TestFormatToolError:
    """测试 format_tool_error 函数。"""

    def test_basic_error_message(self):
        """场景：只传必填参数（error + attempted）。

        验证点：
            - 返回的字符串包含错误信息
            - 返回的字符串包含已尝试的操作
        """
        # Arrange & Act
        result = format_tool_error(
            error="文件不存在",
            attempted="读取 /tmp/test.txt",
        )

        # Assert
        assert "文件不存在" in result
        assert "读取 /tmp/test.txt" in result
        assert "错误：" in result
        assert "已尝试：" in result

    def test_all_fields_present(self):
        """场景：传入所有可选参数。

        验证点：
            - 每个字段都出现在结果中
        """
        # Arrange & Act
        result = format_tool_error(
            error="权限不足",
            attempted="写入 /etc/passwd",
            observed="文件权限为 644",
            do_not_repeat="不要再次尝试写入系统文件",
            next_action="改用用户目录下的文件",
        )

        # Assert
        assert "权限不足" in result
        assert "写入 /etc/passwd" in result
        assert "观察结果：文件权限为 644" in result
        assert "不要重复：不要再次尝试写入系统文件" in result
        assert "建议下一步：改用用户目录下的文件" in result

    def test_optional_fields_omitted(self):
        """场景：省略可选字段时，它们不出现在结果中。

        验证点：
            - "观察结果：" 不出现
            - "不要重复：" 不出现
            - "建议下一步：" 不出现
        """
        # Arrange & Act
        result = format_tool_error(
            error="超时",
            attempted="执行 curl",
        )

        # Assert
        assert "观察结果" not in result
        assert "不要重复" not in result
        assert "建议下一步" not in result


# =============================================================================
# 第二部分：Tool.cast_params 测试
#
# cast_params 根据 schema 自动转换参数类型。
# 例如：字符串 "123" → 整数 123，字符串 "true" → 布尔 True。
# =============================================================================


class TestToolCastParams:
    """测试 Tool.cast_params 方法。"""

    def test_string_to_integer(self, fake_tool: FakeTool):
        """场景：传入字符串形式的数字，应转为整数。

        模型返回的 JSON 中数字有时是字符串形式（如 "5"），
        cast_params 应该自动转为 int。
        """
        # Arrange
        params = {"name": "test", "count": "5"}

        # Act
        result = fake_tool.cast_params(params)

        # Assert
        assert result["count"] == 5
        assert isinstance(result["count"], int)

    def test_string_to_number(self, fake_tool: FakeTool):
        """场景：字符串形式的浮点数应转为 float。"""
        # Arrange
        params = {"name": "test", "score": "3.14"}

        # Act
        result = fake_tool.cast_params(params)

        # Assert
        assert result["score"] == 3.14
        assert isinstance(result["score"], float)

    def test_string_to_boolean(self, fake_tool: FakeTool):
        """场景：字符串形式的布尔值应转为 bool。

        支持的真值：true, 1, yes
        支持的假值：false, 0, no
        """
        # Arrange & Act & Assert
        assert fake_tool.cast_params({"name": "x", "enabled": "true"})["enabled"] is True
        assert fake_tool.cast_params({"name": "x", "enabled": "1"})["enabled"] is True
        assert fake_tool.cast_params({"name": "x", "enabled": "yes"})["enabled"] is True
        assert fake_tool.cast_params({"name": "x", "enabled": "false"})["enabled"] is False
        assert fake_tool.cast_params({"name": "x", "enabled": "0"})["enabled"] is False
        assert fake_tool.cast_params({"name": "x", "enabled": "no"})["enabled"] is False

    def test_already_correct_type_unchanged(self, fake_tool: FakeTool):
        """场景：参数已经是正确类型，不做转换。"""
        # Arrange
        params = {"name": "test", "count": 5, "score": 3.14, "enabled": True}

        # Act
        result = fake_tool.cast_params(params)

        # Assert
        assert result["count"] == 5
        assert result["score"] == 3.14
        assert result["enabled"] is True

    def test_unknown_keys_preserved(self, fake_tool: FakeTool):
        """场景：传入 schema 中没有定义的 key，原样保留。

        模型有时会传入额外参数，cast_params 不应该丢弃它们。
        """
        # Arrange
        params = {"name": "test", "unknown_key": "value"}

        # Act
        result = fake_tool.cast_params(params)

        # Assert
        assert result["unknown_key"] == "value"

    def test_none_value_for_string_kept_as_none(self, fake_tool: FakeTool):
        """场景：string 类型参数传入 None，保持 None。

        _cast_value 中 string 类型对 None 做了特殊处理：不转为 "None"。
        """
        # Arrange
        params = {"name": None}

        # Act
        result = fake_tool.cast_params(params)

        # Assert
        assert result["name"] is None

    def test_non_object_schema_returns_original(self):
        """场景：schema 根类型不是 object，直接返回原参数。

        cast_params 只对 object 类型做递归转换。
        """

        # Arrange: 创建一个 schema 根类型为 string 的工具
        class StringSchemaTool(Tool):
            @property
            def name(self) -> str:
                return "str_tool"

            @property
            def description(self) -> str:
                return "desc"

            @property
            def parameters(self) -> dict[str, Any]:
                return {"type": "string"}

            async def execute(self, **kwargs: Any) -> str:
                return ""

        tool = StringSchemaTool()
        params = {"key": "value"}

        # Act
        result = tool.cast_params(params)

        # Assert: 原样返回
        assert result == {"key": "value"}

    def test_array_items_cast(self, fake_tool: FakeTool):
        """场景：array 类型的元素按 items schema 转换。"""
        # Arrange
        params = {"name": "test", "tags": [123, 456]}  # 数字应转为字符串

        # Act
        result = fake_tool.cast_params(params)

        # Assert
        assert result["tags"] == ["123", "456"]

    def test_invalid_integer_string_kept(self, fake_tool: FakeTool):
        """场景：无法转为整数的字符串保持原值。

        "abc" 无法转为 int，应该保持为 "abc"。
        """
        # Arrange
        params = {"name": "test", "count": "abc"}

        # Act
        result = fake_tool.cast_params(params)

        # Assert
        assert result["count"] == "abc"


# =============================================================================
# 第三部分：Tool.validate_params 测试
#
# validate_params 根据 schema 校验参数是否合法。
# 返回错误消息列表，空列表表示通过。
# =============================================================================


class TestToolValidateParams:
    """测试 Tool.validate_params 方法。"""

    def test_valid_params_pass(self, fake_tool: FakeTool):
        """场景：参数完全合法。

        验证点：
            - 返回空列表（无错误）
        """
        # Arrange
        params = {"name": "test", "count": 5}

        # Act
        errors = fake_tool.validate_params(params)

        # Assert
        assert errors == []

    def test_missing_required_field(self, fake_tool: FakeTool):
        """场景：缺少必填字段。

        验证点：
            - 返回的错误列表包含"缺少必填字段"
        """
        # Arrange
        params = {"count": 5}  # 缺少必填的 "name"

        # Act
        errors = fake_tool.validate_params(params)

        # Assert
        assert len(errors) >= 1
        assert any("name" in e for e in errors)

    def test_wrong_type_integer(self, fake_tool: FakeTool):
        """场景：integer 参数传入错误类型。"""
        # Arrange
        params = {"name": "test", "count": "not_a_number"}

        # Act
        errors = fake_tool.validate_params(params)

        # Assert
        assert any("整数" in e for e in errors)

    def test_minimum_constraint(self, fake_tool: FakeTool):
        """场景：integer 参数低于 minimum。

        FakeTool 的 count 字段 minimum=0。
        """
        # Arrange
        params = {"name": "test", "count": -1}

        # Act
        errors = fake_tool.validate_params(params)

        # Assert
        assert any("大于等于" in e for e in errors)

    def test_maximum_constraint(self, fake_tool: FakeTool):
        """场景：integer 参数超过 maximum。

        FakeTool 的 count 字段 maximum=100。
        """
        # Arrange
        params = {"name": "test", "count": 200}

        # Act
        errors = fake_tool.validate_params(params)

        # Assert
        assert any("小于等于" in e for e in errors)

    def test_array_min_items(self, fake_tool: FakeTool):
        """场景：array 参数项数不足。

        FakeTool 的 tags 字段 minItems=1。
        """
        # Arrange
        params = {"name": "test", "tags": []}

        # Act
        errors = fake_tool.validate_params(params)

        # Assert
        assert any("至少需要" in e for e in errors)

    def test_params_not_dict(self, fake_tool: FakeTool):
        """场景：传入非 dict 类型的参数。

        验证点：
            - 返回包含"对象类型"的错误
        """
        # Arrange & Act
        errors = fake_tool.validate_params("not a dict")  # type: ignore

        # Assert
        assert len(errors) >= 1
        assert any("对象" in e for e in errors)

    def test_enum_constraint(self):
        """场景：参数值不在 enum 列表中。"""

        # Arrange: 创建一个有 enum 约束的工具
        class EnumTool(Tool):
            @property
            def name(self) -> str:
                return "enum_tool"

            @property
            def description(self) -> str:
                return "desc"

            @property
            def parameters(self) -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                    },
                    "required": ["level"],
                }

            async def execute(self, **kwargs: Any) -> str:
                return ""

        tool = EnumTool()

        # Act: 传入不在 enum 中的值
        errors = tool.validate_params({"level": "critical"})

        # Assert
        assert any("low" in e or "medium" in e or "high" in e for e in errors)

    def test_string_min_length(self):
        """场景：字符串长度不足。"""

        # Arrange
        class MinLenTool(Tool):
            @property
            def name(self) -> str:
                return "min_len"

            @property
            def description(self) -> str:
                return "desc"

            @property
            def parameters(self) -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "minLength": 3},
                    },
                    "required": ["code"],
                }

            async def execute(self, **kwargs: Any) -> str:
                return ""

        tool = MinLenTool()

        # Act
        errors = tool.validate_params({"code": "ab"})

        # Assert
        assert any("少于" in e for e in errors)

    def test_string_max_length(self):
        """场景：字符串长度超出。"""

        # Arrange
        class MaxLenTool(Tool):
            @property
            def name(self) -> str:
                return "max_len"

            @property
            def description(self) -> str:
                return "desc"

            @property
            def parameters(self) -> dict[str, Any]:
                return {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "maxLength": 5},
                    },
                    "required": ["code"],
                }

            async def execute(self, **kwargs: Any) -> str:
                return ""

        tool = MaxLenTool()

        # Act
        errors = tool.validate_params({"code": "toolongvalue"})

        # Assert
        assert any("超过" in e for e in errors)


# =============================================================================
# 第四部分：Tool.to_schema 测试
#
# to_schema 把工具转换为 OpenAI 函数调用格式的 schema。
# 这个 schema 会发给 LLM，让模型知道有哪些工具可用。
# =============================================================================


class TestToolToSchema:
    """测试 Tool.to_schema 方法。"""

    def test_schema_structure(self, fake_tool: FakeTool):
        """场景：验证 to_schema 输出的结构。

        OpenAI 函数调用格式：
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": {...}
            }
        }
        """
        # Act
        schema = fake_tool.to_schema()

        # Assert
        assert schema["type"] == "function"
        assert "function" in schema
        assert schema["function"]["name"] == "fake_tool"
        assert schema["function"]["description"] == "用于测试的假工具"
        assert "parameters" in schema["function"]
        assert schema["function"]["parameters"]["type"] == "object"

    def test_schema_contains_all_properties(self, fake_tool: FakeTool):
        """场景：schema 的 parameters 包含所有属性定义。"""
        # Act
        schema = fake_tool.to_schema()
        props = schema["function"]["parameters"]["properties"]

        # Assert
        assert "name" in props
        assert "count" in props
        assert "score" in props
        assert "enabled" in props
        assert "tags" in props


# =============================================================================
# 第五部分：ToolRegistry 测试
#
# ToolRegistry 是工具的注册中心，负责：
#   1. 注册和查找工具
#   2. 输出所有工具的 schema（给 LLM 看）
#   3. 统一执行入口（自动 cast → validate → execute → 错误包装）
# =============================================================================


class TestToolRegistry:
    """测试 ToolRegistry 的核心功能。"""

    @pytest.mark.asyncio
    async def test_register_and_execute(self, registry: ToolRegistry):
        """场景：注册工具后能正常执行。

        验证点：
            - 工具注册成功
            - execute 返回工具的执行结果
        """
        # Arrange
        tool = SimpleTool()
        registry.register(tool)

        # Act
        result = await registry.execute("simple_tool", {"message": "hello"})

        # Assert
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, registry: ToolRegistry):
        """场景：调用不存在的工具。

        验证点：
            - 返回错误信息（不是抛异常）
            - 错误信息包含可用工具列表
        """
        # Act
        result = await registry.execute("nonexistent", {"input": "test"})

        # Assert
        assert "找不到工具" in result
        assert "nonexistent" in result

    @pytest.mark.asyncio
    async def test_execute_with_invalid_params(self, registry: ToolRegistry):
        """场景：传入不合法的参数。

        验证点：
            - 返回参数校验错误（不是抛异常）
            - 错误信息包含校验失败的原因
        """
        # Arrange
        registry.register(FakeTool())

        # Act: 缺少必填的 "name" 参数
        result = await registry.execute("fake_tool", {"count": 5})

        # Assert
        assert "参数不合法" in result
        assert "name" in result

    @pytest.mark.asyncio
    async def test_execute_with_type_casting(self, registry: ToolRegistry):
        """场景：参数需要类型转换时，自动完成。

        传入 count="10"（字符串），应自动转为整数 10。
        """
        # Arrange
        registry.register(FakeTool())

        # Act
        result = await registry.execute("fake_tool", {"name": "test", "count": "10"})

        # Assert: 执行成功（没有参数校验错误）
        assert "executed with" in result
        assert "参数不合法" not in result

    @pytest.mark.asyncio
    async def test_execute_tool_exception_caught(self, registry: ToolRegistry):
        """场景：工具执行时抛出异常。

        验证点：
            - 异常被捕获，不会导致程序崩溃
            - 返回包含异常信息的错误消息
        """
        # Arrange
        registry.register(AlwaysFailTool())

        # Act
        result = await registry.execute("always_fail", {"input": "test"})

        # Assert
        assert "异常" in result
        assert "模拟执行失败" in result
        # 重试提示应该存在
        assert "不要" in result

    @pytest.mark.asyncio
    async def test_execute_error_string_appends_retry_hint(self, registry: ToolRegistry):
        """场景：工具返回以"错误："开头的字符串。

        验证点：
            - 原始错误信息保留
            - 附加重试提示
        """
        # Arrange
        registry.register(ErrorStringTool())

        # Act
        result = await registry.execute("error_string", {"input": "test"})

        # Assert
        assert "错误：文件不存在" in result
        assert "不要用相同参数重复调用" in result

    def test_get_definitions(self, registry_with_tools: ToolRegistry):
        """场景：获取所有工具的 schema 列表。

        验证点：
            - 返回的列表长度等于注册的工具数
            - 每个元素都是 OpenAI 函数调用格式
        """
        # Act
        defs = registry_with_tools.get_definitions()

        # Assert
        assert len(defs) == 3
        names = {d["function"]["name"] for d in defs}
        assert names == {"fake_tool", "simple_tool", "always_fail"}

    def test_register_overwrites_same_name(self, registry: ToolRegistry):
        """场景：注册同名工具，后注册的覆盖先注册的。

        这是刻意保留的行为，方便外部注入定制版本。
        """
        # Arrange
        tool1 = SimpleTool()
        tool2 = SimpleTool()
        registry.register(tool1)
        registry.register(tool2)

        # Act
        defs = registry.get_definitions()

        # Assert: 只有一个工具
        assert len(defs) == 1

    @pytest.mark.asyncio
    async def test_register_from_other_registry(self):
        """场景：从另一个 registry 复制工具。

        这是子 agent 复用父 agent MCP 工具的机制。
        """
        # Arrange
        parent = ToolRegistry()
        parent.register(SimpleTool())
        parent.register(FakeTool())
        parent.register(AlwaysFailTool())

        child = ToolRegistry()

        # Act: 只复制 mcp_ 开头的工具（这里没有，所以复制 0 个）
        count = child.register_from(parent, name_prefix="mcp_")

        # Assert
        assert count == 0
        assert len(child.get_definitions()) == 0

        # Act: 复制所有工具
        count = child.register_from(parent)

        # Assert
        assert count == 3
        assert len(child.get_definitions()) == 3

    @pytest.mark.asyncio
    async def test_register_from_with_exclude(self):
        """场景：从另一个 registry 复制工具时排除某些工具。"""
        # Arrange
        parent = ToolRegistry()
        parent.register(SimpleTool())
        parent.register(AlwaysFailTool())

        child = ToolRegistry()

        # Act: 排除 always_fail
        count = child.register_from(parent, exclude_names={"always_fail"})

        # Assert
        assert count == 1
        names = {d["function"]["name"] for d in child.get_definitions()}
        assert names == {"simple_tool"}


# =============================================================================
# 第六部分：文件系统工具测试
#
# 这些工具操作真实文件系统，用 pytest 的 tmp_path fixture
# 创建临时目录，测试结束后自动清理。
# =============================================================================


class TestReadFileTool:
    """测试 ReadFileTool。"""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, tmp_path: Path):
        """场景：读取一个存在的文件。

        验证点：
            - 返回文件内容
            - 内容包含行号前缀
        """
        # Arrange
        test_file = tmp_path / "hello.txt"
        test_file.write_text("第一行\n第二行\n第三行", encoding="utf-8")

        tool = ReadFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path="hello.txt")

        # Assert
        assert "第一行" in result
        assert "第二行" in result
        assert "第三行" in result
        # 应该有行号前缀（如 "1| 第一行"）
        assert "1|" in result

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path: Path):
        """场景：读取不存在的文件。

        验证点：
            - 返回错误信息（不是抛异常）
            - 错误信息包含"不存在"
        """
        # Arrange
        tool = ReadFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path="nonexistent.txt")

        # Assert
        assert "不存在" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_read_with_offset_and_limit(self, tmp_path: Path):
        """场景：使用 offset 和 limit 分页读取。

        验证点：
            - 只返回指定范围的行
        """
        # Arrange: 创建 10 行的文件
        test_file = tmp_path / "lines.txt"
        test_file.write_text(
            "\n".join(f"line {i}" for i in range(1, 11)),
            encoding="utf-8",
        )
        tool = ReadFileTool(workspace=tmp_path)

        # Act: 读取第 3 行开始，最多 2 行
        result = await tool.execute(path="lines.txt", offset=3, limit=2)

        # Assert
        assert "line 3" in result
        assert "line 4" in result
        assert "line 1" not in result
        assert "line 10" not in result

    @pytest.mark.asyncio
    async def test_read_empty_file(self, tmp_path: Path):
        """场景：读取空文件。

        验证点：
            - 返回"空文件"提示
        """
        # Arrange
        test_file = tmp_path / "empty.txt"
        test_file.write_text("", encoding="utf-8")
        tool = ReadFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path="empty.txt")

        # Assert
        assert "空文件" in result

    @pytest.mark.asyncio
    async def test_read_directory_returns_error(self, tmp_path: Path):
        """场景：尝试用 read_file 读取目录。

        验证点：
            - 返回"不是文件"的错误
        """
        # Arrange
        (tmp_path / "subdir").mkdir()
        tool = ReadFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path="subdir")

        # Assert
        assert "不是文件" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_read_offset_beyond_file(self, tmp_path: Path):
        """场景：offset 超出文件总行数。

        验证点：
            - 返回"超出"相关错误
        """
        # Arrange
        test_file = tmp_path / "short.txt"
        test_file.write_text("only one line", encoding="utf-8")
        tool = ReadFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path="short.txt", offset=100)

        # Assert
        assert "超出" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_read_path_outside_workspace(self, tmp_path: Path):
        """场景：尝试读取工作区外的文件。

        验证点：
            - 返回权限错误
        """
        # Arrange
        outside_file = tmp_path.parent / "outside.txt"
        outside_file.write_text("secret", encoding="utf-8")
        tool = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)

        # Act
        result = await tool.execute(path=str(outside_file))

        # Assert
        assert "超出" in result or "权限" in result or "错误" in result

        # Cleanup
        outside_file.unlink(missing_ok=True)


class TestWriteFileTool:
    """测试 WriteFileTool。"""

    @pytest.mark.asyncio
    async def test_write_creates_file(self, tmp_path: Path):
        """场景：写入新文件。

        验证点：
            - 文件被创建
            - 文件内容正确
        """
        # Arrange
        tool = WriteFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path="new_file.txt", content="Hello World")

        # Assert
        assert "成功" in result
        assert (tmp_path / "new_file.txt").exists()
        assert (tmp_path / "new_file.txt").read_text(encoding="utf-8") == "Hello World"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, tmp_path: Path):
        """场景：写入文件时自动创建父目录。

        验证点：
            - 多层父目录被创建
            - 文件内容正确
        """
        # Arrange
        tool = WriteFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(
            path="a/b/c/deep.txt",
            content="deep content",
        )

        # Assert
        assert "成功" in result
        assert (tmp_path / "a" / "b" / "c" / "deep.txt").exists()

    @pytest.mark.asyncio
    async def test_write_overwrites_existing(self, tmp_path: Path):
        """场景：覆盖已存在的文件。

        验证点：
            - 文件内容被替换为新内容
        """
        # Arrange
        test_file = tmp_path / "existing.txt"
        test_file.write_text("old content", encoding="utf-8")
        tool = WriteFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path="existing.txt", content="new content")

        # Assert
        assert "成功" in result
        assert test_file.read_text(encoding="utf-8") == "new content"

    @pytest.mark.asyncio
    async def test_write_empty_content(self, tmp_path: Path):
        """场景：写入空内容。

        验证点：
            - 文件被创建，内容为空
        """
        # Arrange
        tool = WriteFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path="empty.txt", content="")

        # Assert
        assert "成功" in result
        assert (tmp_path / "empty.txt").read_text(encoding="utf-8") == ""


class TestEditFileTool:
    """测试 EditFileTool。"""

    @pytest.mark.asyncio
    async def test_simple_replace(self, tmp_path: Path):
        """场景：简单的查找替换。

        验证点：
            - old_text 被替换为 new_text
        """
        # Arrange
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Hello World", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(
            path="edit.txt",
            old_text="World",
            new_text="Python",
        )

        # Assert
        assert "成功" in result
        assert test_file.read_text(encoding="utf-8") == "Hello Python"

    @pytest.mark.asyncio
    async def test_replace_all(self, tmp_path: Path):
        """场景：替换所有出现的文本。

        验证点：
            - 所有匹配都被替换
        """
        # Arrange
        test_file = tmp_path / "repeat.txt"
        test_file.write_text("aaa bbb aaa bbb aaa", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(
            path="repeat.txt",
            old_text="aaa",
            new_text="ccc",
            replace_all=True,
        )

        # Assert
        assert "成功" in result
        assert test_file.read_text(encoding="utf-8") == "ccc bbb ccc bbb ccc"

    @pytest.mark.asyncio
    async def test_replace_not_found(self, tmp_path: Path):
        """场景：找不到要替换的文本。

        验证点：
            - 返回错误信息（包含 diff 提示）
        """
        # Arrange
        test_file = tmp_path / "no_match.txt"
        test_file.write_text("Hello World", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(
            path="no_match.txt",
            old_text="NonExistent",
            new_text="New",
        )

        # Assert
        assert "找不到" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_replace_multiple_without_replace_all(self, tmp_path: Path):
        """场景：多次出现但未设置 replace_all。

        验证点：
            - 返回警告，要求补充上下文或设置 replace_all
        """
        # Arrange
        test_file = tmp_path / "multi.txt"
        test_file.write_text("abc abc abc", encoding="utf-8")
        tool = EditFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(
            path="multi.txt",
            old_text="abc",
            new_text="xyz",
        )

        # Assert
        assert "出现了" in result or "replace_all" in result

    @pytest.mark.asyncio
    async def test_edit_nonexistent_file(self, tmp_path: Path):
        """场景：编辑不存在的文件。

        验证点：
            - 返回"不存在"错误
        """
        # Arrange
        tool = EditFileTool(workspace=tmp_path)

        # Act
        result = await tool.execute(
            path="ghost.txt",
            old_text="old",
            new_text="new",
        )

        # Assert
        assert "不存在" in result or "错误" in result


class TestListDirTool:
    """测试 ListDirTool。"""

    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path: Path):
        """场景：列出目录内容。

        验证点：
            - 返回的列表包含文件和子目录
            - 子目录有 [DIR] 前缀
            - 文件有 [FILE] 前缀
        """
        # Arrange
        (tmp_path / "file1.txt").write_text("a", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("b", encoding="utf-8")
        (tmp_path / "subdir").mkdir()
        tool = ListDirTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path=str(tmp_path))

        # Assert
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "subdir" in result
        assert "[FILE]" in result
        assert "[DIR]" in result

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, tmp_path: Path):
        """场景：列出空目录。

        验证点：
            - 返回"目录为空"提示
        """
        # Arrange
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        tool = ListDirTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path=str(empty_dir))

        # Assert
        assert "为空" in result

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self, tmp_path: Path):
        """场景：列出不存在的目录。

        验证点：
            - 返回"不存在"错误
        """
        # Arrange
        tool = ListDirTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path=str(tmp_path / "nonexistent"))

        # Assert
        assert "不存在" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_list_ignores_noise_dirs(self, tmp_path: Path):
        """场景：自动忽略噪声目录。

        验证点：
            - .git、__pycache__、.venv 等不出现在结果中
        """
        # Arrange
        (tmp_path / "real_file.txt").write_text("x", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / ".venv").mkdir()
        tool = ListDirTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path=str(tmp_path))

        # Assert
        assert "real_file.txt" in result
        assert ".git" not in result
        assert "__pycache__" not in result
        assert ".venv" not in result

    @pytest.mark.asyncio
    async def test_list_recursive(self, tmp_path: Path):
        """场景：递归列出目录。

        验证点：
            - 子目录下的文件也出现在结果中
            - 路径是相对路径
        """
        # Arrange
        (tmp_path / "file1.txt").write_text("a", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "file2.txt").write_text("b", encoding="utf-8")
        tool = ListDirTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path=str(tmp_path), recursive=True)

        # Assert
        assert "file1.txt" in result
        assert "file2.txt" in result
        # 递归模式下路径是相对路径，不带 [FILE]/[DIR] 前缀
        assert "[FILE]" not in result

    @pytest.mark.asyncio
    async def test_list_path_is_file(self, tmp_path: Path):
        """场景：尝试用 list_dir 列出文件（不是目录）。

        验证点：
            - 返回"不是目录"错误
        """
        # Arrange
        test_file = tmp_path / "file.txt"
        test_file.write_text("content", encoding="utf-8")
        tool = ListDirTool(workspace=tmp_path)

        # Act
        result = await tool.execute(path=str(test_file))

        # Assert
        assert "不是目录" in result or "错误" in result


# =============================================================================
# 第七部分：辅助函数测试
#
# 测试 filesystem.py 中的内部辅助函数。
# =============================================================================


class TestFindMatch:
    """测试 _find_match 函数。"""

    def test_exact_match(self):
        """场景：精确匹配。"""
        # Act
        match, count = _find_match("Hello World", "World")

        # Assert
        assert match == "World"
        assert count == 1

    def test_multiple_matches(self):
        """场景：多次匹配。"""
        # Act
        match, count = _find_match("abc abc abc", "abc")

        # Assert
        assert match == "abc"
        assert count == 3

    def test_no_match(self):
        """场景：无匹配。"""
        # Act
        match, count = _find_match("Hello World", "Python")

        # Assert
        assert match is None
        assert count == 0

    def test_fuzzy_match_ignores_indentation(self):
        """场景：宽松匹配（忽略缩进差异）。

        old_text 的缩进和文件内容不同，但去除空白后应该匹配。
        """
        # Arrange
        content = "  def foo():\n    pass"
        old_text = "def foo():\n    pass"  # 没有前导空格

        # Act
        match, count = _find_match(content, old_text)

        # Assert
        assert match is not None
        assert count == 1


# =============================================================================
# 第八部分：ExecTool 测试
#
# ExecTool 是风险最高的工具，测试重点在安全拦截。
# 正常用 echo/dir 命令测，危险命令测拦截。
# =============================================================================


class TestExecTool:
    """测试 ExecTool。"""

    @pytest.mark.asyncio
    async def test_execute_simple_command(self):
        """场景：执行一个安全的简单命令。

        验证点：
            - 返回命令输出
            - 包含退出码
        """
        # Arrange
        tool = ExecTool()

        # Act: echo 是最安全的命令
        result = await tool.execute(command="echo hello")

        # Assert
        assert "hello" in result
        assert "退出码" in result

    @pytest.mark.asyncio
    async def test_empty_command_rejected(self):
        """场景：空命令。

        验证点：
            - 返回错误信息
        """
        # Arrange
        tool = ExecTool()

        # Act
        result = await tool.execute(command="")

        # Assert
        assert "不能为空" in result or "错误" in result

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked_rm_rf(self):
        """场景：尝试执行 rm -rf。

        验证点：
            - 被安全策略拦截
        """
        # Arrange
        tool = ExecTool()

        # Act
        result = await tool.execute(command="rm -rf /")

        # Assert
        assert "安全策略拦截" in result or "高风险" in result

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked_shutdown(self):
        """场景：尝试执行 shutdown。

        验证点：
            - 被安全策略拦截
        """
        # Arrange
        tool = ExecTool()

        # Act
        result = await tool.execute(command="shutdown -s")

        # Assert
        assert "安全策略拦截" in result or "高风险" in result

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked_format(self):
        """场景：尝试执行 format。

        验证点：
            - 被安全策略拦截
        """
        # Arrange
        tool = ExecTool()

        # Act
        result = await tool.execute(command="format C:")

        # Assert
        assert "安全策略拦截" in result or "高风险" in result

    @pytest.mark.asyncio
    async def test_output_truncation(self):
        """场景：命令输出过长时被截断。

        验证点：
            - 输出被截断到 _MAX_OUTPUT 以内
            - 包含截断提示
        """
        # Arrange
        tool = ExecTool()

        # Act: 生成大量输出（Windows 用 dir /s，Linux 用 find /）
        # 用 Python 生成大量输出更跨平台
        result = await tool.execute(
            command='python -c "print(\'x\' * 20000)"',
        )

        # Assert
        # 输出应该被截断（如果超过 _MAX_OUTPUT）
        # 注意：实际是否截断取决于输出长度
        assert len(result) <= tool._MAX_OUTPUT + 500  # 留一些余量给截断提示

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self):
        """场景：启用工作区限制时，路径穿越被拦截。

        验证点：
            - ../ 被检测到
        """
        # Arrange
        tool = ExecTool(restrict_to_workspace=True, working_dir="/tmp/workspace")

        # Act
        result = await tool.execute(command="cat ../secret.txt")

        # Assert
        assert "路径穿越" in result or "安全策略" in result


# =============================================================================
# 运行方式：
#
# 运行所有工具测试：
#     pytest ZBot/test/tool_test.py -v
#
# 运行某个测试类：
#     pytest ZBot/test/tool_test.py::TestToolCastParams -v
#
# 运行某个具体测试：
#     pytest ZBot/test/tool_test.py::TestToolCastParams::test_string_to_integer -v
#
# 查看详细输出：
#     pytest ZBot/test/tool_test.py -v -s
#
# 运行测试 + 覆盖率：
#     pytest ZBot/test/tool_test.py --cov=ZBot/agent/tools --cov-report=term-missing
# =============================================================================
