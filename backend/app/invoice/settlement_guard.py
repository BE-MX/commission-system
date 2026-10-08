"""Current state fence for receipts belonging to a presale shipment."""
from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement


SENDABLE_STATES = {"awaiting_payment", "awaiting_verification", "ready"}


def receipt_settlement(db, receipt, *, current=False):
    if not receipt.batch_id or receipt.purpose not in {"presale_goods", "freight"}:
        return None
    query = db.query(SettlementApplication).filter(
        SettlementApplication.receipt_id == receipt.id,
        SettlementApplication.status != "released",
    )
    if current:
        query = query.populate_existing().with_for_update()
    application = query.one_or_none()
    if not application:
        raise ValueError("预售回款未关联有效结算，暂停发送")
    settlement = (db.query(ShipmentSettlement).filter_by(id=application.settlement_id)
        .populate_existing().with_for_update().one_or_none()) if current else db.get(ShipmentSettlement, application.settlement_id)
    if not settlement or settlement.invoice_id != receipt.invoice_id:
        raise ValueError("预售回款结算身份异常，暂停发送")
    return settlement


def ensure_receipt_sendable(db, receipt, *, current=False):
    settlement = receipt_settlement(db, receipt, current=current)
    if settlement and settlement.state not in SENDABLE_STATES:
        raise ValueError("本批结算已暂停或进入出库流程，回款不能继续发送")
    return settlement
