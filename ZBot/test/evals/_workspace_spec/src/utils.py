"""fixture 项目里通用的杂项工具函数。"""

from __future__ import annotations

import hashlib
import re


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text))


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."