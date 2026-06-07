"""Agent run / 文件上传 / Follow-up 队列的 API 结构。

事件流采用 OpenAI Responses API 兼容的事件分类:
  - session_meta: 会话/thread 元数据
  - turn_context: turn 切换时的上下文快照
  - event_msg: 应用层事件(task_started/task_complete/user_message/token_count)
  - response_item: 模型原始输出(message/function_call/function_call_output/reasoning)

SSE 事件 payload 形如:
  data: {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "..."}}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# 文件上传
# ---------------------------------------------------------------------------

class FileUploadResponse(Base):
    file_id: str


# ---------------------------------------------------------------------------
# Run 生命周期
# ---------------------------------------------------------------------------

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class RunStartRequest(Base):
    """POST /api/threads/{name}/runs body。"""

    message: str = Field(min_length=1, max_length=32000)
    file_id: Optional[str] = None


class RunResponse(Base):
    """POST /api/threads/{name}/runs 响应(立即返回,run 在后台跑)。"""

    run_id: str
    thread_name: str
    status: RunStatus
    created_at: datetime
    events_url: str
    status_url: str


class TokenUsage(Base):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0


class RunStatusResponse(Base):
    """GET /api/threads/{name}/runs/{run_id} 响应。"""

    run_id: str
    thread_name: str
    status: RunStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    token_usage: Optional[TokenUsage] = None


# ---------------------------------------------------------------------------
# Follow-up 队列(steering)
# ---------------------------------------------------------------------------

class FollowUpCreate(Base):
    message: str = Field(min_length=1, max_length=32000)


class FollowUp(Base):
    follow_up_id: str
    thread_name: str
    message: str
    queued_at: datetime


# ---------------------------------------------------------------------------
# SSE 事件 payload(OpenAI Responses API 兼容)
# ---------------------------------------------------------------------------

class SessionMetaPayload(Base):
    """session_meta 事件:流的开头,描述 thread 元数据。"""

    id: str
    thread_name: str
    cwd: str = ""
    model_provider: str = ""
    cli_version: str = ""
    source: str = "zbot-web"


class TurnContextPayload(Base):
    """turn_context 事件:turn 切换时的上下文快照。"""

    turn_id: str
    thread_name: str
    model_context_window: int = 0


class TaskStartedPayload(Base):
    """event_msg/task_started 事件。"""

    type: Literal["task_started"] = "task_started"
    turn_id: str
    started_at: float
    model_context_window: int
    collaboration_mode_kind: str = "default"


class TaskCompletePayload(Base):
    """event_msg/task_complete 事件。"""

    type: Literal["task_complete"] = "task_complete"
    turn_id: str
    status: RunStatus
    ended_at: float
    final_content: str = ""


class UserMessagePayload(Base):
    """event_msg/user_message 事件(steered=true 表示 follow-up 注入)。"""

    type: Literal["user_message"] = "user_message"
    message: str
    steered: bool = False


class TokenCountPayload(Base):
    """event_msg/token_count 事件。"""

    type: Literal["token_count"] = "token_count"
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


class ErrorPayload(Base):
    """event_msg/error 事件。"""

    type: Literal["error"] = "error"
    message: str
    code: str = ""


EventMsgSubTypes = Union[
    TaskStartedPayload,
    TaskCompletePayload,
    UserMessagePayload,
    TokenCountPayload,
    ErrorPayload,
]


class MessageItemPayload(Base):
    """response_item/message 事件。"""

    type: Literal["message"] = "message"
    role: str
    content: str
    delta: bool


class FunctionCallItemPayload(Base):
    """response_item/function_call 事件。"""

    type: Literal["function_call"] = "function_call"
    call_id: str
    name: str
    arguments: str


class FunctionCallOutputItemPayload(Base):
    """response_item/function_call_output 事件。"""

    type: Literal["function_call_output"] = "function_call_output"
    call_id: str
    output: str


class ReasoningItemPayload(Base):
    """response_item/reasoning 事件。"""

    type: Literal["reasoning"] = "reasoning"
    summary: str = ""


ResponseItemSubTypes = Union[
    MessageItemPayload,
    FunctionCallItemPayload,
    FunctionCallOutputItemPayload,
    ReasoningItemPayload,
]


RunEventType = Literal["session_meta", "turn_context", "event_msg", "response_item"]


class RunEvent(Base):
    """SSE 事件 envelope:与 Codex rollout JSONL 格式兼容。

    顶层 type 区分 4 类,payload 是对应子类型(在 router 层手动按 type 字段判别)。
    """

    type: RunEventType
    payload: dict[str, Any]

    model_config = ConfigDict(extra="allow")
