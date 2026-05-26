"""配置管理 REST 路由。

供前端引导页读取 / 写入 ~/.ZBot/config.json，
无需用户在终端手动运行 onboard 命令。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from ZBot.config.loader import load_config, save_config
from ZBot.config.schema import Config
from ZBot.service.utils.helpers import ensure_workspace_dirs

router = APIRouter(prefix="/api/config", tags=["config"])

# 各 provider 的默认 API Base，方便前端预填
_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_base": "https://api.deepseek.com/v1",
        "model_placeholder": "deepseek-chat",
    },
    "openrouter": {
        "api_base": "https://openrouter.ai/api/v1",
        "model_placeholder": "openrouter/anthropic/claude-sonnet-4",
    },
    "dashscope": {
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_placeholder": "qwen-plus",
    },
    "siliconflow": {
        "api_base": "https://api.siliconflow.cn/v1",
        "model_placeholder": "deepseek-ai/DeepSeek-V3",
    },
}


def _mask_key(key: str) -> str:
    """脱敏 API Key：保留前 4 位 + ****。"""
    if len(key) <= 4:
        return "****"
    return key[:4] + "****"


def _is_masked_or_empty_key(value: Any) -> bool:
    """判断前端是否没有提交新的明文 API Key。"""
    if not isinstance(value, str):
        return True
    stripped = value.strip()
    return not stripped or "*" in stripped


def _merge_config_patch(current: Config, patch: dict[str, Any]) -> Config:
    """把前端局部配置合并进当前配置，避免覆盖未展示的高级配置。"""
    data = current.model_dump(by_alias=True)

    for key, value in patch.items():
        if key == "providers":
            continue
        data[key] = value

    incoming_providers = patch.get("providers")
    if isinstance(incoming_providers, dict):
        providers = data.setdefault("providers", {})
        for provider_name, provider_patch in incoming_providers.items():
            if not isinstance(provider_patch, dict):
                continue
            existing = providers.setdefault(provider_name, {})
            for key, value in provider_patch.items():
                if key == "apiKey" and _is_masked_or_empty_key(value):
                    continue
                existing[key] = value

    return Config.model_validate(data)


def _resolved_provider_status(config: Config) -> tuple[bool, str, str]:
    """按当前 model/provider 解析实际使用的 provider，并判断关键字段是否齐全。"""
    provider_config, provider_name, _is_gateway = config.get_provider(config.model)
    if not config.model or not provider_config or not provider_name:
        return False, provider_name or config.provider, "未能按当前模型匹配到 provider。"
    if not provider_config.api_key:
        return False, provider_name, f"{provider_name} 缺少 API Key。"
    if not provider_config.api_base:
        return False, provider_name, f"{provider_name} 缺少 API Base URL。"
    return True, provider_name, ""


@router.get("/status")
async def config_status() -> dict[str, Any]:
    """检测配置是否可用。前端启动时调用此端点决定显示引导页还是聊天界面。"""
    config = load_config()
    if config is None:
        return {"configured": False, "model": "", "provider": ""}

    configured, provider_name, reason = _resolved_provider_status(config)
    return {
        "configured": configured,
        "model": config.model,
        "provider": provider_name,
        "reason": reason,
    }


@router.get("")
async def get_config() -> dict[str, Any]:
    """返回当前配置（API Key 脱敏）。"""
    config = load_config()
    if config is None:
        raise HTTPException(status_code=404, detail="配置文件不存在或无法解析。")

    data = config.model_dump(by_alias=True)
    configured, provider_name, reason = _resolved_provider_status(config)
    data["resolvedProvider"] = provider_name
    data["configured"] = configured
    data["reason"] = reason
    # 脱敏所有 api_key 字段
    providers = data.get("providers", {})
    for _name, prov in providers.items():
        if isinstance(prov, dict) and prov.get("apiKey"):
            prov["apiKey"] = _mask_key(prov["apiKey"])
    return data


@router.get("/defaults")
async def provider_defaults() -> dict[str, dict[str, str]]:
    """返回各 provider 的默认 api_base 和模型占位符，供前端预填。"""
    return _PROVIDER_DEFAULTS


@router.put("")
async def put_config(body: dict[str, Any]) -> dict[str, Any]:
    """接收前端提交的局部配置，合并当前配置后校验并写盘。"""
    current = load_config() or Config()
    try:
        config = _merge_config_patch(current, body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    save_config(config)
    ensure_workspace_dirs(workspace=config.workspace_path)
    configured, provider_name, reason = _resolved_provider_status(config)
    return {
        "ok": True,
        "configured": configured,
        "model": config.model,
        "provider": provider_name,
        "reason": reason,
    }
