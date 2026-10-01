"""任务中心入参。字段值域的业务校验在 service 层（返回中文提示），这里只做形状约束。"""
from typing import Optional

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=10000)
    acceptance: Optional[list[str]] = None
    priority: str = "P2"
    module_key: Optional[str] = None
    parent_id: Optional[int] = None
    due_date: Optional[str] = None
    source: str = "manual"


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=10000)
    acceptance: Optional[list[str]] = None
    priority: Optional[str] = None
    module_key: Optional[str] = None
    due_date: Optional[str] = None


class StatusChange(BaseModel):
    status: str
    reason: Optional[str] = Field(None, max_length=500)
    confirm_open_children: bool = False


class MoveInput(BaseModel):
    parent_id: Optional[int] = None


class LinkCreate(BaseModel):
    kind: str
    ref: str = Field(..., max_length=500)
    title: str = Field("", max_length=200)


class CustomModuleCreate(BaseModel):
    title: str = Field(..., max_length=100)


class DraftRequest(BaseModel):
    text: str = Field(..., max_length=1000)
    module_key: Optional[str] = None
    parent_id: Optional[int] = None
