"""POST /api/agent/files:接收文件上传,转 content blocks,返回 file_id。"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from ZBot.backend.handlers.agent_files import handle_uploaded_files, MAX_FILES_PER_UPLOAD


router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/files", status_code=status.HTTP_201_CREATED)
async def upload_files(
    files: list[UploadFile] = File(...),
    # ZBot 改:前端传当前选中的 model,服务端在多模态能力不足时直接 400,
    # 避免坏请求打到 LLM 触发 litellm 验证错误。Form 字段与 files 同请求体。
    model: str | None = Form(default=None),
) -> dict[str, str]:
    # C3: 在路由层先 reject 空文件列表和过多样本,
    # 避免进入 handler 后再 4xx(用户体验差)。
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"单次最多上传 {MAX_FILES_PER_UPLOAD} 个文件,实际收到 {len(files)} 个",
        )
    return await handle_uploaded_files(files, model=model)
