"""文件类型检测与文本解码工具函数。"""

from __future__ import annotations

from pathlib import Path

from ZBot.backend.parse import detect_by_magic

IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff"}
UNSUPPORTED_FILE_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/html", "text/xml", "application/json", "text/csv"}


def detect_upload_mime(filename: str | None, content_type: str | None, raw_bytes: bytes) -> str:
    """综合 magic bytes、声明 content_type 和扩展名判断上传文件类型。"""
    magic_mime = detect_by_magic(raw_bytes)
    if magic_mime != "application/octet-stream":
        return magic_mime

    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared

    suffix = Path(filename or "").suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".json": "application/json",
    }.get(suffix, "application/octet-stream")


def decode_text(raw_bytes: bytes, *, max_chars: int = 120_000) -> str:
    """把小型文本文件解码为 UTF-8 文本，失败字符用替换符保留位置。"""
    text = raw_bytes.decode("utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n……（文本过长，已截断）"
