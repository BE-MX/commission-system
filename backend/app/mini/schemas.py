"""微信小程序端接口 — Pydantic schemas"""

from typing import Optional
from pydantic import BaseModel, Field


# ── 认证 ──────────────────────────────────────────────────

class MiniLoginRequest(BaseModel):
    code: str = Field(..., description="wx.login() 返回的一次性 code")


class MiniBindRequest(BaseModel):
    open_id: str = Field(..., description="登录接口返回的 openId")
    identifier: str = Field(..., description="工号或手机号")


class MiniUserInfo(BaseModel):
    id: int
    name: str
    wx_id: Optional[str] = None


class MiniLoginResponse(BaseModel):
    bound: bool
    token: Optional[str] = None
    user: Optional[MiniUserInfo] = None
    open_id: Optional[str] = None


class MiniVerifyResponse(BaseModel):
    valid: bool
    user: Optional[MiniUserInfo] = None


# ── 扫码 ──────────────────────────────────────────────────

class ScanSubmitRequest(BaseModel):
    progress_id: int = Field(..., description="工序进度记录 ID")
    order_product_id: int = Field(..., description="产品 ID（二次校验）")


class RevokeRequest(BaseModel):
    progress_id: int = Field(..., description="要撤销的工序进度记录 ID")


class ProductInfo(BaseModel):
    id: int
    order_id: Optional[str] = None
    order_no: Optional[str] = None
    product_name: Optional[str] = None
    model: Optional[str] = None
    spec_info: Optional[str] = None
    order_qty: Optional[int] = None
    received_qty: Optional[int] = None
    is_urgent: Optional[int] = 0
    expected_delivery_date: Optional[str] = None


class NextProcessInfo(BaseModel):
    progress_id: int
    process_name: str
    step_order: int
    total_steps: int
    completed_by: Optional[str] = None


class ScanProductResponse(BaseModel):
    product: ProductInfo
    next_process: Optional[NextProcessInfo] = None
    can_submit: bool
    block_reason: Optional[str] = None


class ScanSubmitResponse(BaseModel):
    success: bool
    message: str
    all_done: Optional[bool] = False
    next_process: Optional[str] = None


class HistoryRecord(BaseModel):
    product_name: Optional[str] = None
    model: Optional[str] = None
    process_name: Optional[str] = None
    completed_at: Optional[str] = None
    order_no: Optional[str] = None


class HistoryResponse(BaseModel):
    today_count: int = 0
    records: list[HistoryRecord] = []
