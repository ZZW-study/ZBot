"""Agent WebSocket harness 路由。"""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile, WebSocket

from ZBot.backend.handlers.agent_files import handle_uploaded_files
from ZBot.backend.handlers.agent_ws import handle_agent_websocket
from ZBot.backend.handlers.sessions import session_detail as _session_detail
from ZBot.backend.routers.session_name import get_session_detail


router = APIRouter(prefix="/api/agent", tags=["agent"])

# **表单数据**就是一组“字段名 = 值”的数据，类似网页填表：
# question = "总结这个文件"
# session_name = "default"
# files = 上传的 PDF 文件
# 它也有结构，但它不是 JSON 对象那种“结构体请求体”。
# 你的接口要同时传**文件 + 文字**，前端通常会这样组织：
# const data = new FormData()
# data.append("files", file)
# data.append("question", "总结这个文件")
# data.append("session_name", "default")

# 后端对应接收：
# async def ask_with_files(
#     files: list[UploadFile] = File(...),  # 接文件
#     question: str = Form("默认问题"),       # 接表单里的文字
#     session_name: str = Form("default"),   # 接表单里的文字
# ):

# 如果只传普通结构化数据，不上传文件，一般会写成 JSON：
# {
#   "question": "总结这个文件",
#   "session_name": "default"
# }

# 后端可能用一个模型接收：
# class AskRequest(BaseModel):
#     question: str
#     session_name: str
# 核心区别：
# JSON / 结构体：适合传普通数据
# Form + File：适合同时传文字和文件
# 所以这里用 `Form`，是因为它要和 `File(...)` 一起接收上传内容。
# -----------------------------------------------------------------------------
# WebSocket 实现原理说明：
#
# WebSocket 本质上是一种基于 TCP 的通信协议。
#
# 前端最开始会发送一次 HTTP 请求，并携带 Upgrade: websocket 请求头。
# 后端执行 await websocket.accept() 后，完成协议升级：
# 此后这条 TCP 连接不再按照普通 HTTP 的“请求一次、响应一次”工作，
# 而是按照 WebSocket 协议传输一帧一帧的消息数据。
#
# -----------------------------------------------------------------------------
#    前端通过 WebSocket 告诉后端“开始”或“停止”；
#    后端通过 WebSocket 持续告诉前端“处理到哪一步”和“生成了什么内容”。
#    该函数不是“前端不停请求、后端不停响应”。就是后端可以在接受前端命令后，可以一直向前端发信息。
#
#    它的底层过程是：
#        一次 HTTP 握手升级为 WebSocket
#        -> 在同一条 TCP 连接上双向传输 WebSocket 数据帧
#        -> asyncio 事件循环并发管理接收命令、执行 Agent、发送事件
#        -> queue 负责在 Agent 执行逻辑与网络发送逻辑之间传递事件。
# -----------------------------------------------------------------------------
@router.post("/have_files")
async def handle_files(
    files: list[UploadFile] = File(...),
) -> dict[str, str]:
    """接收前端上传的文件，并转换为模型可接收的内容块。"""
    return await handle_uploaded_files(files)


@router.websocket("/ws")
async def agent_websocket(
    websocket: WebSocket,
) -> None:
    """
    接收前端命令，并向前端实时推送 Agent 运行事件。
    同一个接口地址 ≠ 同一条 WebSocket 连接,后端就会分别执行一份 agent_websocket() 函数实例,每个实例负责一个 WebSocket 连接，互相独立。
    """
    await handle_agent_websocket(websocket)
