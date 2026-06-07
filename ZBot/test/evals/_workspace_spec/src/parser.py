"""fixture 项目用的轻量行式配置解析器。"""

from __future__ import annotations

import json
import re
from typing import Any


_KV_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(?P<value>.+?)\s*$")


def parse_kv_lines(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _KV_RE.match(line)
        if not match:
            continue
        result[match.group("key")] = match.group("value")
    return result


def parse_json_safe(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {"value": data}


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1]
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections