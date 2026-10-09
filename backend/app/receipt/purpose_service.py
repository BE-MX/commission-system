"""Audited presale classification; original cash facts are never edited."""
from fastapi import HTTPException
from sqlalchemy import select

from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement
from app.receipt import access, authority, service
from app.receipt.models import ReceiptIntent


def apply(db, row, invoice, body, actor):
    if row.version != body.version:
        raise HTTPException(409, "回款已变化，请刷新后重新核对用途")
    if (invoice.order_type != "presale" or row.purpose not in {"presale_deposit", "presale_advance"}
            or row.status != "active" or row.sync_status != "synced" or row.collect_status != 1
            or not row.xiaoman_receipt_id or row.last_error):
        raise ValueError("仅已核验生效的预售定金或预付货款可以更正用途")
    apps = db.scalars(select(SettlementApplication).where(
        SettlementApplication.receipt_id == row.id).order_by(SettlementApplication.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    if any(app.status != "released" for app in apps):
        raise ValueError("此款已被出库结算占用或扣减，请先核对原批次，不能更改用途")
    active = db.scalar(select(ShipmentSettlement.id).where(
        ShipmentSettlement.invoice_id == invoice.id,
        ShipmentSettlement.state.notin_(["cancelled", "shipped"]))
        .order_by(ShipmentSettlement.id).with_for_update())
    if active:
        raise ValueError("请先取消尚未付款、尚未同步的原发货结算，再更正收款用途")
    intent = db.scalar(select(ReceiptIntent).where(ReceiptIntent.receipt_id == row.id)
        .with_for_update().execution_options(populate_existing=True))
    if row.purpose == body.purpose:
        return row
    previous = row.purpose
    row.purpose = body.purpose
    row.version += 1
    if intent:
        intent.purpose = body.purpose
        intent.bank_charge = row.bank_charge
    service.log(db, row, "purpose_changed", f"Presale purpose {previous} -> {body.purpose}; {body.reason}", actor)
    db.flush()
    return row


def update(db, identity, body, user):
    row, invoice, current, _, _ = authority.local_group(db, identity, user,
        "receipt:write", "receipt:admin", any_permission=True)
    apply(db, row, invoice, body, access.user_id(current))
    return row, invoice
