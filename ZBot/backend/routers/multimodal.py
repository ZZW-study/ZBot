"""多模态上传与识别相关路由。"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from loguru import logger

from ZBot.backend.parse import detect_by_magic
from ZBot.config.loader import load_config
from ZBot.config.schema import Config
from ZBot.service.agent_run.agent_factory import AgentSetupError, create_agent_bundle
from ZBot.service.agent_run.agent_run_service import AgentEvent, AgentRunService

# ---------------------------------------------------------------------------
# 配置缓存：避免每次 HTTP 请求都读磁盘
# ---------------------------------------------------------------------------
_CONFIG_TTL_SECONDS = 30
_cached_config: Config | None = None
_config_cached_at: float = 0.0

router = APIRouter(
    prefix="/api/multimodal",
    tags=["multimodal"],
)

_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff"}
_UNSUPPORTED_FILE_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/html", "text/xml", "application/json", "text/csv"}


@router.post("/ask")
async def ask_with_files(
    files: list[UploadFile] = File(...),
    question: str = Form("用户没有任何输入的问题，请你根据上传的文件内容进行回答"),
    session_name: str = Form("default"),
) -> dict[str, Any]:
    """接收上传文件并通过 AgentRunService 调用模型完成一次多模态分析。"""
    if not files:
        raise HTTPException(status_code=400, detail="至少需要上传一个文件。")

    content_blocks: list[dict[str, Any]] = [{"type": "text", "text": question}]
    file_summaries: list[dict[str, Any]] = []

    for file in files:
        raw_bytes = await file.read()
        mime = _detect_upload_mime(file, raw_bytes)
        logger.info("文件 {} 的 MIME 类型检测结果: {}", file.filename, mime)
        if mime == "application/octet-stream":
            raise HTTPException(status_code=415, detail=f"无法识别文件类型：{file.filename or 'unknown'}")

        file_summaries.append(
            {
                "filename": file.filename,
                "mime": mime,
                "size_bytes": len(raw_bytes),
            }
        )

        if mime in _IMAGE_MIME_TYPES:
            encoded_content = base64.b64encode(raw_bytes).decode("utf-8")
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded_content}"},
                }
            )
        elif mime in _TEXT_MIME_TYPES:
            content_blocks[0]["text"] += (
                f"\n\n---\n\n上传文本文件：{file.filename or 'unknown'}\n"
                f"{_decode_text(raw_bytes)}"
            )
        
        elif mime in _UNSUPPORTED_FILE_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"当前聊天 provider 尚未启用 {mime} 文件输入适配，"
                    "请先使用图片，或后续接入 Responses/file input 适配层。"
                ),
            )
        else:
            raise HTTPException(status_code=415, detail=f"暂不支持该文件类型：{mime}")

    events: list[dict[str, Any]] = []
    final_content = await _run_multimodal_agent(content_blocks, session_name, events)

    return {
        "question": question,
        "files_count": len(files),
        "files": file_summaries,
        "answer": final_content,
        "events": events,
        "status": "completed",
    }


def _detect_upload_mime(file: UploadFile, raw_bytes: bytes) -> str:
    """综合 magic bytes、声明 content_type 和扩展名判断上传文件类型。"""
    magic_mime = detect_by_magic(raw_bytes)
    if magic_mime != "application/octet-stream":
        return magic_mime

    declared = (file.content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared

    suffix = Path(file.filename or "").suffix.lower()
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


def _decode_text(raw_bytes: bytes) -> str:
    """把小型文本文件解码为 UTF-8 文本，失败字符用替换符保留位置。"""
    text = raw_bytes.decode("utf-8", errors="replace")
    max_chars = 120_000
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n……（文本过长，已截断）"


def _get_config() -> Config | None:
    """带 TTL 缓存的配置加载，避免每个 HTTP 请求都读磁盘。"""
    global _cached_config, _config_cached_at
    now = time.monotonic()
    if _cached_config is not None and now - _config_cached_at < _CONFIG_TTL_SECONDS:
        return _cached_config
    _cached_config = load_config()
    _config_cached_at = now
    return _cached_config


async def _run_multimodal_agent(
    content_blocks: list[dict[str, Any]],
    session_name: str,
    events: list[dict[str, Any]],
) -> str:
    """创建一次 HTTP 请求级 service，执行多模态消息并清理资源。"""
    config = _get_config()
    if config is None:
        raise HTTPException(status_code=500, detail="无法加载配置文件，请先完成 ZBot 配置。")

    async def _event_sink(event: AgentEvent) -> None:
        """收集本次 HTTP 请求中的结构化事件，便于前端调试展示。"""
        events.append(event.to_dict())

    try:
        service = AgentRunService(create_agent_bundle(config))
    except AgentSetupError as exc:
        raise HTTPException(status_code=500, detail={"code": exc.code, "message": exc.message}) from exc

    try:
        await service.start(session_name, event_sink=_event_sink)
        return await service.ask(content_blocks, session_name, event_sink=_event_sink)
    finally:
        await service.close(session_name)
