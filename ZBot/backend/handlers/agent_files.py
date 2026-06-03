"""Agent 文件上传处理。"""

import base64
import uuid
from typing import Any

from fastapi import HTTPException, UploadFile
from loguru import logger

from ZBot.services.files.upload import (
    IMAGE_MIME_TYPES,
    TEXT_MIME_TYPES,
    UNSUPPORTED_FILE_MIME_TYPES,
    decode_text,
    detect_upload_mime,
)

file_store: dict[str, list[dict[str, Any]]] = {}


async def handle_uploaded_files(files: list[UploadFile]) -> dict[str, str]:
    """接收前端上传的文件，并转换为模型可接收的内容块。"""

    content_blocks: list[dict[str, Any]] = []

    for file in files:
        raw_bytes = await file.read()
        mime = detect_upload_mime(file.filename, file.content_type, raw_bytes)

        logger.info("文件 {} 的 MIME 类型检测结果: {}", file.filename, mime)

        if mime == "application/octet-stream":
            raise HTTPException(
                status_code=415,
                detail=f"无法识别文件类型：{file.filename or 'unknown'}",
            )

        if mime in IMAGE_MIME_TYPES:
            image_encoded_content = base64.b64encode(raw_bytes).decode("utf-8")
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{image_encoded_content}",
                    },
                }
            )

        elif mime in TEXT_MIME_TYPES:
            content_blocks.append(
                {
                    "type": "text",
                    "text": decode_text(raw_bytes),
                }
            )

        elif mime in UNSUPPORTED_FILE_MIME_TYPES:
            file_encoded_content = base64.b64encode(raw_bytes).decode("utf-8")
            content_blocks.append(
                {
                    "type": "file",
                    "file": {
                        "file_data": f"data:{mime};base64,{file_encoded_content}",
                    },
                }
            )

        else:
            raise HTTPException(
                status_code=415,
                detail=f"暂不支持该文件类型：{mime}",
            )

    file_id = str(uuid.uuid4())
    file_store[file_id] = content_blocks

    return {"file_id": file_id}
