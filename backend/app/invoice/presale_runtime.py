"""Locked presale funding references; existing receipt facts remain immutable."""
from decimal import Decimal, InvalidOperation
from app.invoice.presale_funding import FundingLot
from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement
from app.receipt.models import Receipt
from app.receipt import remote

POOL_PURPOSES = {"presale_deposit", "presale_advance"}


def required(quote):
    return Decimal(quote["funding_total_amount"]) if quote.get("funding_version") == 2 else (
        Decimal(quote["new_payment_due"]) + Decimal(quote["deposit_applied"]))


def source_component(app, receipt):
    return "goods" if receipt.purpose in POOL_PURPOSES else app.component


def released_legacy_deposit_matches(app, settlement, receipt, invoice):
    """A cancelled V1 whole-deposit reference retains its original money facts."""
    quote = settlement.quote
    try:
        amount = Decimal(str(quote['deposit_applied']))
        charge = Decimal(str(quote['deposit_charge_applied']))
        return (quote.get('funding_version') in {None, 1} and app.component == 'deposit'
            and settlement.state == 'cancelled' and app.status == 'released'
            and app.settlement_id == settlement.id and settlement.invoice_id == invoice.id
            and receipt.invoice_id == invoice.id
            and receipt.customer_id == invoice.customer_id and receipt.currency == invoice.currency
            and settlement.is_final == 1 and quote.get('currency') == invoice.currency
            and quote.get('deposit_receipt_id') == receipt.id and app.receipt_id == receipt.id
            and receipt.purpose in POOL_PURPOSES and receipt.xiaoman_order_id == invoice.xiaoman_order_id
            and amount.is_finite() and charge.is_finite() and amount > 0 and 0 <= charge < amount
            and app.amount == amount == receipt.amount and app.bank_charge == charge == receipt.bank_charge)
    except (InvalidOperation, KeyError, TypeError, ValueError, AttributeError):
        return False


def pool_lots(db, invoice, snapshot=None, *, current=False):
    query = db.query(Receipt).filter(Receipt.invoice_id == invoice.id,
        Receipt.purpose.in_(POOL_PURPOSES))
    if current:
        query = query.order_by(Receipt.id).populate_existing().with_for_update()
    receipts = query.all()
    query = db.query(SettlementApplication, ShipmentSettlement).join(ShipmentSettlement,
        ShipmentSettlement.id == SettlementApplication.settlement_id).filter(
            SettlementApplication.receipt_id.in_([row.id for row in receipts]))
    if current:
        query = query.order_by(SettlementApplication.id).populate_existing().with_for_update()
    applications = query.all()
    rows = {str(row["cash_collection_id"]): row for row in snapshot["rows"]} if snapshot else None
    lots = []
    for receipt in receipts:
        if (receipt.customer_id != invoice.customer_id or receipt.currency != invoice.currency
                or receipt.xiaoman_order_id != invoice.xiaoman_order_id):
            raise ValueError("预售资金池回款身份已变化，请核对原单")
        used = charge = Decimal(0)
        for app, settlement in applications:
            if app.receipt_id != receipt.id:
                continue
            if (settlement.invoice_id != invoice.id or app.status not in {"reserved", "applied", "released"}
                    or app.amount <= 0 or app.bank_charge < 0 or app.bank_charge > app.amount
                    or app.component not in {"goods", "freight", "deposit"}
                    or app.status != "released" and (
                        app.component == "freight" and (receipt.purpose != "presale_advance" or app.bank_charge)
                        or app.component == "deposit" and receipt.purpose != "presale_deposit"
                        or receipt.purpose == "presale_deposit" and not settlement.is_final)
                    or settlement.state == "cancelled" and app.status != "released"):
                raise ValueError("预售资金池结算关联异常，请核对原单")
            if app.status != "released":
                used += app.amount; charge += app.bank_charge
        if (used > receipt.amount or charge > receipt.bank_charge or charge > used
                or used - charge > receipt.amount - receipt.bank_charge):
            raise ValueError("预售资金池已被其他结算占用或分配超额")
        effective = (receipt.status == "active" and receipt.sync_status == "synced"
            and receipt.collect_status == 1 and not receipt.last_error)
        if rows is not None and effective:
            counterpart = rows.get(str(receipt.xiaoman_receipt_id))
            effective = bool(counterpart and str(counterpart.get("collect_status")) == "1"
                and counterpart.get("currency") == receipt.currency
                and remote.money(counterpart.get("amount")) == remote.net_amount(receipt))
        if receipt.status == "active":
            lots.append(FundingLot(receipt.id, receipt.purpose, str(receipt.amount),
                str(receipt.bank_charge), str(used), str(charge), bool(effective)))
    return receipts, lots


def validate_quote_applications(row, applications, receipts):
    if row.quote.get("funding_version") != 2:
        return
    if bool(row.is_final) != row.quote.get("is_final"):
        raise ValueError("原发货结算末批标记已变化，请核对原单")
    expected = sorted((part["receipt_id"], part["component"], part["purpose"],
        Decimal(part["amount"]), Decimal(part["bank_charge"]))
        for part in row.quote["pool_applications"])
    # A cancelled graph retains its original classification evidence after an
    # audited correction of the now-free receipt. IDs/amounts/fees stay exact.
    historical = {(identity, component): purpose for identity, component, purpose, _, _ in expected}
    cancelled = row.state == "cancelled" and all(app.status == "released" for app in applications)
    actual = sorted((app.receipt_id, app.component,
        historical.get((app.receipt_id, app.component), receipts[app.receipt_id].purpose)
            if cancelled else receipts[app.receipt_id].purpose,
        Decimal(app.amount), Decimal(app.bank_charge)) for app in applications
        if receipts[app.receipt_id].purpose in POOL_PURPOSES)
    if row.state == "cancelled" and not cancelled:
        raise ValueError("已取消发货结算仍有未释放资金，请核对原单")
    if actual != expected:
        raise ValueError("原发货结算资金池分配已变化，请核对原单")
