"""Regenerate both customs workbooks from checked source rows in a single transaction."""
from io import BytesIO

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from sqlalchemy import select

from app.core.config import get_settings
from app.core.time import beijing_now
from app.cross_border.import_service import write_transaction
from app.cross_border.match_service import build_rows
from app.cross_border.models import Declaration, ExportBatch, Receipt, Review
from app.cross_border.parser import BASE, FIELDS, HEAD, LABELS, LINE, NUMERIC, RECEIPT
from app.cross_border.review_service import annotate


def make_workbook(sheet_names, documents, stamp, mode, dxp_id):
    book = Workbook(write_only=True)
    for sheet_name in sheet_names:
        sheet = book.create_sheet(sheet_name)
        sheet.append(LABELS[sheet_name])
        sheet.append(FIELDS[sheet_name])
        for document in documents:
            values = dict(document[sheet_name])
            if sheet_name == BASE:
                values.update(dxpMode=mode, dxpId=dxp_id)
            elif sheet_name in (HEAD, RECEIPT):
                values["appTime"] = stamp
            cells = []
            for field in FIELDS[sheet_name]:
                value = values[field]
                if sheet_name == LINE and field in NUMERIC[LINE]:
                    cells.append(float(value))
                elif not value:
                    cells.append(None)
                else:
                    cell = WriteOnlyCell(sheet, value=value)
                    # Imported text including a leading '=' stays literal in the downloaded workbook.
                    cell.data_type = "s"
                    cells.append(cell)
            sheet.append(cells)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def create_export(db, body, actor):
    config = get_settings()
    if not config.CROSS_BORDER_DXP_MODE.strip() or not config.CROSS_BORDER_DXP_ID.strip():
        raise HTTPException(409, "请先配置报文传输模式和传输编号")
    selected = set(body.content_hashes)
    with write_transaction(db, freeze_sources=True):
        declarations = db.scalars(select(Declaration).where(Declaration.content_hash.in_(selected))
                                  .order_by(Declaration.first_import_id, Declaration.first_row_no)).all()
        if len(declarations) != len(selected):
            raise HTTPException(409, "部分申报已不存在，请刷新后重选")
        rows = {r["content_hash"]: r for r in annotate(build_rows(db, order_nos={d.order_no for d in declarations}))
                if r["row_type"] == "declaration"}
        chosen = [rows[d.content_hash] for d in declarations]
        if any(not r["can_export"] or not r["receipt_hash"] for r in chosen):
            raise HTTPException(409, "所选申报仍有阻断异常、已排除或作废，请刷新核对")
        if any(r["exported"] for r in chosen) and not body.confirm_reexport:
            raise HTTPException(409, "所选申报已有导出记录，请明确确认再次导出")
        suspects = [r for r in chosen if r["needs_suspected_confirmation"]]
        if suspects and not (body.confirm_suspected and body.reason):
            raise HTTPException(409, "同一订单号存在可能已修改的申报，请核实并说明原因")
        receipt_ids = {r["receipt_hash"] for r in chosen}
        if len(receipt_ids) != len(chosen):
            raise HTTPException(409, "收款单无法逐条对应，请重新核对")
        receipts = {r.content_hash: r for r in db.scalars(select(Receipt).where(Receipt.content_hash.in_(receipt_ids)))}
        orders, payments = [], []
        for declaration, row in zip(declarations, chosen):
            receipt = receipts[row["receipt_hash"]]
            orders.append({HEAD: declaration.head_json, LINE: declaration.line_json, BASE: declaration.base_json})
            payments.append({RECEIPT: receipt.receipt_json, BASE: receipt.base_json})
        now = beijing_now()
        args = (now.strftime("%Y%m%d%H%M%S"), config.CROSS_BORDER_DXP_MODE, config.CROSS_BORDER_DXP_ID)
        batch = ExportBatch(created_by=actor, created_at=now, content_hashes=[d.content_hash for d in declarations],
                            order_file=make_workbook((HEAD, LINE, BASE), orders, *args),
                            receipt_file=make_workbook((RECEIPT, BASE), payments, *args))
        db.add(batch)
        for row in suspects:
            db.add(Review(content_hash=row["content_hash"], action="confirm_suspected", reason=body.reason,
                          created_by=actor, created_at=now))
        db.flush()
        identity = batch.id
    return {"id": identity}


def get_file(db, identity, kind):
    column = ExportBatch.order_file if kind == "order" else ExportBatch.receipt_file
    data = db.scalar(select(column).where(ExportBatch.id == identity))
    if data is None:
        raise HTTPException(404, "找不到该导出文件")
    return data
