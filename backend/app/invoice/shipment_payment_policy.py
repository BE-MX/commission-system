"""Frozen batch payment terms; credit never manufactures an effective receipt."""
from app.invoice.settlement_models import SettlementApplication
from app.receipt.models import Receipt, ReceiptLog

PAY_FIRST = "pay_first"
SHIP_FIRST = "ship_first"
PAYMENT_STATES = {"awaiting_payment", "awaiting_verification"}
CREDIT_PAYMENT_STATES = PAYMENT_STATES | {"ready", "outbound_pending", "shipped"}


def term(row):
    value = row.quote.get("payment_term", PAY_FIRST)
    if value not in {PAY_FIRST, SHIP_FIRST} or value == SHIP_FIRST and row.quote.get("funding_version") != 2:
        raise ValueError("发货批次结算方式异常，请核对原单")
    return value


def is_credit(row):
    return term(row) == SHIP_FIRST


def accepts_payment(row):
    return row.state in (CREDIT_PAYMENT_STATES if is_credit(row) else PAYMENT_STATES)


def receipt_effective(receipt):
    return (receipt.status == "active" and receipt.sync_status == "synced"
        and receipt.collect_status == 1 and not receipt.last_error and bool(receipt.xiaoman_receipt_id))


def requires_effective(db, app, receipt, *, current=False):
    from app.invoice.presale_runtime import POOL_PURPOSES
    if receipt.purpose in POOL_PURPOSES or app.status == "applied":
        return True
    query = db.query(ReceiptLog.id).filter(ReceiptLog.receipt_id == receipt.id,
        ReceiptLog.action == "credit_effective")
    if current:
        query = query.with_for_update()
    return query.first() is not None


def credit_funding_valid(db, row, *, current=False):
    """An uncollected credit payment is debt; a revoked real payment is an anomaly."""
    from app.invoice import settlement_guard, settlement_service
    if not is_credit(row):
        return False
    try:
        settlement_service.funding_balance(db, row, current=current)
        query = db.query(SettlementApplication, Receipt).join(Receipt,
            Receipt.id == SettlementApplication.receipt_id).filter(
                SettlementApplication.settlement_id == row.id, SettlementApplication.status != "released")
        if current:
            query = query.order_by(SettlementApplication.id, Receipt.id).populate_existing().with_for_update()
        from app.invoice.presale_runtime import POOL_PURPOSES
        for app, receipt in query.all():
            if receipt.status != "active":
                return False
            if receipt.purpose not in POOL_PURPOSES:
                settlement_guard._validate_current_payment(db, receipt, app, row, current=current)
            if requires_effective(db, app, receipt, current=current):
                if not receipt_effective(receipt):
                    return False
            elif receipt.xiaoman_receipt_id:
                if receipt.sync_status != "synced" or receipt.collect_status not in {0, 1} or receipt.last_error:
                    return False
            elif receipt.sync_status not in {"waiting_target", "pending", "failed", "syncing", "uncertain"}:
                return False
        return True
    except ValueError:
        return False


def record_effective(db, receipt, actor):
    """Persist that a credit payment was once real, even if later revoked."""
    from app.invoice.settlement_models import ShipmentSettlement
    from app.receipt import service
    if receipt.collect_status != 1 or not receipt.batch_id or receipt.purpose not in {"presale_goods", "freight"}:
        return
    row = db.query(ShipmentSettlement).join(SettlementApplication,
        SettlementApplication.settlement_id == ShipmentSettlement.id).filter(
            SettlementApplication.receipt_id == receipt.id,
            SettlementApplication.status != "released").one_or_none()
    if row is not None and is_credit(row) and not db.query(ReceiptLog.id).filter(
            ReceiptLog.receipt_id == receipt.id, ReceiptLog.action == "credit_effective").first():
        service.log(db, receipt, "credit_effective", "先出库批次回款已生效，保留原资金事实", actor)
