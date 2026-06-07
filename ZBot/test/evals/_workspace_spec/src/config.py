"""用极简自研解析器加载 YAML 配置（不依赖 PyYAML）。"""

from __future__ import annotations

from pathlib import Path


def load_config(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            key = "__list__"
            arr = parent.setdefault(key, [])
            arr.append(_coerce(line[2:].strip()))
        elif ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value == "":
                new: dict = {}
                parent[key] = new
                stack.append((indent, new))
            else:
                parent[key] = _coerce(value)
    return root


def _coerce(value: str):
    if value.lower() in {"true", "yes"}:
        return True
    if value.lower() in {"false", "no"}:
        return False
    if value.lower() in {"null", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value.strip('"').strip("'")