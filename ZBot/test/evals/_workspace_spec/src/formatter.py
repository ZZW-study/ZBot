"""把字典和列表格式化成人类可读的字符串。"""

from __future__ import annotations

from typing import Any


def fmt_table(rows: list[dict], columns: list[str] | None = None) -> str:
    if not rows:
        return ""
    cols = columns or list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    header = " | ".join(c.ljust(widths[c]) for c in cols)
    sep = "-+-".join("-" * widths[c] for c in cols)
    body_lines = []
    for row in rows:
        body_lines.append(" | ".join(str(row.get(c, "")).ljust(widths[c]) for c in cols))
    return "\n".join([header, sep, *body_lines])


def fmt_bullets(items: list[Any]) -> str:
    return "\n".join(f"- {item}" for item in items)


def fmt_kv(pairs: dict[str, Any]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in pairs.items())