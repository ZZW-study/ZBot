"""配置文件加载与保存工具。

这个模块负责把 nanobot 的配置来源统一收口到一处：
1. 先读取磁盘上的 `config.json`。
2. 再叠加 `NANOBOT_*` 环境变量覆盖。
3. 最后交给 Pydantic 做一次标准化校验。

这样上层模块只需要调用 `load_config()`，无需分别处理磁盘、环境变量和默认值。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from nanobot.config.schema import Config

# 测试或脚本场景下允许临时改写配置文件路径，便于隔离不同运行环境。
_current_config_path: Path | None = None


def get_path_config() -> Path:
    """返回当前生效的配置文件路径。"""
    if _current_config_path is not None:
        return _current_config_path
    return Path.home() / ".nanobot" / "config.json"


def _coerce_env_value(raw: str) -> Any:
    """尽量把环境变量值解析为 JSON；解析失败时保留原始字符串。

    例如：
    - `"true"` -> `True`
    - `"123"` -> `123`
    - `"["a"]"` -> `["a"]`
    - `"abc"` -> `"abc"`
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个字典，并返回新结果。

    `override` 中的值优先级更高；当同名字段两边都是字典时，继续向下合并。
    """
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _load_env_overrides() -> dict[str, Any]:
    """把 `NANOBOT_*` 环境变量转换成嵌套配置字典。

    命名规则示例：
    `NANOBOT_AGENTS__DEFAULTS__MODEL=qwen-plus`
    会被转换成：
    `{"agents": {"defaults": {"model": "qwen-plus"}}}`
    """
    prefix = "NANOBOT_"
    overrides: dict[str, Any] = {}

    for key, raw_value in os.environ.items():
        if not key.startswith(prefix):
            continue

        parts = [part.strip().lower() for part in key[len(prefix) :].split("__") if part.strip()]
        if not parts:
            continue

        node = overrides
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child

        node[parts[-1]] = _coerce_env_value(raw_value)

    return overrides


def _normalize_config_data(data: dict[str, Any], *, exclude_unset: bool) -> dict[str, Any]:
    """用 `Config` 对配置字典做一次字段标准化。

    这样无论输入里使用驼峰键还是下划线键，最终都会被统一为模型字段名，
    后面的合并逻辑也就不需要关心别名差异。
    """
    return Config.model_validate(data).model_dump(
        by_alias=False,
        exclude_unset=exclude_unset,
    )


def load_config(config_path: Path | None = None) -> Config:
    """加载配置。

    加载顺序固定为：
    1. 磁盘配置。
    2. 环境变量覆盖。
    3. Pydantic 最终校验与默认值补全。
    """
    path = config_path or get_path_config()
    file_data: dict[str, Any] = {}

    if path.exists():
        try:
            with open(path, encoding="utf-8") as file:
                loaded = json.load(file)
            if isinstance(loaded, dict):
                file_data = _normalize_config_data(loaded, exclude_unset=False)
            else:
                print(f"警告：配置文件 {path} 的根节点必须是 JSON 对象，已改用默认配置。")
        except (json.JSONDecodeError, OSError, ValidationError, ValueError) as exc:
            print(f"警告：读取配置文件 {path} 失败：{exc}")
            print("无法解析的配置项将回退到默认值。")

    env_overrides = _normalize_config_data(_load_env_overrides(), exclude_unset=True)
    merged = _deep_merge(file_data, env_overrides)
    return Config.model_validate(merged)


def save_config(config: Config, config_path: Path | None = None) -> None:
    """把配置对象写回磁盘。"""
    path = config_path or get_path_config()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(by_alias=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
