"""文件处理工具。"""

from ZBot.services.files.mime import detect_by_magic
from ZBot.services.files.upload import (
    IMAGE_MIME_TYPES,
    TEXT_MIME_TYPES,
    UNSUPPORTED_FILE_MIME_TYPES,
    decode_text,
    detect_upload_mime,
)

__all__ = [
    "IMAGE_MIME_TYPES",
    "TEXT_MIME_TYPES",
    "UNSUPPORTED_FILE_MIME_TYPES",
    "decode_text",
    "detect_by_magic",
    "detect_upload_mime",
]
