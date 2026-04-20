"""提成批次、明细相关 Schema"""

from typing import Optional, Literal
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CommissionBatchCreateRequest(BaseModel):
    """创建提成批次请求"""
    batch_name: str
    period_type: Literal["monthly", "quarterly", "semi_annual", "annual"] = "quarterly"
    period_start: date
    period_end: date


class CommissionBatchListItem(BaseModel):
    """提成批次列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_name: str
    period_type: Optional[str] = None
    period_start: date
    period_end: date
    status: str
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    confirmed_by: Optional[str] = None


class CommissionDetailListItem(BaseModel):
    """提成明细列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_id: str
    order_id: str
    customer_id: str
    customer_name: Optional[str] = None
    payment_amount: float
    salesperson_id: str
    salesperson_name: Optional[str] = None
    salesperson_rate: float
    salesperson_commission: float
    supervisor_id: Optional[str] = None
    supervisor_name: Optional[str] = None
    supervisor_rate: Optional[float] = None
    supervisor_commission: float
    calc_rule_note: Optional[str] = None
    status: str


class CommissionCalcResponse(BaseModel):
    """提成计算结果"""
    total_payments: int
    total_salesperson_commission: float
    total_supervisor_commission: float
    skipped_incomplete: int
    skipped_no_snapshot: int
    errors: list[str] = []


class CommissionConfirmRequest(BaseModel):
    """确认批次请求"""
    confirmed_by: str


class CommissionBatchSummary(BaseModel):
    """批次汇总统计"""
    batch_name: str
    status: str
    total_payments: int
    total_payment_amount: float
    total_salesperson_commission: float
    total_supervisor_commission: float
    total_commission: float
    salesperson_count: int
    supervisor_count: int
    skipped_incomplete: int
    skipped_no_snapshot: int
