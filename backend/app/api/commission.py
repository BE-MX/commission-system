"""提成计算路由"""

from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_db
from app.models.commission import (
    CommissionBatch, CommissionDetail, SyncedPayment, PaymentCommissionStatus,
)
from app.models.customer import CustomerCommissionSnapshot
from app.models.business import UserBasic, CustomerInfo
from app.schemas.common import ResponseModel, PageResponse
from app.schemas.commission import (
    CommissionBatchCreateRequest, CommissionBatchListItem,
    CommissionDetailListItem, CommissionCalcResponse,
    CommissionConfirmRequest, CommissionBatchSummary,
)
from app.services.commission_calculator import (
    calculate_commission, void_batch, confirm_batch,
)

router = APIRouter()


@router.post("/batch", summary="创建提成批次")
def create_batch(
    req: CommissionBatchCreateRequest,
    db: Session = Depends(get_db),
) -> ResponseModel[CommissionBatchListItem]:
    """创建提成批次（status=draft）"""
    batch = CommissionBatch(
        batch_name=req.batch_name,
        period_type=req.period_type,
        period_start=req.period_start,
        period_end=req.period_end,
        status="draft",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    return ResponseModel(data=CommissionBatchListItem.model_validate(batch))


@router.get("/batch/list", summary="查询批次列表")
def list_batches(
    status: str = Query("", description="状态筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ResponseModel[PageResponse[CommissionBatchListItem]]:
    """查询提成批次列表"""
    query = db.query(CommissionBatch)

    if status:
        query = query.filter(CommissionBatch.status == status)

    query = query.order_by(CommissionBatch.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = [CommissionBatchListItem.model_validate(b) for b in rows]
    page_data = PageResponse(items=items, total=total, page=page, page_size=page_size)
    return ResponseModel(data=page_data)


@router.post("/batch/{batch_id}/calculate", summary="执行提成计算")
def execute_calculation(
    batch_id: int = Path(..., description="批次ID"),
    db: Session = Depends(get_db),
) -> ResponseModel[CommissionCalcResponse]:
    """对指定批次执行提成计算"""
    result = calculate_commission(db, batch_id)
    db.commit()

    return ResponseModel(data=CommissionCalcResponse(
        total_payments=result.total_payments,
        total_salesperson_commission=float(result.total_salesperson_commission),
        total_supervisor_commission=float(result.total_supervisor_commission),
        skipped_incomplete=result.skipped_incomplete,
        skipped_no_snapshot=result.skipped_no_snapshot,
        errors=result.errors,
    ))


@router.get("/batch/{batch_id}/details", summary="查询提成明细")
def list_commission_details(
    batch_id: int = Path(..., description="批次ID"),
    salesperson_id: str = Query("", description="业务员ID"),
    supervisor_id: str = Query("", description="主管ID"),
    customer_id: str = Query("", description="客户ID"),
    keyword: str = Query("", description="搜索关键字"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ResponseModel[PageResponse[CommissionDetailListItem]]:
    """查询指定批次的提成明细"""
    SpUser = aliased(UserBasic)
    SvUser = aliased(UserBasic)

    query = db.query(
        CommissionDetail,
        CustomerInfo.company_name.label("customer_name"),
        SpUser.full_name.label("salesperson_name"),
        SvUser.full_name.label("supervisor_name"),
    ).outerjoin(
        CustomerInfo,
        CommissionDetail.customer_id == CustomerInfo.company_id,
    ).outerjoin(
        SpUser, CommissionDetail.salesperson_id == SpUser.user_id,
    ).outerjoin(
        SvUser, CommissionDetail.supervisor_id == SvUser.user_id,
    ).filter(
        CommissionDetail.batch_id == batch_id,
    )

    if salesperson_id:
        query = query.filter(CommissionDetail.salesperson_id == salesperson_id)
    if supervisor_id:
        query = query.filter(CommissionDetail.supervisor_id == supervisor_id)
    if customer_id:
        query = query.filter(CommissionDetail.customer_id == customer_id)
    if keyword:
        like_pattern = f"%{keyword}%"
        query = query.filter(
            CustomerInfo.company_name.like(like_pattern)
            | SpUser.full_name.like(like_pattern)
            | SvUser.full_name.like(like_pattern)
            | CommissionDetail.payment_id.like(like_pattern)
        )

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for detail, customer_name, sp_name, sv_name in rows:
        items.append(CommissionDetailListItem(
            id=detail.id,
            payment_id=detail.payment_id,
            order_id=detail.order_id,
            customer_id=detail.customer_id,
            customer_name=customer_name,
            payment_amount=float(detail.payment_amount),
            salesperson_id=detail.salesperson_id,
            salesperson_name=sp_name,
            salesperson_rate=float(detail.salesperson_rate),
            salesperson_commission=float(detail.salesperson_commission),
            supervisor_id=detail.supervisor_id,
            supervisor_name=sv_name,
            supervisor_rate=float(detail.supervisor_rate) if detail.supervisor_rate else None,
            supervisor_commission=float(detail.supervisor_commission),
            calc_rule_note=detail.calc_rule_note,
            status=detail.status,
        ))

    page_data = PageResponse(items=items, total=total, page=page, page_size=page_size)
    return ResponseModel(data=page_data)


@router.post("/batch/{batch_id}/confirm", summary="确认批次")
def confirm_commission_batch(
    batch_id: int = Path(..., description="批次ID"),
    req: CommissionConfirmRequest = ...,
    db: Session = Depends(get_db),
) -> ResponseModel[dict]:
    """确认提成批次"""
    confirm_batch(db, batch_id, req.confirmed_by)
    db.commit()
    return ResponseModel(message="批次已确认", data={"batch_id": batch_id})


@router.post("/batch/{batch_id}/void", summary="作废批次")
def void_commission_batch(
    batch_id: int = Path(..., description="批次ID"),
    db: Session = Depends(get_db),
) -> ResponseModel[dict]:
    """作废提成批次"""
    void_batch(db, batch_id)
    db.commit()
    return ResponseModel(message="批次已作废", data={"batch_id": batch_id})


@router.get("/batch/{batch_id}/summary", summary="批次汇总统计")
def get_batch_summary(
    batch_id: int = Path(..., description="批次ID"),
    db: Session = Depends(get_db),
) -> ResponseModel[CommissionBatchSummary]:
    """查询批次汇总统计"""
    batch = db.query(CommissionBatch).filter(CommissionBatch.id == batch_id).first()
    if not batch:
        return ResponseModel(code=404, message=f"批次 {batch_id} 不存在")

    # 聚合提成明细（排除 voided）
    agg = db.query(
        func.count(CommissionDetail.id).label("total_payments"),
        func.coalesce(func.sum(CommissionDetail.payment_amount), 0).label("total_payment_amount"),
        func.coalesce(func.sum(CommissionDetail.salesperson_commission), 0).label("total_sp_commission"),
        func.coalesce(func.sum(CommissionDetail.supervisor_commission), 0).label("total_sv_commission"),
        func.count(func.distinct(CommissionDetail.salesperson_id)).label("salesperson_count"),
        func.count(func.distinct(CommissionDetail.supervisor_id)).label("supervisor_count"),
    ).filter(
        CommissionDetail.batch_id == batch_id,
        CommissionDetail.status != "voided",
    ).first()

    # 计算跳过数：期间内已同步但未参与计算的回款
    period_payment_count = db.query(func.count(SyncedPayment.id)).filter(
        SyncedPayment.payment_date >= batch.period_start,
        SyncedPayment.payment_date <= batch.period_end,
    ).scalar() or 0

    calculated_count = agg.total_payments if agg else 0
    total_skipped = period_payment_count - calculated_count

    # 分析跳过原因
    skipped_incomplete = 0
    skipped_no_snapshot = 0
    if total_skipped > 0:
        calculated_pids = db.query(PaymentCommissionStatus.payment_id).filter(
            PaymentCommissionStatus.batch_id == batch_id,
        ).subquery()

        skipped_payments = db.query(SyncedPayment.customer_id).filter(
            SyncedPayment.payment_date >= batch.period_start,
            SyncedPayment.payment_date <= batch.period_end,
            ~SyncedPayment.payment_id.in_(db.query(calculated_pids.c.payment_id)),
        ).all()

        skipped_cids = {r.customer_id for r in skipped_payments}
        for cid in skipped_cids:
            snap = db.query(CustomerCommissionSnapshot).filter(
                CustomerCommissionSnapshot.customer_id == cid,
                CustomerCommissionSnapshot.is_current == True,
            ).first()
            if not snap:
                skipped_no_snapshot += 1
            elif not snap.is_complete:
                skipped_incomplete += 1

    total_sp = float(agg.total_sp_commission) if agg else 0
    total_sv = float(agg.total_sv_commission) if agg else 0

    return ResponseModel(data=CommissionBatchSummary(
        batch_name=batch.batch_name,
        status=batch.status,
        total_payments=calculated_count,
        total_payment_amount=float(agg.total_payment_amount) if agg else 0,
        total_salesperson_commission=total_sp,
        total_supervisor_commission=total_sv,
        total_commission=total_sp + total_sv,
        salesperson_count=agg.salesperson_count if agg else 0,
        supervisor_count=agg.supervisor_count if agg else 0,
        skipped_incomplete=skipped_incomplete,
        skipped_no_snapshot=skipped_no_snapshot,
    ))
