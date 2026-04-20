"""客户归属快照管理路由"""

import tempfile
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, UploadFile, File, Query, Path
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_db
from app.models.customer import CustomerCommissionSnapshot
from app.models.business import UserBasic, CustomerInfo
from app.schemas.common import ResponseModel, PageResponse
from app.schemas.customer import (
    CustomerSnapshotListItem, CustomerSnapshotCreateRequest,
    CustomerSnapshotCompleteRequest, CustomerSnapshotResetRequest,
    CustomerImportResult,
)
from app.services.customer_reset_service import (
    reset_customer_attribution, complete_snapshot, import_snapshots_from_excel,
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

    query = db.query(
        CustomerCommissionSnapshot,
        CustomerInfo.company_name.label("customer_name"),
        SpUser.full_name.label("salesperson_name"),
        SvUser.full_name.label("supervisor_name"),
    ).outerjoin(
        CustomerInfo,
        CustomerCommissionSnapshot.customer_id == CustomerInfo.company_id,
    ).outerjoin(
        SpUser,
        CustomerCommissionSnapshot.salesperson_id == SpUser.user_id,
    ).outerjoin(
        SvUser,
        CustomerCommissionSnapshot.supervisor_id == SvUser.user_id,
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
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for snap, customer_name, sp_name, sv_name in rows:
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
            is_complete=snap.is_complete,
            source=snap.source,
            first_order_id=snap.first_order_id,
            first_order_date=snap.first_order_date,
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

    sp_rate, sv_rate, _ = calc_commission_rates(
        req.salesperson_id, req.salesperson_attribute,
        req.supervisor_id, req.supervisor_attribute,
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
    snapshot = complete_snapshot(
        db,
        snapshot_id=snapshot_id,
        salesperson_attribute=req.salesperson_attribute,
        supervisor_attribute=req.supervisor_attribute,
        operator="api",
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


@router.get("/snapshot/template", summary="下载客户归属导入模板")
def download_snapshot_template():
    """下载客户归属 Excel 导入模板"""
    wb = Workbook()
    ws = wb.active
    ws.title = "客户归属导入模板"
    ws.append(["客户ID(company_id)", "业务员ID(user_id)", "业务员属性(开发/分配)",
               "业务主管ID(user_id)", "主管属性(开发/分配)"])

    # 设置列宽
    for col in ["A", "B", "C", "D", "E"]:
        ws.column_dimensions[col].width = 22

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=customer_snapshot_template.xlsx"},
    )
