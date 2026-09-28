"""Current state fence for receipts belonging to a presale shipment."""
from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement


SENDABLE_STATES = {"awaiting_payment", "awaiting_verification", "ready"}


def receipt_settlement(db, receipt):
    if not receipt.batch_id or receipt.purpose not in {"presale_goods", "freight"}:
        return None
    application = db.query(SettlementApplication).filter(
        SettlementApplication.receipt_id == receipt.id,
        SettlementApplication.status != "released",
    ).one_or_none()
    if not application:
        raise ValueError("预售回款未关联有效结算，暂停发送")
    settlement = db.get(ShipmentSettlement, application.settlement_id)
    if not settlement or settlement.invoice_id != receipt.invoice_id:
        raise ValueError("预售回款结算身份异常，暂停发送")
    return settlement


def ensure_receipt_sendable(db, receipt):
    settlement = receipt_settlement(db, receipt)
    if settlement and settlement.state not in SENDABLE_STATES:
        raise ValueError("本批结算已暂停或进入出库流程，回款不能继续发送")
    return settlement
