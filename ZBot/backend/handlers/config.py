"""Config HTTP 响应组装。"""

from typing import Any

from ZBot.services.config.schema import Config
from ZBot.services.config.config import resolved_provider_status
from ZBot.services.formatting.config_masking import mask_key


def config_status_payload(config: Config | None) -> dict[str, Any]:
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


def config_payload(config: Config) -> dict[str, Any]:
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


def config_saved_payload(config: Config) -> dict[str, Any]:
    configured, provider_name, reason = resolved_provider_status(config)
    return {
        "ok": True,
        "configured": configured,
        "model": config.model,
        "provider": provider_name,
        "reason": reason,
    }
