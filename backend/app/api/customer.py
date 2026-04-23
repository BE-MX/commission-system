"""客户归属快照管理路由"""

import tempfile
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, UploadFile, File, Query, Path
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_db
from app.models.customer import CustomerCommissionSnapshot
from app.models.business import UserBasic, CustomerInfo, OkkiReceipt
from app.schemas.common import ResponseModel, PageResponse
from app.schemas.customer import (
    CustomerSnapshotListItem, CustomerSnapshotCreateRequest,
    CustomerSnapshotCompleteRequest, CustomerSnapshotResetRequest,
    CustomerImportResult, CustomerAutoMatchResult,
)
from app.services.customer_reset_service import (
    reset_customer_attribution, complete_snapshot, import_snapshots_from_excel,
    auto_match_incomplete_snapshots,
)
from app.services.rate_utils import calc_commission_rates

router = APIRouter()


@router.get("/snapshot/list", summary="查询客户归属列表")
def list_customer_snapshots(
    keyword: str = Query("", description="搜索客户名/ID"),
    is_complete: str = Query("all", description="完整性筛选: true/false/all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ResponseModel[PageResponse[CustomerSnapshotListItem]]:
    """查询当前有效的客户归属快照列表"""
    SpUser = aliased(UserBasic)
    SvUser = aliased(UserBasic)
    Sv2User = aliased(UserBasic)

    first_receipt_sub = db.query(
        OkkiReceipt.company_id,
        func.min(OkkiReceipt.collection_date).label("first_receipt_date"),
    ).group_by(OkkiReceipt.company_id).subquery()

    query = db.query(
        CustomerCommissionSnapshot,
        CustomerInfo.company_name.label("customer_name"),
        SpUser.full_name.label("salesperson_name"),
        SvUser.full_name.label("supervisor_name"),
        Sv2User.full_name.label("second_supervisor_name"),
        first_receipt_sub.c.first_receipt_date,
    ).outerjoin(
        CustomerInfo,
        CustomerCommissionSnapshot.customer_id == CustomerInfo.company_id,
    ).outerjoin(
        SpUser,
        CustomerCommissionSnapshot.salesperson_id == SpUser.user_id,
    ).outerjoin(
        SvUser,
        CustomerCommissionSnapshot.supervisor_id == SvUser.user_id,
    ).outerjoin(
        Sv2User,
        CustomerCommissionSnapshot.second_supervisor_id == Sv2User.user_id,
    ).outerjoin(
        first_receipt_sub,
        CustomerCommissionSnapshot.customer_id == first_receipt_sub.c.company_id,
    ).filter(
        CustomerCommissionSnapshot.is_current == True,
    )

    if is_complete == "true":
        query = query.filter(CustomerCommissionSnapshot.is_complete == True)
    elif is_complete == "false":
        query = query.filter(CustomerCommissionSnapshot.is_complete == False)

    if keyword:
        like_pattern = f"%{keyword}%"
        query = query.filter(or_(
            CustomerCommissionSnapshot.customer_id.like(like_pattern),
            CustomerInfo.company_name.like(like_pattern),
        ))

    total = query.count()
    rows = query.order_by(
        CustomerCommissionSnapshot.is_complete.asc(),
        SpUser.full_name.asc(),
    ).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for snap, customer_name, sp_name, sv_name, sv2_name, first_receipt_date in rows:
        items.append(CustomerSnapshotListItem(
            id=snap.id,
            customer_id=snap.customer_id,
            customer_name=customer_name,
            salesperson_id=snap.salesperson_id,
            salesperson_name=sp_name,
            salesperson_attribute=snap.salesperson_attribute,
            salesperson_rate=float(snap.salesperson_rate) if snap.salesperson_rate else None,
            supervisor_id=snap.supervisor_id,
            supervisor_name=sv_name,
            supervisor_attribute=snap.supervisor_attribute,
            supervisor_rate=float(snap.supervisor_rate) if snap.supervisor_rate else None,
            second_supervisor_id=snap.second_supervisor_id,
            second_supervisor_name=sv2_name,
            second_supervisor_rate=float(snap.second_supervisor_rate) if snap.second_supervisor_rate else None,
            remark=snap.remark,
            is_complete=snap.is_complete,
            source=snap.source,
            first_order_id=snap.first_order_id,
            first_order_date=snap.first_order_date,
            first_receipt_date=first_receipt_date,
        ))

    page_data = PageResponse(items=items, total=total, page=page, page_size=page_size)
    return ResponseModel(data=page_data)


@router.post("/snapshot", summary="手工新增客户归属")
def create_customer_snapshot(
    req: CustomerSnapshotCreateRequest,
    db: Session = Depends(get_db),
) -> ResponseModel[CustomerSnapshotListItem]:
    """手工新增客户归属快照"""
    cust = db.query(CustomerInfo).filter(CustomerInfo.company_id == req.customer_id).first()
    if not cust:
        return ResponseModel(code=404, message=f"客户 {req.customer_id} 不存在")

    sp_user = db.query(UserBasic).filter(UserBasic.user_id == req.salesperson_id).first()
    if not sp_user:
        return ResponseModel(code=404, message=f"业务员 {req.salesperson_id} 不存在")

    sp_rate, sv_rate, sv2_rate, _ = calc_commission_rates(
        req.salesperson_id, req.salesperson_attribute,
        req.supervisor_id, req.supervisor_attribute,
        req.second_supervisor_id,
    )

    # 旧快照失效
    db.query(CustomerCommissionSnapshot).filter(
        CustomerCommissionSnapshot.customer_id == req.customer_id,
        CustomerCommissionSnapshot.is_current == True,
    ).update({"is_current": False}, synchronize_session="fetch")

    now = datetime.now()
    snapshot = CustomerCommissionSnapshot(
        customer_id=req.customer_id,
        salesperson_id=req.salesperson_id,
        salesperson_attribute=req.salesperson_attribute,
        salesperson_rate=sp_rate,
        supervisor_id=req.supervisor_id,
        supervisor_attribute=req.supervisor_attribute,
        supervisor_rate=sv_rate,
        second_supervisor_id=req.second_supervisor_id,
        second_supervisor_rate=sv2_rate,
        remark=req.remark,
        is_complete=True,
        is_current=True,
        source="manual",
        operator="api",
        operated_at=now,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    return ResponseModel(data=CustomerSnapshotListItem(
        id=snapshot.id,
        customer_id=snapshot.customer_id,
        customer_name=cust.company_name,
        salesperson_id=snapshot.salesperson_id,
        salesperson_name=sp_user.full_name,
        salesperson_attribute=snapshot.salesperson_attribute,
        salesperson_rate=float(sp_rate),
        supervisor_id=snapshot.supervisor_id,
        supervisor_attribute=snapshot.supervisor_attribute,
        supervisor_rate=float(sv_rate) if sv_rate else None,
        second_supervisor_id=snapshot.second_supervisor_id,
        second_supervisor_rate=float(sv2_rate) if sv2_rate else None,
        remark=snapshot.remark,
        is_complete=True,
        source="manual",
        first_order_id=snapshot.first_order_id,
        first_order_date=snapshot.first_order_date,
    ))


@router.put("/snapshot/{snapshot_id}/complete", summary="补全不完整快照")
def complete_customer_snapshot(
    snapshot_id: int = Path(..., description="快照ID"),
    req: CustomerSnapshotCompleteRequest = ...,
    db: Session = Depends(get_db),
) -> ResponseModel[dict]:
    """补全不完整的客户归属快照"""
    from decimal import Decimal as D
    snapshot = complete_snapshot(
        db,
        snapshot_id=snapshot_id,
        salesperson_attribute=req.salesperson_attribute,
        supervisor_attribute=req.supervisor_attribute,
        operator="api",
        salesperson_rate_override=D(str(req.salesperson_rate)) if req.salesperson_rate is not None else None,
        supervisor_rate_override=D(str(req.supervisor_rate)) if req.supervisor_rate is not None else None,
        second_supervisor_rate_override=D(str(req.second_supervisor_rate)) if req.second_supervisor_rate is not None else None,
    )
    db.commit()
    return ResponseModel(
        message="快照补全成功",
        data={"snapshot_id": snapshot.id, "customer_id": snapshot.customer_id},
    )


@router.put("/snapshot/{snapshot_id}/reset", summary="人工重置客户归属")
def reset_customer_snapshot(
    snapshot_id: int = Path(..., description="快照ID"),
    req: CustomerSnapshotResetRequest = ...,
    db: Session = Depends(get_db),
) -> ResponseModel[dict]:
    """人工重置客户归属"""
    old_snapshot = db.query(CustomerCommissionSnapshot).filter(
        CustomerCommissionSnapshot.id == snapshot_id,
    ).first()
    if not old_snapshot:
        return ResponseModel(code=404, message=f"快照 {snapshot_id} 不存在")

    new_snapshot = reset_customer_attribution(
        db,
        customer_id=old_snapshot.customer_id,
        new_salesperson_id=req.salesperson_id,
        new_supervisor_id=req.supervisor_id,
        salesperson_attribute=req.salesperson_attribute,
        supervisor_attribute=req.supervisor_attribute,
        reason=req.reset_reason,
        operator="api",
        new_second_supervisor_id=req.second_supervisor_id,
        remark=req.remark,
    )
    db.commit()
    return ResponseModel(
        message="客户归属已重置",
        data={"snapshot_id": new_snapshot.id, "customer_id": new_snapshot.customer_id},
    )


@router.post("/snapshot/import", summary="Excel批量导入客户归属")
def import_customer_snapshots(
    file: UploadFile = File(..., description="Excel文件"),
    db: Session = Depends(get_db),
) -> ResponseModel[CustomerImportResult]:
    """从 Excel 批量导入客户归属快照"""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    svc_result = import_snapshots_from_excel(db, tmp_path, operator="api")
    db.commit()

    return ResponseModel(data=CustomerImportResult(
        total_rows=svc_result.total_rows,
        success=svc_result.success,
        failed=svc_result.failed,
        failures=svc_result.failures,
    ))


@router.post("/snapshot/auto-match", summary="自动匹配待补充快照")
def auto_match_snapshots(
    db: Session = Depends(get_db),
) -> ResponseModel[CustomerAutoMatchResult]:
    """根据员工属性和主管关系自动填充待补充的客户归属快照"""
    result = auto_match_incomplete_snapshots(db, operator="api")
    db.commit()
    return ResponseModel(
        message=f"本次成功匹配{result.matched}条，当前还剩{result.remaining}条未匹配成功。",
        data=CustomerAutoMatchResult(matched=result.matched, remaining=result.remaining),
    )


@router.get("/snapshot/template", summary="下载客户归属导入模板")
def download_snapshot_template():
    """下载客户归属 Excel 导入模板"""
    wb = Workbook()
    ws = wb.active
    ws.title = "客户归属导入模板"
    ws.append(["客户ID(company_id)", "业务员ID(user_id)", "业务员属性(开发/分配)",
               "一级主管ID(user_id)", "一级主管属性(开发/分配)", "二级主管ID(user_id)"])

    # 设置列宽
    for col in ["A", "B", "C", "D", "E", "F"]:
        ws.column_dimensions[col].width = 22

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=customer_snapshot_template.xlsx"},
    )
