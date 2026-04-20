"""报表导出路由"""

from collections import defaultdict
from decimal import Decimal
from io import BytesIO

from fastapi import APIRouter, Depends, Query, Path
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_db
from app.models.commission import CommissionBatch, CommissionDetail
from app.models.business import UserBasic, CustomerInfo

router = APIRouter()

HEADER_FONT = Font(bold=True)
HEADER_FILL = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center")

DETAIL_COLUMNS = [
    "回款ID", "订单ID", "客户ID", "客户名称", "回款金额",
    "业务员ID", "业务员", "业务员比例", "业务员提成",
    "主管ID", "主管", "主管比例", "主管提成", "计算规则", "状态",
]


def _style_header(ws, columns):
    """为表头行应用样式"""
    for col_idx, col_name in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN


def _write_detail_row(ws, row_num, d, customer_name, sp_name, sv_name):
    """写入一行明细数据"""
    ws.cell(row=row_num, column=1, value=d.payment_id)
    ws.cell(row=row_num, column=2, value=d.order_id)
    ws.cell(row=row_num, column=3, value=d.customer_id)
    ws.cell(row=row_num, column=4, value=customer_name or "")
    ws.cell(row=row_num, column=5, value=float(d.payment_amount))
    ws.cell(row=row_num, column=6, value=d.salesperson_id)
    ws.cell(row=row_num, column=7, value=sp_name or "")
    ws.cell(row=row_num, column=8, value=float(d.salesperson_rate))
    ws.cell(row=row_num, column=9, value=float(d.salesperson_commission))
    ws.cell(row=row_num, column=10, value=d.supervisor_id or "")
    ws.cell(row=row_num, column=11, value=sv_name or "")
    ws.cell(row=row_num, column=12, value=float(d.supervisor_rate) if d.supervisor_rate else 0)
    ws.cell(row=row_num, column=13, value=float(d.supervisor_commission))
    ws.cell(row=row_num, column=14, value=d.calc_rule_note or "")
    ws.cell(row=row_num, column=15, value=d.status)


def _add_subtotal_row(ws, row_num, count):
    """写入小计行"""
    bold = Font(bold=True)
    ws.cell(row=row_num, column=4, value="小计").font = bold
    ws.cell(row=row_num, column=5, value=f"=SUM(E2:E{row_num - 1})").font = bold
    ws.cell(row=row_num, column=9, value=f"=SUM(I2:I{row_num - 1})").font = bold
    ws.cell(row=row_num, column=13, value=f"=SUM(M2:M{row_num - 1})").font = bold


def _query_details(db: Session, batch_id: int):
    """查询批次全部明细，含名称"""
    SpUser = aliased(UserBasic)
    SvUser = aliased(UserBasic)

    return db.query(
        CommissionDetail,
        CustomerInfo.company_name.label("customer_name"),
        SpUser.full_name.label("salesperson_name"),
        SvUser.full_name.label("supervisor_name"),
    ).outerjoin(
        CustomerInfo, CommissionDetail.customer_id == CustomerInfo.company_id,
    ).outerjoin(
        SpUser, CommissionDetail.salesperson_id == SpUser.user_id,
    ).outerjoin(
        SvUser, CommissionDetail.supervisor_id == SvUser.user_id,
    ).filter(
        CommissionDetail.batch_id == batch_id,
        CommissionDetail.status != "voided",
    ).all()


def _to_streaming(wb: Workbook, filename: str) -> StreamingResponse:
    """将 Workbook 转为 StreamingResponse"""
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/commission/{batch_id}/export", summary="导出提成明细Excel")
def export_commission_details(
    batch_id: int = Path(..., description="批次ID"),
    group_by: str = Query("", description="分组方式: salesperson/supervisor/customer"),
    db: Session = Depends(get_db),
):
    """导出提成明细 Excel，支持按业务员/主管/客户分sheet"""
    batch = db.query(CommissionBatch).filter(CommissionBatch.id == batch_id).first()
    if not batch:
        return {"code": 404, "message": f"批次 {batch_id} 不存在", "data": None}

    rows = _query_details(db, batch_id)

    wb = Workbook()
    wb.remove(wb.active)

    if not group_by:
        ws = wb.create_sheet("全部明细")
        _style_header(ws, DETAIL_COLUMNS)
        for idx, (d, cname, spname, svname) in enumerate(rows, start=2):
            _write_detail_row(ws, idx, d, cname, spname, svname)
        if rows:
            _add_subtotal_row(ws, len(rows) + 2, len(rows))
    else:
        groups = defaultdict(list)
        for d, cname, spname, svname in rows:
            if group_by == "salesperson":
                key = spname or d.salesperson_id
            elif group_by == "supervisor":
                key = svname or (d.supervisor_id or "无主管")
            else:
                key = cname or d.customer_id
            groups[key].append((d, cname, spname, svname))

        for group_name, group_rows in groups.items():
            sheet_name = str(group_name)[:31]
            ws = wb.create_sheet(sheet_name)
            _style_header(ws, DETAIL_COLUMNS)
            for idx, (d, cname, spname, svname) in enumerate(group_rows, start=2):
                _write_detail_row(ws, idx, d, cname, spname, svname)
            _add_subtotal_row(ws, len(group_rows) + 2, len(group_rows))

    if not wb.sheetnames:
        ws = wb.create_sheet("空")
        ws.cell(row=1, column=1, value="无数据")

    return _to_streaming(wb, f"commission_details_{batch.batch_name}.xlsx")


@router.get("/commission/{batch_id}/salesperson-summary", summary="导出业务员提成汇总Excel")
def export_salesperson_summary(
    batch_id: int = Path(..., description="批次ID"),
    db: Session = Depends(get_db),
):
    """导出业务员提成汇总 Excel"""
    batch = db.query(CommissionBatch).filter(CommissionBatch.id == batch_id).first()
    if not batch:
        return {"code": 404, "message": f"批次 {batch_id} 不存在", "data": None}

    results = db.query(
        CommissionDetail.salesperson_id,
        UserBasic.full_name,
        func.count(CommissionDetail.id).label("payment_count"),
        func.sum(CommissionDetail.payment_amount).label("total_amount"),
        CommissionDetail.salesperson_rate,
        func.sum(CommissionDetail.salesperson_commission).label("total_commission"),
    ).outerjoin(
        UserBasic, CommissionDetail.salesperson_id == UserBasic.user_id,
    ).filter(
        CommissionDetail.batch_id == batch_id,
        CommissionDetail.status != "voided",
    ).group_by(
        CommissionDetail.salesperson_id,
        UserBasic.full_name,
        CommissionDetail.salesperson_rate,
    ).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "业务员提成汇总"

    columns = ["业务员ID", "姓名", "回款笔数", "回款总额", "提成比例", "提成金额"]
    _style_header(ws, columns)

    for idx, r in enumerate(results, start=2):
        ws.cell(row=idx, column=1, value=r.salesperson_id)
        ws.cell(row=idx, column=2, value=r.full_name or "")
        ws.cell(row=idx, column=3, value=r.payment_count)
        ws.cell(row=idx, column=4, value=float(r.total_amount or 0))
        ws.cell(row=idx, column=5, value=float(r.salesperson_rate or 0))
        ws.cell(row=idx, column=6, value=float(r.total_commission or 0))

    return _to_streaming(wb, f"salesperson_summary_{batch.batch_name}.xlsx")


@router.get("/commission/{batch_id}/supervisor-summary", summary="导出主管提成汇总Excel")
def export_supervisor_summary(
    batch_id: int = Path(..., description="批次ID"),
    db: Session = Depends(get_db),
):
    """导出主管提成汇总 Excel"""
    batch = db.query(CommissionBatch).filter(CommissionBatch.id == batch_id).first()
    if not batch:
        return {"code": 404, "message": f"批次 {batch_id} 不存在", "data": None}

    results = db.query(
        CommissionDetail.supervisor_id,
        UserBasic.full_name,
        func.count(func.distinct(CommissionDetail.salesperson_id)).label("sp_count"),
        func.sum(CommissionDetail.payment_amount).label("total_amount"),
        CommissionDetail.supervisor_rate,
        func.sum(CommissionDetail.supervisor_commission).label("total_commission"),
    ).outerjoin(
        UserBasic, CommissionDetail.supervisor_id == UserBasic.user_id,
    ).filter(
        CommissionDetail.batch_id == batch_id,
        CommissionDetail.status != "voided",
        CommissionDetail.supervisor_id.isnot(None),
    ).group_by(
        CommissionDetail.supervisor_id,
        UserBasic.full_name,
        CommissionDetail.supervisor_rate,
    ).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "主管提成汇总"

    columns = ["主管ID", "姓名", "管辖业务员数", "管辖回款总额", "提成比例", "提成金额"]
    _style_header(ws, columns)

    for idx, r in enumerate(results, start=2):
        ws.cell(row=idx, column=1, value=r.supervisor_id or "")
        ws.cell(row=idx, column=2, value=r.full_name or "")
        ws.cell(row=idx, column=3, value=r.sp_count)
        ws.cell(row=idx, column=4, value=float(r.total_amount or 0))
        ws.cell(row=idx, column=5, value=float(r.supervisor_rate or 0))
        ws.cell(row=idx, column=6, value=float(r.total_commission or 0))

    return _to_streaming(wb, f"supervisor_summary_{batch.batch_name}.xlsx")
