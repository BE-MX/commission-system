"""Local fulfillment money components; callers hold book then order locks.

Receipt principal and customer fee are separately conserved. The settlement
quote is the single source for planned batch fees; bank costs stay on Batch.
"""
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from app.finance import service as finance
from app.invoice.settlement_models import ReceiptBatch, Receivable, SettlementApplication
from app.receipt.models import Receipt

ZERO = Decimal("0")


def sources(db, invoice):
    # The book serializes all local money writers, so current-read discovery is
    # stable. Lock payment parents before AR and allocation children.
    rows = db.scalars(select(Receipt).where(Receipt.invoice_id == invoice.id, Receipt.source == "local")
                      .order_by(Receipt.id).with_for_update().execution_options(populate_existing=True)).all()
    batches = {identity: finance.lock(db, ReceiptBatch, identity) for identity in sorted({row.batch_id for row in rows})}
    targets = {row.id: row for row in db.scalars(select(Receivable).where(Receivable.invoice_id == invoice.id)
        .order_by(Receivable.id).with_for_update().execution_options(populate_existing=True)).all()}
    effective = [row for row in rows if row.status == "active" and row.collect_status == 1
                 and batches[row.batch_id].finance_status == "confirmed"]
    return effective, targets


def ensure_event_date(db, invoice_id, day, settlement_id=None):
    from app.invoice.models import InvoiceCommerceEvent
    query = select(InvoiceCommerceEvent).where(InvoiceCommerceEvent.invoice_id == invoice_id,
        InvoiceCommerceEvent.payload["settlement_id"].as_integer().isnot(None))
    if settlement_id is not None:
        query = query.where(InvoiceCommerceEvent.payload["settlement_id"].as_integer() == settlement_id)
    events = db.scalars(query.with_for_update().execution_options(populate_existing=True)).all()
    if any(date.fromisoformat(event.payload["body"]["business_date"]) > day for event in events):
        raise ValueError("业务日期不能早于已有发货动作")


def deposit_totals(rows):
    deposits = [row for row in rows if row.purpose == "presale_deposit"]
    return sum((row.effective_amount for row in deposits), ZERO), sum((row.effective_bank_charge for row in deposits), ZERO)


def requirements(settlement):
    quote = settlement.quote
    return {"goods": (Decimal(quote["goods_payment_due"]), Decimal(quote["goods_payment_charge"])),
            "freight": (Decimal(quote["freight_amount"]), ZERO),
            "deposit": (Decimal(quote["deposit_applied"]), Decimal(quote["deposit_charge_applied"]))}


def applications(db, invoice):
    from app.invoice.settlement_models import ShipmentSettlement
    return db.scalars(select(SettlementApplication).join(ShipmentSettlement,
        ShipmentSettlement.id == SettlementApplication.settlement_id).where(ShipmentSettlement.invoice_id == invoice.id)
        .order_by(SettlementApplication.id).with_for_update().execution_options(populate_existing=True)).all()


def totals(apps, settlement_id, component):
    selected = [app for app in apps if app.settlement_id == settlement_id and app.component == component and app.status != "released"]
    return sum((app.effective_amount for app in selected), ZERO), sum((app.effective_bank_charge for app in selected), ZERO)


def component_for(receipt, target):
    return "freight" if target.kind == "freight" else "deposit" if receipt.purpose == "presale_deposit" else "goods"


def validate(db, invoice, settlement, rows, targets, apps, *, complete):
    by_id = {row.id: row for row in rows}
    for app in [a for a in apps if a.status != "released"]:
        row = by_id.get(app.receipt_id)
        if row is None:
            raise ValueError("发货占用的核销已失效，请核对资金")
        used = [a for a in apps if a.receipt_id == row.id and a.status != "released"]
        amount = sum((a.effective_amount for a in used), ZERO)
        fee = sum((a.effective_bank_charge for a in used), ZERO)
        if fee > row.effective_bank_charge or amount - fee > row.effective_amount - row.effective_bank_charge or amount > row.effective_amount:
            raise ValueError("发货占用超过有效核销本金或费用")
        if app.settlement_id == settlement.id:
            target = targets[row.receivable_id]
            if (row.currency != invoice.currency or target.invoice_id != invoice.id
                    or component_for(row, target) != app.component
                    or (app.component == "freight" and invoice.order_type == "presale" and target.settlement_id != settlement.id)):
                raise ValueError("发货资金的客户、币种或应收组成不匹配")
    for component, required in requirements(settlement).items():
        actual = totals(apps, settlement.id, component)
        if actual[0] > required[0] or actual[1] > required[1] or (complete and actual != required):
            raise ValueError("本批已确认货款、运费或费用组成不足或超额")


def fund(db, invoice, settlement, rows, targets, apps, business_date):
    validate(db, invoice, settlement, rows, targets, apps, complete=False)
    for component, required in requirements(settlement).items():
        used_amount, used_fee = totals(apps, settlement.id, component)
        need_fee = required[1] - used_fee
        need_principal = required[0] - required[1] - (used_amount - used_fee)
        for row in rows:
            if row.collection_date > business_date:
                continue
            target = targets[row.receivable_id]
            if component_for(row, target) != component or (component == "freight" and invoice.order_type == "presale" and target.settlement_id != settlement.id):
                continue
            used = [a for a in apps if a.receipt_id == row.id and a.status != "released"]
            available_fee = row.effective_bank_charge - sum((a.effective_bank_charge for a in used), ZERO)
            available_principal = row.effective_amount - row.effective_bank_charge - sum((a.effective_amount - a.effective_bank_charge for a in used), ZERO)
            fee, principal = min(need_fee, available_fee), min(need_principal, available_principal)
            if fee + principal <= 0:
                continue
            app = next((a for a in apps if a.receipt_id == row.id and a.settlement_id == settlement.id and a.component == component), None)
            if app is None:
                app = SettlementApplication(settlement_id=settlement.id, receipt_id=row.id, component=component,
                    amount=0, bank_charge=0, status="reserved")
                db.add(app)
                apps.append(app)
            if app.status == "released":
                app.amount, app.bank_charge, app.status = ZERO, ZERO, "reserved"
                app.released_amount, app.released_bank_charge = ZERO, ZERO
            app.amount += fee + principal
            app.bank_charge += fee
            need_fee, need_principal = need_fee - fee, need_principal - principal
        if need_fee or need_principal:
            raise ValueError("本批已确认货款、运费或费用组成不足，请先核销付款")
    db.flush()
    validate(db, invoice, settlement, rows, targets, apps, complete=True)
