"""鉴权相关工具：密码哈希、令牌签发、权限检查。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected: str) -> bool:
    _, actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected)


def issue_token(user_id: str, ttl_seconds: int = 3600) -> str:
    seed = f"{user_id}:{int(time.time()) // ttl_seconds}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def has_permission(role: str, action: str) -> bool:
    matrix: dict[str, set[str]] = {
        "admin": {"read", "write", "delete", "manage"},
        "editor": {"read", "write"},
        "viewer": {"read"},
    }
    allowed = matrix.get(role, set())
    return action in allowed