"""Edit only the local receipt remark under the existing group authority."""
from fastapi import HTTPException
from sqlalchemy import select

from app.invoice.linked_sync_service import ensure_idle
from app.receipt import access, authority, service
from app.receipt.models import ReceiptIntent


def update(db, identity, body, user):
    row, invoice, current, batch, _ = authority.local_group(db, identity, user, "receipt:write")
    ensure_idle(invoice)
    if invoice.sync_status == "sync_uncertain" or invoice.status == "syncing":
        raise ValueError("订单正在同步或结果待核对，请先完成原订单恢复")
    if row.status != "active" or (batch is not None and batch.status != "active"):
        raise ValueError("仅有效回款单可修改备注")
    if row.sync_status == "syncing":
        raise ValueError("回款正在同步，请稍后刷新再修改备注")
    if row.version != body.version:
        raise HTTPException(409, "回款已被修改，请刷新后重新编辑备注")
    if (row.remark or "") != body.remark:
        row.remark = body.remark
        row.version += 1
        # The invoice editor's converted draft must remain identical to its receipt.
        intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.receipt_id == row.id)
            .with_for_update().execution_options(populate_existing=True))
        if intent is not None and intent.status == "converted":
            intent.remark = row.remark
        service.log(db, row, "remark", "修改回款备注（方舟留存）", access.user_id(current))
        db.flush()
    return row, invoice
