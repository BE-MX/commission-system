"""回款同步路由"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.commission import SyncedPayment, PaymentCommissionStatus
from app.models.business import CustomerInfo
from app.schemas.common import ResponseModel, PageResponse
from app.schemas.payment import (
    PaymentSyncRequest, PaymentSyncResponse, SyncedPaymentListItem,
)
from app.services.payment_sync_service import sync_payments

router = APIRouter()


@router.post("/sync", summary="执行回款增量同步")
def execute_payment_sync(
    req: PaymentSyncRequest,
    db: Session = Depends(get_db),
) -> ResponseModel[PaymentSyncResponse]:
    """执行回款增量同步，从业务库拉取指定日期范围的回款"""
    result = sync_payments(db, req.date_start, req.date_end)
    db.commit()

    return ResponseModel(data=PaymentSyncResponse(
        total_payments=result.total_payments,
        new_synced=result.new_synced,
        already_synced=result.already_synced,
        customers_checked=result.customers_checked,
        snapshots_auto_created=result.snapshots_auto_created,
        snapshots_incomplete=result.snapshots_incomplete,
        incomplete_customers=result.incomplete_customers,
    ))


@router.get("/synced/list", summary="查询已同步回款列表")
def list_synced_payments(
    date_start: str = Query(..., description="回款日期起始"),
    date_end: str = Query(..., description="回款日期结束"),
    customer_id: str = Query("", description="客户ID"),
    keyword: str = Query("", description="搜索关键字"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ResponseModel[PageResponse[SyncedPaymentListItem]]:
    """查询已同步的回款列表"""
    query = db.query(
        SyncedPayment,
        CustomerInfo.company_name.label("customer_name"),
        PaymentCommissionStatus.batch_id,
    ).outerjoin(
        CustomerInfo,
        SyncedPayment.customer_id == CustomerInfo.company_id,
    ).outerjoin(
        PaymentCommissionStatus,
        SyncedPayment.payment_id == PaymentCommissionStatus.payment_id,
    ).filter(
        SyncedPayment.payment_date >= date_start,
        SyncedPayment.payment_date <= date_end,
    )

    if customer_id:
        query = query.filter(SyncedPayment.customer_id == customer_id)

    if keyword:
        like_pattern = f"%{keyword}%"
        query = query.filter(or_(
            SyncedPayment.payment_id.like(like_pattern),
            SyncedPayment.order_id.like(like_pattern),
            SyncedPayment.customer_id.like(like_pattern),
            CustomerInfo.company_name.like(like_pattern),
        ))

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for payment, customer_name, batch_id in rows:
        items.append(SyncedPaymentListItem(
            payment_id=payment.payment_id,
            order_id=payment.order_id,
            customer_id=payment.customer_id,
            customer_name=customer_name,
            payment_date=payment.payment_date,
            payment_amount=float(payment.payment_amount),
            is_calculated=batch_id is not None,
            batch_id=batch_id,
        ))

    page_data = PageResponse(items=items, total=total, page=page, page_size=page_size)
    return ResponseModel(data=page_data)
