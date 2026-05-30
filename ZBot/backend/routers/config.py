"""配置管理 REST 路由。

供前端引导页读取 / 写入 ~/.ZBot/config.json，
无需用户在终端手动运行 onboard 命令。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from ZBot.config.loader import save_config
from ZBot.config.schema import Config
from ZBot.service.config_service import (
    PROVIDER_DEFAULTS,
    config_cache,
    merge_config_patch,
    resolved_provider_status,
)
from ZBot.service.utils.config_utils import mask_key
from ZBot.service.utils.helpers import ensure_workspace_dirs

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/status")
async def config_status() -> dict[str, Any]:
    """检测配置是否可用。前端启动时调用此端点决定显示引导页还是聊天界面。"""
    config = config_cache.get()
    if config is None:
        return {"exists": False, "configured": False, "model": "", "provider": ""}

    configured, provider_name, reason = resolved_provider_status(config)
    return {
        "exists": True,
        "configured": configured,
        "model": config.model,
        "provider": provider_name,
        "reason": reason,
    }


@router.get("")
async def get_config() -> dict[str, Any]:
    """返回当前配置（API Key 脱敏）。"""
    config = config_cache.get()
    if config is None:
        raise HTTPException(status_code=404, detail="配置文件不存在或无法解析。")

    data = config.model_dump(by_alias=True)
    configured, provider_name, reason = resolved_provider_status(config)
    data["resolvedProvider"] = provider_name
    data["configured"] = configured
    data["reason"] = reason
    # 脱敏所有 api_key 字段
    providers = data.get("providers", {})
    for _name, prov in providers.items():
        if isinstance(prov, dict) and prov.get("apiKey"):
            prov["apiKey"] = mask_key(prov["apiKey"])
    return data


@router.get("/defaults")
async def provider_defaults() -> dict[str, dict[str, str]]:
    """返回各 provider 的默认 api_base 和模型占位符，供前端预填。"""
    return PROVIDER_DEFAULTS


@router.put("")
async def put_config(body: dict[str, Any]) -> dict[str, Any]:
    """接收前端提交的局部配置，合并当前配置后校验并写盘。"""
    current = config_cache.get() or Config()
    try:
        config = merge_config_patch(current, body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    save_config(config)
    config_cache.invalidate()
    ensure_workspace_dirs(workspace=config.workspace_path)
    configured, provider_name, reason = resolved_provider_status(config)
    return {
        "ok": True,
        "configured": configured,
        "model": config.model,
        "provider": provider_name,
        "reason": reason,
    }
