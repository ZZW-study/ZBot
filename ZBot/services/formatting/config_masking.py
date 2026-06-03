"""配置相关的纯工具函数。"""

from __future__ import annotations

from typing import Any


def mask_key(key: str) -> str:
    """脱敏 API Key：保留前 4 位 + ****。"""
    if len(key) <= 4:
        return "****"
    return key[:4] + "****"


def is_masked_or_empty_key(value: Any) -> bool:
    """判断前端是否没有提交新的明文 API Key。"""
    if not isinstance(value, str):
        return True
    stripped = value.strip()
    return not stripped or "*" in stripped
