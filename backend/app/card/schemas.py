"""Pydantic schemas for the sales-card butler module."""

from typing import Optional

from pydantic import BaseModel, Field


# ---------- 公开端点 ----------

class UnlockRequest(BaseModel):
    passcode: str = Field(..., min_length=3, max_length=128)


class InquiryCreate(BaseModel):
    contact: str = Field(..., min_length=3, max_length=128)
    message: str = Field(..., min_length=1, max_length=2000)


# ---------- 管理端点 ----------

class SalespersonUpsert(BaseModel):
    # (?!admin$) ：slug=admin 会与 /admin/* 管理路由字面前缀纠缠（审查 P2-6）
    slug: str = Field(..., min_length=2, max_length=32, pattern=r"^(?!admin$)[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=64)
    title: str = Field("Sales Manager", max_length=64)
    email: str = Field(..., max_length=128)
    whatsapp: Optional[str] = Field(None, max_length=32)
    intro: Optional[str] = None
    links_json: Optional[list] = None
    is_active: int = 1


class CustomerCreate(BaseModel):
    salesperson_id: int
    display_name: str = Field(..., min_length=1, max_length=128)
    email: Optional[str] = Field(None, max_length=128)
    whatsapp: Optional[str] = Field(None, max_length=64)
    expo_code: str = Field("", max_length=64)
    remark: Optional[str] = None


class CustomerUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=128)
    email: Optional[str] = Field(None, max_length=128)
    whatsapp: Optional[str] = Field(None, max_length=64)
    expo_code: Optional[str] = Field(None, max_length=64)
    remark: Optional[str] = None


class EntryCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=128)
    content: Optional[str] = Field(None, max_length=8000)
    # 只认本模块上传端点产出的路径形状，防把其他模块的 /uploads 文件投影进客户可见纪要（审查 P2-3）
    attachment_path: Optional[str] = Field(
        None, max_length=512, pattern=r"^card/[0-9a-f]{32}\.(jpg|jpeg|png|webp)$",
    )


class InquiryStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(new|handled)$")
