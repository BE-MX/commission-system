"""备货管理 — Pydantic 请求/响应模型"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class SafetyStockSaveItem(BaseModel):
    product_id: int
    safety_stock: int = Field(ge=0)
    # 乐观锁,带上当前 updated_at,服务端校验未变化才接受
    updated_at: Optional[str] = None


class SafetyStockSaveRequest(BaseModel):
    lead_time_days: int = Field(default=30, ge=1, le=365)
    safety_factor: float = Field(default=1.5, ge=0.1, le=10.0)
    items: List[SafetyStockSaveItem]


class AutoGenerateRequest(BaseModel):
    product_ids: Optional[List[int]] = None
    lead_time_days: int = Field(default=30, ge=1, le=365)
    safety_factor: float = Field(default=1.5, ge=0.1, le=10.0)
    history_days: int = Field(default=30, ge=7, le=365)


class TftPredictRequest(BaseModel):
    product_id: int
    history_days: int = Field(default=90, ge=7, le=365)


# ═══════════════════════════════════════════════════════════
# 生产单购物车
# ═══════════════════════════════════════════════════════════

class CartAddRequest(BaseModel):
    """加入购物车"""
    product_id: int
    product_name: str = Field(max_length=255)
    model: Optional[str] = Field(None, max_length=100)
    spec_info: Optional[str] = Field(None, max_length=255)
    order_qty: int = Field(gt=0, le=999999)
    remark: Optional[str] = Field(None, max_length=500)


class CartUpdateRequest(BaseModel):
    """更新购物车项"""
    order_qty: int = Field(gt=0, le=999999)
    remark: Optional[str] = Field(None, max_length=500)


class CartItemResponse(BaseModel):
    """购物车项响应"""
    id: int
    product_id: int
    product_name: str
    model: Optional[str]
    spec_info: Optional[str]
    order_qty: int
    remark: Optional[str]
    created_at: str


# ═══════════════════════════════════════════════════════════
# 生产订单
# ═══════════════════════════════════════════════════════════

class OrderCreateRequest(BaseModel):
    """从购物车生成生产订单"""
    cart_ids: List[int] = Field(min_length=1)
    batch_no: str = Field(max_length=64)
    remark: Optional[str] = Field(None, max_length=500)
    is_urgent: bool = Field(default=False)
    expected_delivery_date: Optional[date] = None


class OrderUpdateRequest(BaseModel):
    """编辑生产订单"""
    batch_no: Optional[str] = Field(None, max_length=64)
    remark: Optional[str] = Field(None, max_length=500)
    status: Optional[int] = Field(None, ge=0, le=2)


class OrderItemUpdateRequest(BaseModel):
    """编辑生产订单明细"""
    order_qty: Optional[int] = Field(None, gt=0, le=999999)
    remark: Optional[str] = Field(None, max_length=500)
    is_urgent: Optional[int] = Field(None, ge=0, le=1)
    expected_delivery_date: Optional[date] = None


class OrderItemReceivedRequest(BaseModel):
    """录入已入库数量"""
    received_qty: int = Field(ge=0, le=999999)


class OrderItemStatusRequest(BaseModel):
    """修改明细状态"""
    status: int = Field(ge=0, le=2)


class OrderItemResponse(BaseModel):
    """生产订单明细响应"""
    id: int
    order_id: int
    product_id: int
    product_name: str
    model: Optional[str]
    spec_info: Optional[str]
    order_qty: int
    received_qty: int
    in_transit_qty: int
    status: int
    is_urgent: int
    expected_delivery_date: Optional[str]
    remark: Optional[str]
    created_at: str


class OrderListResponse(BaseModel):
    """生产订单列表项"""
    id: int
    order_no: str
    batch_no: str
    remark: Optional[str]
    status: int
    status_label: str
    created_by: int
    created_by_name: Optional[str]
    created_at: str
    item_count: int
    total_order_qty: int
    total_received_qty: int
    total_in_transit_qty: int


class OrderDetailResponse(BaseModel):
    """生产订单详情"""
    id: int
    order_no: str
    batch_no: str
    remark: Optional[str]
    status: int
    status_label: str
    created_by: int
    created_by_name: Optional[str]
    created_at: str
    updated_by: Optional[int]
    updated_at: Optional[str]
    items: List[OrderItemResponse]


class OrderItemListResponse(BaseModel):
    """生产订单明细列表项(标签页二用)"""
    id: int
    order_id: int
    order_no: str
    batch_no: str
    product_id: int
    product_name: str
    model: Optional[str]
    spec_info: Optional[str]
    order_qty: int
    received_qty: int
    in_transit_qty: int
    status: int
    status_label: str
    order_status: int
    order_status_label: str
    is_urgent: int
    expected_delivery_date: Optional[str]
    remark: Optional[str]
    created_at: str


# ═══════════════════════════════════════════════════════════
# 备货状态查询
# ═══════════════════════════════════════════════════════════

class StockStatusQueryRequest(BaseModel):
    product_ids: List[int]


class StockStatusItemResponse(BaseModel):
    product_id: int
    stock_status: str  # "", "备货中", "加急中"
    has_urgent: bool
    items: List[dict]


# ═══════════════════════════════════════════════════════════
# 生产在途查询
# ═══════════════════════════════════════════════════════════

class InTransitQueryRequest(BaseModel):
    product_ids: List[int]


class InTransitItemResponse(BaseModel):
    product_id: int
    in_transit_qty: int
