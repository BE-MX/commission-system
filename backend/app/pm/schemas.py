"""PM Hub Pydantic schemas（请求体校验）。"""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class EntryRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class MaterialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: Optional[str] = None
    category: Optional[str] = "其他"
    importance: Optional[str] = "important"
    phase: Optional[int] = None
    delivery_type: Optional[str] = "file"
    external_url: Optional[str] = None
    delivery_remark: Optional[str] = None
    owner: Optional[str] = None


class MaterialUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[str] = None
    phase: Optional[int] = None
    status: Optional[str] = None
    external_url: Optional[str] = None
    delivery_remark: Optional[str] = None
    owner: Optional[str] = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: Optional[str] = None
    status: Optional[str] = "todo"
    blocked_reason: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[date] = None
    phase: Optional[int] = None
    material_ids: Optional[list[int]] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    blocked_reason: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[date] = None
    phase: Optional[int] = None
    material_ids: Optional[list[int]] = None
