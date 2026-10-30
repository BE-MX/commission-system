"""Do not settle a return while pre-existing cash or shipment writers are active."""
from fastapi import HTTPException
from sqlalchemy import select

from app.invoice.models import Invoice, OkkiOutboundTask
from app.invoice.settlement_models import ShipmentSettlement
from app.invoice.shipment_cancellation_policy import CANCELLED_STATES
from app.receipt.models import Receipt, ReceiptIntent


def ensure_idle(db, snapshot):
    invoice_id = snapshot.get("invoice_id")
    if invoice_id is None:
        return
    invoice = db.get(Invoice, invoice_id)
    cancelling = invoice and invoice.cancellation and invoice.cancellation.get("status") != "aborted"
    if invoice is None or invoice.sync_status in {"syncing", "sync_uncertain"} or cancelling:
        raise HTTPException(409, "原订单正在同步、取消或待核对，请先完成原任务再生效退货")
    pending = db.scalar(select(Receipt.id).where(Receipt.invoice_id == invoice_id, Receipt.status == "active",
        (Receipt.sync_status != "synced") | Receipt.xiaoman_receipt_id.is_(None)).limit(1))
    if pending:
        raise HTTPException(409, "原订单存在未发送、执行中或结果待核对的回款，请先处理原回款")
    intent = db.scalar(select(ReceiptIntent.id).where(ReceiptIntent.invoice_id == invoice_id,
        ReceiptIntent.eligible == 1, ReceiptIntent.status.in_(["draft", "armed", "ready"]), ReceiptIntent.amount > 0).limit(1))
    if intent:
        raise HTTPException(409, "原订单尚有自动回款意图，请先核对原回款任务")
    if db.scalar(select(OkkiOutboundTask.id).where(OkkiOutboundTask.invoice_id == invoice_id,
            OkkiOutboundTask.status.notin_(["done", "skipped"])).limit(1)):
        raise HTTPException(409, "原订单仍有未完成的出库执行任务，请先核对原出库")
    if db.scalar(select(ShipmentSettlement.id).where(ShipmentSettlement.invoice_id == invoice_id,
            ShipmentSettlement.state.notin_(["shipped", *CANCELLED_STATES])).limit(1)):
        raise HTTPException(409, "原预售单仍有活动发货结算，请先完成或取消原批次")
