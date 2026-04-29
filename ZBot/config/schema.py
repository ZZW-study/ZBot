"""
本模块使用 Pydantic 定义 ZBot 的配置结构与默认值，
并通过 `Config` 提供统一的配置加载/校验接口。
"""

from typing import Literal                          # Literal 用于限定变量只能是几个固定值之一
from pathlib import Path                    

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel      # 将下划线命名转为驼峰命名的工具函数
# 继承它，定义结构化数据
# 你写的自定义类继承 BaseModel 后，就变成了严格的结构化数据模型。
# 自动做数据校验
# 不用写一堆 if 判断，自动校验字段类型、必填项、格式（比如邮箱、整数）。
# 自动序列化 / 反序列化
# 轻松把 JSON、字典 转成对象，也能把对象转回字典 / JSON，开发接口、处理数据极方便。
# 极简示例
# # 导入核心类
# from pydantic import BaseModel

# # 自定义数据模型，继承 BaseModel
# class User(BaseModel):
#     name: str  # 必须是字符串
#     age: int   # 必须是整数
#     email: str | None = None  # 可选字段

# # 正确使用
# user = User(name="张三", age=20)
# print(user.dict())  # 转字典输出

# # 错误使用（age 传了字符串）→ 自动报错
# # user = User(name="张三", age="20")

class Base(BaseModel):
    """配置基类"""

    # alias_generator=to_camel 自动将下划线字段转为驼峰别名
    # populate_by_name=True 允许同时用原名和别名赋值
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ProviderConfig(Base):
    """单个 LLM 提供商的配置。
    """
    api_key: str = ""            # API 密钥，默认为空（需在配置文件中填写）
    api_base: str = ""           # API 地址


class ProvidersConfig(Base):
    """所有 LLM 提供商的集合配置。
    """
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenRouter 网关
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)    # DeepSeek
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)   # 阿里通义千问
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig) # 硅基流动


class WebSearchConfig(Base):
    """网页搜索配置（bocha Search API）。"""
    api_key: str = ""             # 搜索 API 密钥
    max_results: int = 5          # 最多返回几条搜索结果


class WebToolsConfig(Base):
    """网页工具配置。

    包含网络搜索配置和 HTTP 代理配置。
    """
    proxy: str | None = None                                          # HTTP 代理地址
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)  # 搜索配置


class ExecToolConfig(Base):
    """Shell 命令执行工具配置,用于配置 AI 执行系统命令时的参数。
    """
    timeout: int = 60        # 命令执行超时时间（秒）


class MCPServerConfig(Base):
    """MCP 服务器连接配置,此配置定义了如何连接 MCP 服务器。
    """
    type: Literal["stdio", "sse", "streamableHttp"] | None = None    # 连接类型
    command: str = ""                                                # 启动命令（stdio 模式），如 "python"、"node"、"uvx"
    args: list[str] = Field(default_factory=list)                    # 命令参数，与 command 配合使用，示例：command="python", args=["-m", "mcp_server"]，实际执行：python -m mcp_server                                                                                                     
    env: dict[str, str] = Field(default_factory=dict)                # 环境变量
    url: str = ""                                                    # 服务器 URL（sse/http 模式）
    headers: dict[str, str] = Field(default_factory=dict)            # HTTP 请求头
    tool_timeout: int = 30  # 工具调用超时时间（秒）

class ToolsConfig(Base):
    """所有工具的全局配置。
    汇总了网页工具、命令执行工具、工作区限制和 MCP 服务器的配置。
    """
    web: WebToolsConfig = Field(default_factory=WebToolsConfig)             # 网页工具配置
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)            # 命令执行配置
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)   # MCP 服务器字典
    restrict_to_workspace: bool = False                                     # 是否限制工具只访问工作区内的文件


class Config(BaseModel):
    """ZBot 根配置。
    这是整个系统的核心配置类，汇总了所有配置项。
    """
    # Agent 默认配置
    workspace: str = "~/.ZBot/workspace"        # 工作区路径
    model: str = ""                             # 使用的模型名称
    provider: str = "auto"                      # LLM 提供商
    max_tokens: int = 4096                      # 模型最大输出 token 数，1 token ≈ 0.5~0.8 个中文字符
    temperature: float = 0.1                    # 采样温度（越低越确定，越高越随机）
    max_tool_iterations: int = 50               # 工具调用最大迭代次数
    memory_window: int = 25                     # 记忆窗口大小（保留多少条历史消息）
    reasoning_effort: str | None = None         # 推理强度参数

    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)  # 所有 LLM 提供商
    tools: ToolsConfig = Field(default_factory=ToolsConfig)              # 所有工具配置

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, v: float) -> float:
        if not 0.0 <= v <= 2.0:
            raise ValueError("temperature 必须在 0.0 ~ 2.0 之间")
        return v

    @field_validator("max_tokens", "memory_window", "max_tool_iterations")
    @classmethod
    def _validate_positive_int(cls, v: int) -> int:
        if v < 1:
            raise ValueError("值必须 >= 1")
        return v

    @property
    def workspace_path(self) -> Path:
        """将工作区路径中的 ~ 展开为实际家目录后返回。"""
        return Path(self.workspace).expanduser()

    def get_provider(
        self,
        model: str | None = None,
    ) -> tuple[ProviderConfig | None, str | None, bool | None]:
        """获取匹配的 LLM 提供商配置。
        根据传入的模型名称，查找对应的提供商配置,看到底注册表支不支持。
        返回：
            (ProviderConfig 实例, 提供商名称,是否是网关) 或 (None, None) 表示未匹配到
        """
        from ZBot.providers.registry import PROVIDERS, find_by_model, find_gateway  # 导入提供商注册表

        # 优先使用强制指定的提供商
        if self.provider != "auto":
            forced_spec = next((spec for spec in PROVIDERS if spec.name == self.provider), None)
            forced_config = getattr(self.providers, self.provider, None)
            if forced_spec and forced_config:
                return forced_config, forced_spec.name, forced_spec.is_gateway
            return None, None, None

        model = model or self.model
        if not model:
            return None, None, None

        # 提取模型前缀（如 "openrouter/anthropic/claude" → "openrouter"）
        model_prefix = model.split("/", 1)[0] if model else ""
        gateway_spec = find_gateway(model_prefix)
        if gateway_spec:
            gateway_config = getattr(self.providers, gateway_spec.name, None)
            return (gateway_config, gateway_spec.name, True) if gateway_config else (None, None, None)

        std_spec = find_by_model(model)
        if std_spec:
            std_config = getattr(self.providers, std_spec.name, None)
            return (std_config, std_spec.name, False) if std_config else (None, None, None)

        return None, None, None  # 未匹配到任何提供商
