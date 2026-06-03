"""Session API 请求结构。"""

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    name: str


class SessionRenameRequest(BaseModel):
    name: str
