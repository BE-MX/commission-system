"""报表中心 — Pydantic 模型"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReportTemplateCreate(BaseModel):
    report_code: str
    name: str
    description: Optional[str] = None
    template_content: str


class ReportTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    template_content: Optional[str] = None
    status: Optional[int] = None
    change_summary: Optional[str] = None


class ReportTemplateResponse(BaseModel):
    id: int
    report_code: str
    name: str
    description: Optional[str] = None
    version: int
    status: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReportTemplateDetailResponse(ReportTemplateResponse):
    """含模板内容的完整响应"""
    template_content: str


class ReportTemplateVersionResponse(BaseModel):
    id: int
    template_id: int
    version: int
    change_summary: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}
