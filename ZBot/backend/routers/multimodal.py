"""多模态上传与识别相关路由。"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from loguru import logger

from ZBot.service.agent_run.agent_factory import AgentSetupError
from ZBot.service.agent_run.agent_run_service import AgentEvent
from ZBot.service.agent_run.agent_runner import create_agent_run_service
from ZBot.service.config_service import config_cache
from ZBot.service.utils.file_utils import (
    IMAGE_MIME_TYPES,
    TEXT_MIME_TYPES,
    UNSUPPORTED_FILE_MIME_TYPES,
    decode_text,
    detect_upload_mime,
)

router = APIRouter(
    prefix="/api/multimodal",
    tags=["multimodal"],
)


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
        mime = detect_upload_mime(file.filename, file.content_type, raw_bytes)
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

        if mime in IMAGE_MIME_TYPES:
            encoded_content = base64.b64encode(raw_bytes).decode("utf-8")
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded_content}"},
                }
            )
        elif mime in TEXT_MIME_TYPES:
            content_blocks[0]["text"] += (
                f"\n\n---\n\n上传文本文件：{file.filename or 'unknown'}\n{decode_text(raw_bytes)}"
            )
        elif mime in UNSUPPORTED_FILE_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"当前聊天 provider 尚未启用 {mime} 文件输入适配，"
                    "请先使用图片，或后续接入 Responses/file input 适配层。"
                ),
            )
        else:
            raise HTTPException(status_code=415, detail=f"暂不支持该文件类型：{mime}")

    # 加载配置并创建 service
    config = config_cache.get()
    if config is None:
        raise HTTPException(status_code=500, detail="无法加载配置文件，请先完成 ZBot 配置。")

    events: list[dict[str, Any]] = []

    async def _event_sink(event: AgentEvent) -> None:
        events.append(event.to_dict())

    try:
        service = create_agent_run_service(config)
    except AgentSetupError as exc:
        raise HTTPException(status_code=500, detail={"code": exc.code, "message": exc.message}) from exc

    try:
        await service.start(session_name, event_sink=_event_sink)
        final_content = await service.ask(content_blocks, session_name, event_sink=_event_sink)
    finally:
        await service.close(session_name)

    return {
        "question": question,
        "files_count": len(files),
        "files": file_summaries,
        "answer": final_content,
        "events": events,
        "status": "completed",
    }
