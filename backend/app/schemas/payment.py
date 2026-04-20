"""回款同步相关 Schema"""

from typing import Optional
from datetime import date

from pydantic import BaseModel, ConfigDict


class PaymentSyncRequest(BaseModel):
    """回款同步请求"""
    date_start: date
    date_end: date


class PaymentSyncResponse(BaseModel):
    """回款同步结果"""
    total_payments: int
    new_synced: int
    already_synced: int
    customers_checked: int
    snapshots_auto_created: int
    snapshots_incomplete: int
    incomplete_customers: list[str] = []


class SyncedPaymentListItem(BaseModel):
    """已同步回款列表项"""
    model_config = ConfigDict(from_attributes=True)

    payment_id: str
    order_id: str
    customer_id: str
    customer_name: Optional[str] = None
    payment_date: date
    payment_amount: float
    is_calculated: bool = False
    batch_id: Optional[int] = None
