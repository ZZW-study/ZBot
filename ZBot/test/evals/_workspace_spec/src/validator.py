"""按一组约束校验用户输入。

注意：故意保留一个除零 bug，供 code_fix 评测任务修复。
函数签名应为 ``safe_divide(numerator, denominator)``，目前当 denominator == 0
时会真的抛出 ZeroDivisionError，应在除法前做零值保护。
"""

from __future__ import annotations

import re
from typing import Any


_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")


def is_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value or ""))


def is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, dict, set)):
        return len(value) > 0
    return True


def safe_divide(numerator: float, denominator: float) -> float:
    """分子除以分母。当前有 bug：分母为 0 时会崩溃。"""
    # BUG：当 denominator == 0 时会真的抛 ZeroDivisionError，应在除法前判零。
    return numerator / denominator


def clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def validate_record(record: dict) -> list[str]:
    errors: list[str] = []
    if not is_non_empty(record.get("name")):
        errors.append("name is required")
    email = record.get("email", "")
    if email and not is_email(email):
        errors.append("email is malformed")
    age = record.get("age")
    if not isinstance(age, int) or age < 0 or age > 150:
        errors.append("age out of range")
    return errors