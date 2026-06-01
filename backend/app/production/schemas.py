"""生产报工 — Pydantic schemas"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── 工序 ──────────────────────────────────────────────────

class ProcessCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    sort_order: int = Field(0, ge=0)


class ProcessUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    sort_order: Optional[int] = Field(None, ge=0)
    status: Optional[int] = Field(None, ge=0, le=1)


class ProcessResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    sort_order: int
    status: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProcessListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ProcessResponse]


# ── 工序路线 ──────────────────────────────────────────────

class ProcessRouteCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class ProcessRouteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    status: Optional[int] = Field(None, ge=0, le=1)


class ProcessRouteResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: int
    step_count: int = 0
    product_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProcessRouteListResponse(BaseModel):
    total: int
    items: list[ProcessRouteResponse]


# ── 路线步骤 ──────────────────────────────────────────────

class RouteStepItem(BaseModel):
    process_id: int


class RouteStepsSaveRequest(BaseModel):
    steps: list[RouteStepItem]


class RouteStepResponse(BaseModel):
    id: int
    route_id: int
    process_id: int
    process_name: str
    step_order: int


class RouteStepsResponse(BaseModel):
    route_id: int
    steps: list[RouteStepResponse]


# ── 产品路线绑定 ─────────────────────────────────────────

class ProductRouteBindRequest(BaseModel):
    route_id: Optional[int] = None  # None = 解绑


class BatchBindRouteRequest(BaseModel):
    product_ids: list[int] = Field(..., min_length=1, max_length=200)
    route_id: int


class ProductRouteResponse(BaseModel):
    product_id: int
    route_id: Optional[int] = None
    route_name: Optional[str] = None
    updated_at: Optional[datetime] = None


class ProductListItem(BaseModel):
    product_id: int
    product_no: Optional[str] = None
    name: Optional[str] = None
    model: Optional[str] = None
    disable_flag: int = 0
    process_route: Optional[ProductRouteResponse] = None


class ProductListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ProductListItem]


class ProductFilterOptions(BaseModel):
    models: list[str] = []
    group_names: list[str] = []


class ProductRouteDetailResponse(BaseModel):
    product_id: int
    route_id: int
    route_name: str
    steps: list[RouteStepResponse]
    updated_at: Optional[datetime] = None


# ── 用户工序绑定 ─────────────────────────────────────────

class UserProcessBindingResponse(BaseModel):
    user_id: int
    bindings: list[dict]  # [{process_id, process_name, bound_at}]


class UserProcessBindingUpdate(BaseModel):
    process_ids: list[int] = []


class UserWxIdUpdate(BaseModel):
    wx_id: Optional[str] = None


class UserWxIdResponse(BaseModel):
    user_id: int
    wx_id: Optional[str] = None
    message: str = "微信ID已更新"


# ── 报工 ──────────────────────────────────────────────────

class ReportRequest(BaseModel):
    qr_data: str
    wx_id: str


class ReportData(BaseModel):
    order_product_id: Optional[int] = None
    process_id: Optional[int] = None
    process_name: Optional[str] = None
    step_order: Optional[int] = None
    completed_at: Optional[datetime] = None
    remaining_steps: Optional[int] = None
    total_steps: Optional[int] = None
    all_completed: Optional[bool] = None
    current_pending_process: Optional[str] = None


class ReportResponse(BaseModel):
    success: bool
    message: str
    data: Optional[ReportData] = None


# ── 进度 ──────────────────────────────────────────────────

class ProgressStepResponse(BaseModel):
    id: int
    step_order: int
    process_id: int
    process_name: str
    status: int
    completed_at: Optional[datetime] = None
    completed_by_user_id: Optional[int] = None
    completed_by_user_name: Optional[str] = None
    completed_by_wx_id: Optional[str] = None


class ProgressResponse(BaseModel):
    order_product_id: int
    route_id: int
    route_name: str
    total_steps: int
    completed_steps: int
    completion_rate: float
    all_completed: bool
    steps: list[ProgressStepResponse]


class InitProgressRequest(BaseModel):
    force: bool = False


class InitProgressResponse(BaseModel):
    order_product_id: int
    route_id: int
    route_name: str
    initialized_steps: int
    message: str


# ── 二维码 / 打印卡 ─────────────────────────────────────

class QRCodeResponse(BaseModel):
    order_product_id: int
    qr_data: str
    qr_code: str  # data:image/png;base64,...


class PrintCardStep(BaseModel):
    step_order: int
    process_name: str


class PrintCardResponse(BaseModel):
    order_product_id: int
    order_no: str
    product_name: str
    model: Optional[str] = None
    spec_info: Optional[str] = None
    order_qty: int
    expected_delivery_date: Optional[str] = None
    is_urgent: int = 0
    remark: Optional[str] = None
    process_steps: list[PrintCardStep] = []
    qr_code_base64: str
    printed_at: str
