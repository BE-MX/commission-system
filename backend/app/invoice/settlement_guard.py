"""Current state fence for receipts belonging to a presale shipment."""
from decimal import Decimal
from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement, Receivable
from app.invoice.models import Invoice
from app.receipt.models import Receipt


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
    if settlement.quote.get("funding_version") == 2:
        _validate_current_payment(db, receipt, application, settlement, current=current)
    return settlement


def _validate_current_payment(db, receipt, application, settlement, *, current=False):
    """Positive authorization for V2 shortfall payments outside the legacy cap."""
    invoice = db.get(Invoice, settlement.invoice_id)
    target_query = db.query(Receivable).filter(Receivable.id == receipt.receivable_id)
    if current:
        target_query = target_query.populate_existing().with_for_update()
    target = target_query.one_or_none()
    component = "freight" if receipt.purpose == "freight" else "goods"
    expected_key = f"settlement:{settlement.id}:freight" if component == "freight" else f"invoice:{settlement.invoice_id}:goods"
    if (invoice is None or invoice.order_type != "presale" or receipt.status != "active"
            or receipt.amount <= 0 or receipt.bank_charge < 0 or receipt.bank_charge >= receipt.amount
            or receipt.customer_id != invoice.customer_id or receipt.currency != invoice.currency
            or settlement.quote.get("currency") != invoice.currency or application.component != component
            or application.amount != receipt.amount or application.bank_charge != receipt.bank_charge
            or target is None or target.invoice_id != invoice.id or target.business_key != expected_key
            or target.kind != component or target.customer_id != invoice.customer_id or target.currency != invoice.currency
            or target.settlement_id != (settlement.id if component == "freight" else None)
            or target.remote_order_id != receipt.xiaoman_order_id
            or component == "goods" and target.remote_order_id != invoice.xiaoman_order_id
            or component == "freight" and receipt.bank_charge):
        raise ValueError("本批补款与冻结资金分配或应收目标不一致，暂停发送")
    query = db.query(SettlementApplication, Receipt).join(Receipt, Receipt.id == SettlementApplication.receipt_id).filter(
        SettlementApplication.settlement_id == settlement.id, SettlementApplication.status != "released")
    if current:
        query = query.order_by(SettlementApplication.id, Receipt.id).populate_existing().with_for_update()
    linked = query.all()
    from app.invoice import presale_runtime, settlement_service
    nonpool = [(app, row) for app, row in linked if row.purpose not in presale_runtime.POOL_PURPOSES]
    for app, row in nonpool:
        if (row.invoice_id != invoice.id or row.customer_id != invoice.customer_id or row.currency != invoice.currency
                or row.status != "active" or app.amount != row.amount or app.bank_charge != row.bank_charge
                or app.component != ("freight" if row.purpose == "freight" else "goods")
                or row.purpose not in {"presale_goods", "freight"}):
            raise ValueError("本批补款资金关联异常，暂停发送")
    goods = sum((app.amount for app, _ in nonpool if app.component == "goods"), Decimal(0))
    freight = sum((app.amount for app, _ in nonpool if app.component == "freight"), Decimal(0))
    charge = sum((app.bank_charge for app, _ in nonpool), Decimal(0))
    if (goods > Decimal(settlement.quote["goods_payment_due"])
            or freight > Decimal(settlement.quote["freight_payment_due"])
            or charge > Decimal(settlement.quote["goods_payment_charge"])):
        raise ValueError("本批补款超过冻结的资金缺口，暂停发送")
    settlement_service.funding_balance(db, settlement, current=current)


def ensure_receipt_sendable(db, receipt, *, current=False):
    settlement = receipt_settlement(db, receipt, current=current)
    if settlement and settlement.state not in SENDABLE_STATES:
        raise ValueError("本批结算已暂停或进入出库流程，回款不能继续发送")
    return settlement
