"""Partial allocation reversals preserve original cash and commission facts."""
from fastapi import HTTPException
from sqlalchemy import select

from app.finance import service as finance
from app.finance.models import FinanceEvent
from app.invoice.settlement_models import Receivable, SettlementApplication, ShipmentSettlement
from app.receipt.models import Receipt


def _components(row, amount, apps, exact_fee=None):
    """Reverse only free principal/fee; proportions cannot spend reserved fees."""
    effective, fee_left = row.effective_amount, row.effective_bank_charge
    occupied = [app for app in apps if app.status in {"reserved", "applied"}]
    used_amount = sum((app.effective_amount for app in occupied), finance.ZERO)
    used_fee = sum((app.effective_bank_charge for app in occupied), finance.ZERO)
    free_fee = finance.money(fee_left - used_fee)
    free_principal = finance.money(effective - fee_left - used_amount + used_fee)
    if free_fee < 0 or free_principal < 0 or amount > free_fee + free_principal:
        raise ValueError("冲回金额超过未占用核销余额，请先解除发货资金占用或办理退货")
    if exact_fee is not None:
        if exact_fee < 0 or exact_fee > min(amount, free_fee) or amount - exact_fee > free_principal:
            raise ValueError("售后冲回组成超过本次释放的可用本金或费用")
        return exact_fee
    ideal_fee = fee_left if amount == effective else finance.money(fee_left * amount / effective)
    # A partial receipt may have all its fee reserved and principal still free,
    # or the opposite. Both components of existing applications stay intact.
    fee = min(min(amount, free_fee), max(max(finance.ZERO, amount - free_principal), ideal_fee))
    return finance.money(fee)


def _commission(db, row, reversed_amount, reversed_fee):
    events = db.scalars(select(FinanceEvent).where(FinanceEvent.receipt_id == row.id,
        FinanceEvent.action.in_(["allocate", "opening_allocation", "reverse_allocation"]))
        .order_by(FinanceEvent.id).with_for_update().execution_options(populate_existing=True)).all()
    original = [event for event in events if event.action in {"allocate", "opening_allocation"}]
    if len(original) != 1:
        raise ValueError("原核销提成事件缺失或重复，禁止冲回")
    total_usd = original[0].commission_amount_usd
    prior_usd = -sum((event.commission_amount_usd for event in events if event.action == "reverse_allocation"), finance.ZERO)
    opening = original[0].payload.get("opening", {}) if original[0].action == "opening_allocation" else {}
    initial_reversed = finance.money(opening.get("reversed_amount", 0))
    initial_fee = finance.money(opening.get("reversed_bank_charge", 0))
    principal = row.amount - row.bank_charge - initial_reversed + initial_fee
    cumulative_principal = reversed_amount - reversed_fee - initial_reversed + initial_fee
    if reversed_amount == row.amount:
        cumulative_usd = total_usd
    elif principal:
        # Differences of cumulative rounded amounts preserve the original USD
        # event even across tiny partial refunds and later FX changes.
        cumulative_usd = finance.money(total_usd * cumulative_principal / principal)
    else:
        cumulative_usd = finance.ZERO
    if not finance.ZERO <= prior_usd <= cumulative_usd <= total_usd:
        raise ValueError("原核销提成冲回累计不一致，请核对事件")
    return finance.money(cumulative_usd - prior_usd)


def _aftersales_release(db, execution_id, row, body, user):
    """Only an audited execution in this transaction can release final deposits."""
    from decimal import Decimal
    from app.aftersales.models import AfterSalesCase, AfterSalesExecution
    from app.invoice.settlement_models import SettlementItem
    from app.receipt.access import user_id
    execution = finance.lock(db, AfterSalesExecution, execution_id)
    if (execution is None or execution.action != "money_execute" or execution.created_by != user_id(user)
            or execution.business_date != body.business_date or execution.payload.get("reversal_event_id")
            or body.request_key != f"aftersales-reverse:{execution.id}"):
        raise ValueError("售后释放凭证无效或已经消费")
    proof = execution.payload
    app = finance.lock(db, SettlementApplication, proof.get("application_id"))
    item = finance.lock(db, SettlementItem, execution.settlement_item_id)
    case = finance.lock(db, AfterSalesCase, execution.case_id)
    shipment = finance.lock(db, ShipmentSettlement, app.settlement_id) if app else None
    release = finance.lock(db, FinanceEvent, proof.get("release_event_id"))
    if (app is None or app.receipt_id != row.id or item is None or item.settlement_id != app.settlement_id
            or case is None or case.local_invoice_item_id != item.invoice_item_id
            or shipment is None or shipment.state != "shipped"
            or (row.purpose == "presale_deposit" and not shipment.is_final)
            or release is None or release.action != "aftersales_release" or release.receipt_id != row.id
            or release.payload.get("execution_id") != execution.id
            or Decimal(proof.get("amount", "0")) != body.amount):
        raise ValueError("售后释放必须关联原已发货应用；首款限最终已发货批次")
    return finance.money(proof["released_bank_charge"])


def reverse(db, receipt_id, body, user, *, release_execution_id=None):
    with db.begin_nested():
        ledger = finance.book(db)
        identity = db.get(Receipt, receipt_id)
        if identity is None or identity.source != "local":
            raise HTTPException(404, "本地核销不存在")
        invoice = finance._invoice(db, identity.invoice_id, user)
        batch = finance._payment(db, identity.batch_id, user)
        target = finance.lock(db, Receivable, identity.receivable_id)
        row = finance.lock(db, Receipt, receipt_id)
        event, fresh = finance.claim(db, "reverse_allocation", receipt_id, body, user, body.business_date)
        if not fresh:
            return row
        finance.open_date(ledger, body.business_date)
        finance._version(row, body.expected_version)
        if row.status != "active" or body.business_date < row.collection_date:
            raise ValueError("仅有效核销可以冲回，日期不能早于原核销")
        finance._after_history(db, body.business_date, batch_id=batch.id, receivable_id=target.id)
        exact_fee = (_aftersales_release(db, release_execution_id, row, body, user)
                     if release_execution_id is not None else None)
        if row.purpose == "presale_deposit" and release_execution_id is None:
            active = db.scalar(select(ShipmentSettlement.id).where(ShipmentSettlement.invoice_id == invoice.id,
                ShipmentSettlement.state != "cancelled").limit(1).with_for_update())
            if active is not None:
                raise ValueError("预售首款已支撑发货结算，请先处理相关批次")
        amount = finance.money(body.amount if body.amount is not None else row.effective_amount)
        if amount <= 0 or amount > row.effective_amount:
            raise ValueError("冲回金额超过核销剩余有效金额")
        apps = db.scalars(select(SettlementApplication).where(SettlementApplication.receipt_id == row.id)
            .order_by(SettlementApplication.id).with_for_update().execution_options(populate_existing=True)).all()
        charge = _components(row, amount, apps, exact_fee)
        reversed_amount = finance.money(row.reversed_amount + amount)
        reversed_fee = finance.money(row.reversed_bank_charge + charge)
        usd = _commission(db, row, reversed_amount, reversed_fee)
        row.reversed_amount, row.reversed_bank_charge = reversed_amount, reversed_fee
        if row.effective_amount == 0:
            row.status, row.collect_status = "reversed", 0
        row.version += 1
        batch.allocated_amount = finance.money(batch.allocated_amount - amount)
        batch.bank_charge_total = finance.money(batch.bank_charge_total - charge)
        batch.version += 1
        target.paid_amount = finance.money(target.paid_amount - amount)
        target.version += 1
        invoice.internal_received = finance.money(invoice.internal_received - amount)
        invoice.internal_balance = finance.money(invoice.internal_balance + amount)
        event.batch_id, event.receipt_id, event.receivable_id, event.amount = batch.id, row.id, target.id, -amount
        event.commission_amount_usd = -usd
        event.payload = {**event.payload, "reversed_bank_charge": str(charge),
            "remaining_amount": str(row.effective_amount), "remaining_bank_charge": str(row.effective_bank_charge)}
        db.flush()
        return row
