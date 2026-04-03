"""
Agent 工具的基类模块。

定义所有工具必须实现的抽象基类，用于统一工具的接口和行为。
"""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """
    工具抽象基类。

    工具是 Agent 可以调用的能力，例如读取文件、执行命令、调用 API 等。
    所有具体工具都需要继承此类，并实现 name、description、parameters 属性以及 execute 方法。
    """

    # 类型映射表：将 JSON Schema 中的类型名称映射到 Python 类型
    # 用于类型检查和强制转换
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称，用于在函数调用时标识该工具。"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具的描述，告诉 Agent 该工具的用途。"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """
        工具的 JSON Schema 参数定义。

        必须符合 JSON Schema 规范，描述工具所需的参数及其类型、约束等。
        例如：
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "recursive": {"type": "boolean", "default": False}
            },
            "required": ["path"]
        }
        """
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        执行工具的主要逻辑。

        参数：
            **kwargs: 传入的实际参数，应与 parameters 定义的 schema 一致。

        返回：
            字符串形式的结果，将被 Agent 用于后续推理或返回给用户。
        """
        pass

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        根据参数 schema 对传入的参数进行安全类型转换。

        主要用于将字符串形式的输入（如来自 LLM 的文本）转换为正确的 Python 类型。
        此方法会递归处理嵌套的对象和数组。

        参数：
            params: 原始参数字典

        返回：
            类型转换后的参数字典
        """
        schema = self.parameters or {}
        # 仅当根 schema 是对象类型时才进行转换，否则直接返回原值
        if schema.get("type", "object") != "object":
            return params

        return self._cast_object(params, schema)

    def _cast_object(self, obj: Any, schema: dict[str, Any]) -> dict[str, Any]:
        """
        递归地将一个字典对象中的值按照 schema 进行类型转换。

        参数：
            obj: 待转换的对象（预期为字典）
            schema: 当前对象的 JSON Schema

        返回：
            转换后的字典
        """
        if not isinstance(obj, dict):
            return obj

        props = schema.get("properties", {})
        result = {}

        for key, value in obj.items():
            if key in props:
                # 该属性在 schema 中有定义，按 schema 转换
                result[key] = self._cast_value(value, props[key])
            else:
                # 未定义的属性保留原样（不做转换）
                result[key] = value

        return result

    def _cast_value(self, val: Any, schema: dict[str, Any]) -> Any:
        """
        根据单个属性的 schema 转换一个值。

        转换策略：
        - 如果值已经是正确类型，直接返回
        - 对于字符串表示的整数、浮点数、布尔值进行转换
        - 递归处理数组和对象
        - 其他情况返回原值

        参数：
            val: 待转换的值
            schema: 该值的 JSON Schema

        返回：
            转换后的值
        """
        target_type = schema.get("type")

        # 已经是正确类型且不需要进一步转换的情况
        if target_type == "boolean" and isinstance(val, bool):
            return val
        if target_type == "integer" and isinstance(val, int) and not isinstance(val, bool):
            return val
        # 对于 string、number（已是数值类型）等，如果已是目标类型则返回
        if target_type in self._TYPE_MAP and target_type not in ("boolean", "integer", "array", "object"):
            expected = self._TYPE_MAP[target_type]
            if isinstance(val, expected):
                return val

        # 字符串 -> 整数
        if target_type == "integer" and isinstance(val, str):
            try:
                return int(val)
            except ValueError:
                return val

        # 字符串 -> 浮点数/数值
        if target_type == "number" and isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return val

        # 强制转为字符串
        if target_type == "string":
            return val if val is None else str(val)

        # 字符串 -> 布尔值
        if target_type == "boolean" and isinstance(val, str):
            val_lower = val.lower()
            if val_lower in ("true", "1", "yes"):
                return True
            if val_lower in ("false", "0", "no"):
                return False
            return val

        # 数组：递归转换每个元素
        if target_type == "array" and isinstance(val, list):
            item_schema = schema.get("items")
            return [self._cast_value(item, item_schema) for item in val] if item_schema else val

        # 对象：递归转换内部属性
        if target_type == "object" and isinstance(val, dict):
            return self._cast_object(val, schema)

        # 未匹配任何转换规则，返回原值
        return val

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """
        根据 JSON Schema 验证参数的有效性。

        返回错误列表，每个元素是一条错误描述字符串。如果列表为空，则参数有效。

        参数：
            params: 待验证的参数字典

        返回：
            错误列表
        """
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        # 确保根 schema 类型为 object
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        # 将根 schema 标记为 object 后调用递归验证
        return self._validate(params, {**schema, "type": "object"}, "")

    def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        """
        递归验证一个值是否符合给定的 JSON Schema。

        参数：
            val: 要验证的值
            schema: 当前值的 JSON Schema
            path: 当前值在参数对象中的路径（用于错误定位）

        返回：
            错误列表
        """
        t, label = schema.get("type"), path or "parameter"

        # 基本类型检查（类型不匹配时直接返回单项错误）
        if t == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
            return [f"{label} should be integer"]
        if t == "number" and (
            not isinstance(val, self._TYPE_MAP[t]) or isinstance(val, bool)
        ):
            return [f"{label} should be number"]
        if t in self._TYPE_MAP and t not in ("integer", "number") and not isinstance(val, self._TYPE_MAP[t]):
            return [f"{label} should be {t}"]

        errors = []

        # 枚举值检查
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")

        # 数值约束
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")

        # 字符串长度约束
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")

        # 对象：验证必需属性以及每个属性值的有效性
        if t == "object":
            props = schema.get("properties", {})
            # 检查 required 字段是否存在
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {path + '.' + k if path else k}")
            # 递归验证每个存在的属性
            for k, v in val.items():
                if k in props:
                    errors.extend(self._validate(v, props[k], path + "." + k if path else k))

        # 数组：递归验证每个元素
        if t == "array" and "items" in schema:
            for i, item in enumerate(val):
                errors.extend(
                    self._validate(item, schema["items"], f"{path}[{i}]" if path else f"[{i}]")
                )

        return errors

    def to_schema(self) -> dict[str, Any]:
        """
        将工具转换为 OpenAI 函数调用格式的 JSON Schema。

        用于将工具集成到 OpenAI API 的 function calling 中。

        返回：
            符合 OpenAI function 规范的字典
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }