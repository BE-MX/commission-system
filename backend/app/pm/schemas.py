"""PM Hub Pydantic schemas（请求体校验）。"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class EntryRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class MaterialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=1024)
    category: Optional[str] = Field(default="其他", max_length=64)
    importance: Optional[str] = Field(default="important", max_length=16)
    phase: Optional[int] = None
    delivery_type: Optional[str] = Field(default="file", max_length=16)
    external_url: Optional[str] = Field(default=None, max_length=512)
    delivery_remark: Optional[str] = Field(default=None, max_length=512)
    owner: Optional[str] = Field(default=None, max_length=64)


class MaterialUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = Field(default=None, max_length=1024)
    category: Optional[str] = Field(default=None, max_length=64)
    importance: Optional[str] = Field(default=None, max_length=16)
    phase: Optional[int] = None
    status: Optional[str] = Field(default=None, max_length=16)
    external_url: Optional[str] = Field(default=None, max_length=512)
    delivery_remark: Optional[str] = Field(default=None, max_length=512)
    owner: Optional[str] = Field(default=None, max_length=64)


class VersionTextCreate(BaseModel):
    """在线编辑保存（Phase 2 §6.1）。content 字符上限兜住 JSON 解析，字节级上限仍由 service 强制。"""

    content: str = Field(min_length=1, max_length=2_000_000)
    change_note: Optional[str] = Field(default=None, max_length=512)
    base_version_no: Optional[int] = Field(default=None, ge=1)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    parent_id: Optional[int] = Field(default=None, ge=1)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2048)
    status: Optional[str] = Field(default="todo", max_length=16)
    blocked_reason: Optional[str] = Field(default=None, max_length=512)
    assignee: Optional[str] = Field(default=None, max_length=64)
    due_date: Optional[date] = None
    phase: Optional[int] = None
    material_ids: Optional[list[int]] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2048)
    status: Optional[str] = Field(default=None, max_length=16)
    blocked_reason: Optional[str] = Field(default=None, max_length=512)
    assignee: Optional[str] = Field(default=None, max_length=64)
    due_date: Optional[date] = None
    phase: Optional[int] = None
    material_ids: Optional[list[int]] = None
