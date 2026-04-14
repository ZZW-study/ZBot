"""配置文件加载与保存工具。"""

from __future__ import annotations              # 启用未来版本的类型注解特性
import json  
from pathlib import Path  
from typing import Any  
from pydantic import ValidationError            # 用于捕获 Pydantic 验证错误
from ZBot.config.paths import get_path_config   # 获取配置文件路径
from ZBot.config.schema import Config           # 配置模型定义


def _normalize_config_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    用 `Config` 对配置字典做一次字段标准化。
    """
    return Config.model_validate(data).model_dump(
        by_alias=False,               # 使用字段名而非别名（确保一致性）
    )


def load_config(config_path: Path | None = None) -> Config:
    """
    从磁盘文件中加载配置，若配置缺失，可以model_validate可以补全。
    """
    # 确定配置文件路径
    path = config_path or get_path_config()

    # ========== 读取磁盘配置 ==========
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)                # 从 JSON 格式的文件中读取数据
        if isinstance(data, dict):
            # 标准化配置数据（应用 Pydantic 验证和转换）
            file_data = _normalize_config_data(data)
        else:
            raise ValueError(f"警告：配置文件 {path} 的内容必须是 JSON 格式，请重新设置。")
    except (json.JSONDecodeError, OSError, ValidationError, ValueError) as exc:
        print(f"警告：读取配置文件 {path} 失败：{exc}")
        print("无法解析的配置项将回退到默认值。")

    # ========== 最终验证 ==========
    # 通过 Pydantic 模型进行完整验证，包括类型检查、约束验证等
    return Config.model_validate(file_data)


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    把配置对象写回磁盘。
    """
    from ZBot.utils.helpers import ensure_dir

    # 确定配置文件路径
    path = config_path or get_path_config()
    ensure_dir(path.parent)
    
    # 将 Config 对象转换为字典（使用字段别名，如 camelCase）
    data = config.model_dump(by_alias=True)
    # 写入 JSON 文件（格式化缩进，支持中文）
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
