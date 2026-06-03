"""Session HTTP 响应组装。"""

from typing import Any

from ZBot.session.manager import Session


def display_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block.get("type") == "image_url":
            parts.append("[image]")
    return "\n".join(parts)


def session_message_detail(session: Session) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for index, message in enumerate(session.messages):
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue

        content = display_content(message.get("content"))
        if role == "assistant" and not content and message.get("tool_calls"):
            continue
        if not content:
            continue

        item: dict[str, Any] = {
            "id": f"{session.session_name}-{index}",
            "role": role,
            "content": content,
            "timestamp": message.get("timestamp"),
        }
        tools_used = message.get("tools_used")
        if isinstance(tools_used, list) and tools_used:
            item["tools_used"] = tools_used
        messages.append(item)
    return messages


def session_detail(session: Session) -> dict[str, Any]:
    messages = session_message_detail(session)
    return {
        "name": session.session_name,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "message_count": len(messages),
        "messages": messages,
    }
