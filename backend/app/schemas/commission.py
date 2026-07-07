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
    expected_confirm_count: int = 0
    confirmed_count: int = 0
    pending_confirm_count: int = 0
    feedback_count: int = 0
    confirmation_status: str = "not_started"


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
    second_supervisor_id: Optional[str] = None
    second_supervisor_name: Optional[str] = None
    second_supervisor_rate: Optional[float] = None
    second_supervisor_commission: float = 0
    calc_rule_note: Optional[str] = None
    status: str


class CommissionCalcResponse(BaseModel):
    """提成计算结果"""
    total_payments: int
    total_salesperson_commission: float
    total_supervisor_commission: float
    total_second_supervisor_commission: float = 0
    skipped_incomplete: int
    skipped_no_snapshot: int
    errors: list[str] = []


class CommissionConfirmRequest(BaseModel):
    """确认批次请求"""
    confirmed_by: str


class CommissionSendConfirmRequest(BaseModel):
    """发送确认请求"""
    notify_dingtalk: bool = True


class CommissionBatchSummary(BaseModel):
    """批次汇总统计"""
    batch_name: str
    status: str
    total_payments: int
    total_payment_amount: float
    total_salesperson_commission: float
    total_supervisor_commission: float
    total_second_supervisor_commission: float = 0
    total_commission: float
    salesperson_count: int
    supervisor_count: int
    second_supervisor_count: int = 0
    skipped_incomplete: int
    skipped_no_snapshot: int
    expected_confirm_count: int = 0
    confirmed_count: int = 0
    pending_confirm_count: int = 0
    feedback_count: int = 0
    confirmation_status: str = "not_started"


class SalesCommissionBatchListItem(BaseModel):
    """业务员侧提成批次列表项"""
    id: int
    batch_name: str
    period_start: date
    period_end: date
    status: str
    related_roles: list[str] = []
    total_payment_amount: float = 0
    total_salesperson_commission: float = 0
    total_supervisor_commission: float = 0
    total_second_supervisor_commission: float = 0
    total_commission: float = 0
    total_commission_rmb: float = 0
    detail_count: int = 0
    created_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    is_confirmed_by_me: bool = False
    my_confirmed_at: Optional[datetime] = None


class SalesCommissionMonthlySummary(BaseModel):
    """业务员侧月度汇总"""
    month: str
    total_commission_usd: float = 0
    average_exchange_rate: float = 0
    total_commission_rmb: float = 0


class SalesCommissionSummary(BaseModel):
    """业务员侧批次汇总"""
    total_payment_amount: float = 0
    total_salesperson_commission: float = 0
    total_supervisor_commission: float = 0
    total_second_supervisor_commission: float = 0
    total_commission: float = 0
    total_commission_rmb: float = 0


class SalesCommissionDetailItem(BaseModel):
    """业务员侧提成明细项"""
    id: int
    payment_id: str
    order_id: str
    order_no: Optional[str] = None
    order_name: Optional[str] = None
    customer_id: str
    customer_name: Optional[str] = None
    customer_country: Optional[str] = None
    collection_date: Optional[date] = None
    type: Optional[str] = None
    payment_amount: float = 0
    service_fee: float = 0
    order_source: Optional[str] = None
    exchange_rate: float = 0
    salesperson_id: Optional[str] = None
    salesperson_name: Optional[str] = None
    salesperson_rate: Optional[float] = None
    salesperson_commission: float = 0
    salesperson_commission_rmb: float = 0
    supervisor_id: Optional[str] = None
    supervisor_name: Optional[str] = None
    supervisor_rate: Optional[float] = None
    supervisor_commission: float = 0
    supervisor_commission_rmb: float = 0
    second_supervisor_id: Optional[str] = None
    second_supervisor_name: Optional[str] = None
    second_supervisor_rate: Optional[float] = None
    second_supervisor_commission: float = 0
    second_supervisor_commission_rmb: float = 0
    calc_rule_note: Optional[str] = None
    status: str


class SalesCommissionBatchDetail(BaseModel):
    """业务员侧批次详情"""
    batch: SalesCommissionBatchListItem
    summary: SalesCommissionSummary
    monthly_summary: list[SalesCommissionMonthlySummary] = []
    salesperson_details: list[SalesCommissionDetailItem] = []
    supervisor_details: list[SalesCommissionDetailItem] = []
    second_supervisor_details: list[SalesCommissionDetailItem] = []


class SalesCommissionFeedbackRequest(BaseModel):
    """业务员批次问题反馈"""
    content: str


class SalesCommissionConfirmRequest(BaseModel):
    """业务员确认提交请求"""
    confirmation_text: str


class CommissionConfirmationProgress(BaseModel):
    """批次确认汇总进度"""
    expected_confirm_count: int = 0
    confirmed_count: int = 0
    pending_confirm_count: int = 0
    feedback_count: int = 0
    confirmation_status: str = "not_started"
