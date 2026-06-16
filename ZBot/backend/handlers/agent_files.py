"""Agent 文件上传处理。"""

import base64
import time
import uuid
from collections import OrderedDict
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

# C3 修复:
#   - MAX_FILE_BYTES: 单文件字节上限(超过直接 413,不让大文件进 RAM)
#   - MAX_FILES_PER_UPLOAD: 一次请求最多几个文件
#   - file_store: 用 OrderedDict 实现的简易 LRU+TTL 替代裸 dict
#     (最多 MAX_FILE_STORE_ENTRIES 个条目,ENTRY_TTL_SECONDS 后过期),
#     防止恶意上传把 RAM 撑爆,旧的 file_id 也会随时间自动失效。
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_FILES_PER_UPLOAD = 10
MAX_FILE_STORE_ENTRIES = 1000
ENTRY_TTL_SECONDS = 3600


class _TtlLruStore:
    """简易 LRU+TTL 缓存,OrderedDict 实现,纯 stdlib。

    get/set 自动驱逐过期条目;
    set 时若 size > maxsize,popitem(last=False) 淘汰最久未用。
    """

    def __init__(self, maxsize: int, ttl_seconds: float) -> None:
        self._data: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl_seconds

    def __setitem__(self, key: str, value: list[dict[str, Any]]) -> None:
        self._data[key] = (time.monotonic(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        entry = self._data.get(key)
        if entry is None:
            return False
        if time.monotonic() - entry[0] > self._ttl:
            self._data.pop(key, None)
            return False
        return True

    def __getitem__(self, key: str) -> list[dict[str, Any]]:
        entry = self._data[key]  # KeyError if missing
        if time.monotonic() - entry[0] > self._ttl:
            self._data.pop(key, None)
            raise KeyError(key)
        self._data.move_to_end(key)
        return entry[1]


file_store: _TtlLruStore = _TtlLruStore(maxsize=MAX_FILE_STORE_ENTRIES, ttl_seconds=ENTRY_TTL_SECONDS)


async def handle_uploaded_files(files: list[UploadFile], *, model: str | None = None) -> dict[str, str]:
    """接收前端上传的文件,并转换为模型可接收的内容块。

    C3 修复:在 read 阶段就检查字节数,超过 MAX_FILE_BYTES 直接 413,
    避免大文件先读进 RAM 再被丢掉。
    """
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"单次最多上传 {MAX_FILES_PER_UPLOAD} 个文件,实际收到 {len(files)} 个",
        )

    content_blocks: list[dict[str, Any]] = []

    for file in files:
        # C3: 用 read(MAX_FILE_BYTES + 1) 检测超限,而不是先 read 全量再判断。
        raw_bytes = await file.read(MAX_FILE_BYTES + 1)
        if len(raw_bytes) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"文件 {file.filename or 'unknown'} 超过 {MAX_FILE_BYTES} 字节上限",
            )
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
            # ZBot 改:litellm Chat Completions 不接受 Responses API 的 file_data 块
            # 改为本地文本提取后作为 text 块发送,扫描件/加密等不可解析的以"提取失败"告知模型。
            from ZBot.services.files.extractors import EXTRACTORS
            extract_fn = EXTRACTORS.get(mime)
            if extract_fn is None:
                raise HTTPException(
                    status_code=415,
                    detail=f"暂不支持该文件类型:{mime}",
                )
            fname = file.filename or "unknown"
            extracted, err = extract_fn(raw_bytes)
            if err:
                content_blocks.append(
                    {
                        "type": "text",
                        "text": f"[文件 {fname} 解析失败: {err}]",
                    }
                )
            else:
                content_blocks.append(
                    {
                        "type": "text",
                        "text": f"[文件 {fname} 的内容]\n{extracted}",
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
