"""One local accounting book; caller commits, each command is savepoint atomic.

The book row serializes financial writes and period closing. It is always locked
before order -> payment -> receivable -> allocation -> attachments. This modest
throughput tradeoff keeps account references, cutoff and balances one atomic fact.
Inventory commands never acquire this book, so their order-first locks remain safe.
"""
import hashlib
import json
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from app.core.time import beijing_now, beijing_today
from app.customer.access_service import require_customer_access, CustomerAccessDenied
from app.customer.models import CustomerAccount
from app.customer.transaction_identity import current_customer, invoice_customer
from app.finance.models import FinanceBook, Currency, BankAccount, FinanceEvent
from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch, Receivable, SettlementApplication, BatchAttachment
from app.receipt import access, batch_service
from app.receipt.models import Receipt
from app.commerce_shadow.hooks import observe_command

logger = logging.getLogger(__name__)
ZERO = Decimal("0.00")


def money(value):
    value = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if not value.is_finite() or abs(value) > Decimal("999999999999.99"):
        raise ValueError("金额超过账务精度范围")
    return value


def lock(db, model, identity):
    return db.scalar(select(model).where(model.id == identity).with_for_update().execution_options(populate_existing=True))


def book(db):
    from app.invoice.transition_gate import lock_platform
    lock_platform(db)
    row = lock(db, FinanceBook, 1)
    if row is None:
        # The migration creates this singleton. Unit-test databases and empty
        # isolated installations may initialize it lazily under a unique key.
        try:
            with db.begin_nested():
                db.add(FinanceBook(id=1))
                db.flush()
        except IntegrityError:
            logger.warning("Concurrent finance book initialization")
            print("Concurrent finance book initialization", flush=True)
        row = lock(db, FinanceBook, 1)
    return row


def open_date(ledger, day):
    if day > beijing_today():
        raise ValueError("不能使用未来记账日期")
    if ledger.closed_through and day <= ledger.closed_through:
        raise ValueError("该业务日期已结账，请在开放期间冲正")


def claim(db, action, identity, body, user, business_date):
    payload = {"action": action, "target_id": identity, "actor_id": access.user_id(user),
               "body": body.model_dump(mode="json")}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    prior = db.scalar(select(FinanceEvent).where(FinanceEvent.request_key == body.request_key)
                      .with_for_update().execution_options(populate_existing=True))
    if prior:
        if prior.request_hash != digest:
            raise ValueError("幂等键已用于不同的资金操作")
        return prior, False
    row = FinanceEvent(request_key=body.request_key, request_hash=digest, action=action,
                       payload=payload, business_date=business_date, created_by=access.user_id(user))
    db.add(row)
    db.flush()
    return row, True


def ensure_batch_access(db, row, user, *, fresh=False):
    if row is None or row.transaction_mode != "local":
        raise HTTPException(404, "本地收款不存在")
    if access.all_access(user):
        return
    # Pure prepayments have no child Receipt; use the real-time customer scope.
    customer_access(db, row.local_customer_id, user, fresh=fresh)


def customer_access(db, customer_id, user, *, fresh=False):
    try:
        return require_customer_access(db, customer_id=customer_id, user=user,
            action_permissions=["receipt:read", "receipt:write", "receipt:admin"], manage_permissions=["customer:admin"], fresh=fresh)
    except CustomerAccessDenied as exc:
        logger.warning("Local finance customer scope denied")
        print("Local finance customer scope denied", flush=True)
        raise HTTPException(404, "客户或收款不存在") from exc


def _payment(db, identity, user):
    row = lock(db, ReceiptBatch, identity)
    ensure_batch_access(db, row, user, fresh=True)
    from app.finance.transition_identity import require_payment
    require_payment(db, row)
    return row


def _invoice(db, identity, user):
    from app.invoice.transition_gate import require_invoice
    require_invoice(db, identity, 'local')
    row = lock(db, Invoice, identity)
    access.ensure_invoice(db, row, user)
    if not access.all_access(user):
        customer_access(db, row.local_customer_id, user, fresh=True)
    if row.transaction_mode != "local" or row.commerce_status not in {"confirmed", "partially_shipped", "shipped", "closed"}:
        raise ValueError("订单不是可记账的本地有效订单")
    return row


def _version(row, expected):
    if row.version != expected:
        raise ValueError("账务数据已变化，请刷新后重试")


def available(row):
    return money(row.gross_amount - row.allocated_amount - row.refunded_amount) if row.finance_status == "confirmed" else ZERO


def _bank_reference_used(db, account_id, reference):
    receipt = db.scalar(select(ReceiptBatch.id).where(ReceiptBatch.bank_account_id == account_id,
                        ReceiptBatch.bank_reference == reference).with_for_update())
    refund_event = db.scalar(select(FinanceEvent.id).where(FinanceEvent.bank_account_id == account_id,
                             FinanceEvent.bank_reference == reference).with_for_update())
    return bool(receipt or refund_event)


def _after_history(db, day, *, batch_id=None, receivable_id=None):
    predicates = []
    if batch_id is not None:
        predicates.append(FinanceEvent.batch_id == batch_id)
    if receivable_id is not None:
        predicates.append(FinanceEvent.receivable_id == receivable_id)
    # Current read, even if this request entered with an old RR snapshot. A
    # later reversal must not finance an earlier-dated new allocation/refund.
    future = db.scalar(select(FinanceEvent.id).where(or_(*predicates), FinanceEvent.business_date > day)
                       .limit(1).with_for_update())
    if future is not None:
        raise ValueError("记账日期不能早于该资金或应收的已有事件")


@observe_command('payment.register')
def register(db, body, user):
    from app.invoice.transition_gate import allow_route
    allow_route(db, 'local')
    with db.begin_nested():
        ledger = book(db)
        scope = require_customer_access(db, customer_id=body.local_customer_id, user=user,
                                        action_permissions=["receipt:write"], manage_permissions=[], fresh=True)
        customer = lock(db, CustomerAccount, scope.customer_id)
        if customer.record_status != "active" or customer.identity_status == "disputed":
            raise ValueError("客户已停用或存在身份争议")
        event, fresh = claim(db, "register", None, body, user, body.collection_date)
        if not fresh:
            return _payment(db, event.batch_id, user)
        open_date(ledger, body.collection_date)
        account = lock(db, BankAccount, body.bank_account_id)
        if account is None or not account.active or account.currency != body.currency:
            raise ValueError("银行账户已停用或币种不符")
        currencies = {x.code: x for x in db.scalars(select(Currency).where(Currency.code.in_([body.currency, "USD"]))
                       .order_by(Currency.code).with_for_update().execution_options(populate_existing=True)).all()}
        currency, usd = currencies.get(body.currency), currencies.get("USD")
        if not currency or not currency.active or not usd or currency.rate_to_cny <= 0 or usd.rate_to_cny <= 0:
            raise ValueError("币种或美元汇率尚未配置")
        if _bank_reference_used(db, account.id, body.bank_reference):
            raise ValueError("该账户的银行流水已登记，请查看原收款")
        from app.finance.transition_identity import reserve
        bank_identity = reserve(db, account, body.bank_reference, body.currency,
            body.gross_amount, access.user_id(user), payment_type=body.payment_type)
        row = ReceiptBatch(batch_no=f"PAY-{body.collection_date:%Y%m%d}-{event.id:08d}",
            transaction_mode="local", customer_id=f"ark:{customer.id}", local_customer_id=customer.id,
            currency=body.currency, gross_amount=body.gross_amount, actual_bank_fee=body.actual_bank_fee,
            net_amount=money(body.gross_amount - body.actual_bank_fee), bank_account_id=account.id,
            bank_reference=body.bank_reference, collection_date=body.collection_date, payment_type=body.payment_type,
            remark=body.remark, request_key=body.request_key, request_hash=event.request_hash,
            rate_to_cny=currency.rate_to_cny,
            rate_to_usd=(currency.rate_to_cny / usd.rate_to_cny).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP),
            created_by=access.user_id(user))
        if row.rate_to_usd <= 0 or row.rate_to_usd >= Decimal("10000000000"):
            raise ValueError("交叉汇率超出精度范围")
        db.add(row)
        db.flush()
        from app.commerce_transition.service import bind_bank_payment
        bind_bank_payment(db, bank_identity.id, f'local:{row.id}')
        if body.attachment_ids:
            batch_service.bind_proofs(db, row, body.attachment_ids, access.user_id(user))
        event.batch_id, event.amount = row.id, body.gross_amount
        db.flush()
        return row


@observe_command('payment.confirm', target_arg='batch_id')
def confirm(db, batch_id, body, user):
    with db.begin_nested():
        ledger = book(db)
        row = _payment(db, batch_id, user)
        event, fresh = claim(db, "confirm", batch_id, body, user, body.business_date)
        if not fresh:
            return row
        open_date(ledger, body.business_date)
        _version(row, body.expected_version)
        if row.finance_status != "registered" or body.business_date < row.collection_date:
            raise ValueError("仅待确认付款可确认，确认日期不能早于收款日期")
        row.finance_status, row.confirmed_by, row.confirmed_at = "confirmed", access.user_id(user), beijing_now()
        row.confirmed_date = body.business_date
        row.version += 1
        event.batch_id, event.amount = row.id, row.gross_amount
        db.flush()
        return row


def _target_active(db, target, day):
    if target.settlement_id is None:
        return
    from app.invoice.settlement_models import ShipmentSettlement
    settlement = lock(db, ShipmentSettlement, target.settlement_id)
    if settlement is None or settlement.state == "cancelled":
        raise ValueError("对应发货结算已取消，应收不可再次调整或核销")
    effective = settlement.quote.get("business_date")
    if effective and day < date.fromisoformat(effective):
        raise ValueError("记账日期不能早于本批应收生效日")


@observe_command('allocation.create', target_arg='batch_id', invoice_arg='body.invoice_id')
def allocate(db, batch_id, body, user):
    with db.begin_nested():
        ledger = book(db)
        invoice = _invoice(db, body.invoice_id, user)
        batch = _payment(db, batch_id, user)
        target = lock(db, Receivable, body.receivable_id)
        if target is None or target.invoice_id != invoice.id:
            raise ValueError("应收不属于所选订单")
        event, fresh = claim(db, "allocate", batch_id, body, user, body.business_date)
        if not fresh:
            return lock(db, Receipt, event.receipt_id)
        open_date(ledger, body.business_date)
        _target_active(db, target, body.business_date)
        _version(batch, body.expected_version)
        if batch.finance_status != "confirmed":
            raise ValueError("付款尚未财务确认")
        if batch.confirmed_date is None or body.business_date < batch.confirmed_date or body.business_date < invoice.invoice_date:
            raise ValueError("核销日期不能早于财务确认和订单日期")
        _after_history(db, body.business_date, batch_id=batch.id, receivable_id=target.id)
        if (current_customer(db, batch.local_customer_id, lock=True) != invoice_customer(db, invoice, lock=True)
                or batch.currency != target.currency or target.currency != invoice.currency):
            raise ValueError("付款与订单的客户或币种不一致")
        remaining = money(target.amount + target.adjustment_amount - target.paid_amount)
        if body.amount > available(batch) or body.amount > remaining:
            raise ValueError("金额超过付款可用余额或应收未核销金额")
        # Customer surcharge is not the bank's actual fee. Allocate it from the
        # remaining target proportion; the final payment absorbs cent rounding.
        active_rows = db.scalars(select(Receipt).where(Receipt.receivable_id == target.id, Receipt.status == "active")
                                  .with_for_update().execution_options(populate_existing=True)).all()
        if body.purpose == "presale_deposit" and (invoice.order_type != "presale" or target.kind != "goods"):
            raise ValueError("首款只能核销预售商品应收")
        pool_remaining = remaining
        charge_left = max(ZERO, money(target.handling_amount - sum((x.effective_bank_charge for x in active_rows), ZERO)))
        if invoice.order_type == "presale" and target.kind == "goods":
            deposits = [row for row in active_rows if row.purpose == "presale_deposit"]
            deposit_left = money(invoice.local_deposit_amount - sum((row.effective_amount for row in deposits), ZERO))
            deposit_charge_left = money(invoice.local_deposit_charge - sum((row.effective_bank_charge for row in deposits), ZERO))
            if body.purpose == "presale_deposit":
                pool_remaining, charge_left = deposit_left, deposit_charge_left
            else:
                pool_remaining, charge_left = remaining - deposit_left, charge_left - deposit_charge_left
            if body.amount > pool_remaining or charge_left < 0:
                raise ValueError("核销超过该首款或非首款合同余额")
        settlement = None
        component = "freight" if target.kind == "freight" else "goods"
        if body.settlement_id is not None:
            from app.invoice.settlement_models import ShipmentSettlement
            from app.invoice import local_funding
            settlement = lock(db, ShipmentSettlement, body.settlement_id)
            if (settlement is None or settlement.invoice_id != invoice.id or settlement.state != "awaiting_payment"
                    or body.purpose == "presale_deposit"
                    or (invoice.order_type == "presale" and target.kind == "freight" and target.settlement_id != settlement.id)):
                raise ValueError("核销对应发货批次、应收或状态不匹配")
            if body.business_date < date.fromisoformat(settlement.quote["business_date"]):
                raise ValueError("核销日期不能早于发货结算生效日")
            local_funding.ensure_event_date(db, invoice.id, body.business_date, settlement.id)
            apps = local_funding.applications(db, invoice)
            required = local_funding.requirements(settlement)[component]
            applied = local_funding.totals(apps, settlement.id, component)
            pool_remaining = money(required[0] - applied[0])
            charge_left = money(required[1] - applied[1])
            if body.amount > pool_remaining:
                raise ValueError("金额超过本批未核销资金计划")
        elif invoice.order_type == "presale" and body.purpose != "presale_deposit":
            raise ValueError("预售批次款必须指定发货结算，沿用本批费用计划")
        charge = min(body.amount, charge_left if body.amount == pool_remaining else money(charge_left * body.amount / pool_remaining))
        if charge > max(ZERO, money(target.handling_amount - sum((x.effective_bank_charge for x in active_rows), ZERO))):
            raise ValueError("核销费用超过应收尚未分配费用，请先核对既有核销")
        proofs = list(db.scalars(select(BatchAttachment.attachment_id).where(BatchAttachment.batch_id == batch.id)).all())
        row = Receipt(receipt_no=f"ALLOC-{event.id:012d}", invoice_id=invoice.id, batch_id=batch.id,
            receivable_id=target.id, source="local", purpose="freight" if target.kind == "freight" else body.purpose,
            request_key=f"local-allocation:{event.id}", request_hash=event.request_hash, amount=body.amount,
            bank_charge=charge, currency=batch.currency, collection_date=body.business_date, payment_type=batch.payment_type,
            customer_id=batch.customer_id, attachment_ids=proofs, collect_status=1, sync_status="not_applicable",
            created_by=access.user_id(user), remark="本地已确认付款核销")
        db.add(row)
        db.flush()
        if settlement is not None:
            db.add(SettlementApplication(settlement_id=settlement.id, receipt_id=row.id, component=component,
                                         amount=row.amount, bank_charge=row.bank_charge, status="reserved"))
        batch.allocated_amount = money(batch.allocated_amount + body.amount)
        batch.bank_charge_total = money(batch.bank_charge_total + charge)
        batch.version += 1
        target.paid_amount = money(target.paid_amount + body.amount)
        target.version += 1
        invoice.internal_received = money(invoice.internal_received + body.amount)
        invoice.internal_balance = money(invoice.internal_balance - body.amount)
        event.batch_id, event.receipt_id, event.receivable_id, event.amount = batch.id, row.id, target.id, body.amount
        event.commission_amount_usd = money((body.amount - charge) * batch.rate_to_usd) if target.kind == "goods" else ZERO
        if target.kind == "goods":
            from app.commission.service import capture
            capture(db, event, batch.customer_id)
        db.flush()
        return row


@observe_command('allocation.reverse', target_arg='receipt_id')
def reverse_allocation(db, receipt_id, body, user):
    from app.finance.reversal_service import reverse
    return reverse(db, receipt_id, body, user)


@observe_command('payment.refund', target_arg='batch_id')
def refund(db, batch_id, body, user):
    with db.begin_nested():
        ledger = book(db)
        row = _payment(db, batch_id, user)
        event, fresh = claim(db, "refund", batch_id, body, user, body.business_date)
        if not fresh:
            return row
        open_date(ledger, body.business_date)
        _version(row, body.expected_version)
        if not body.amount or not body.bank_reference:
            raise ValueError("退款必须填写实际退款金额和银行流水")
        if body.amount > available(row):
            raise ValueError("退款超过未核销的可退余额")
        if row.confirmed_date is None or body.business_date < row.confirmed_date:
            raise ValueError("退款日期不能早于财务确认日期")
        _after_history(db, body.business_date, batch_id=row.id)
        if _bank_reference_used(db, row.bank_account_id, body.bank_reference):
            raise ValueError("退款银行流水已记账")
        from app.finance.transition_identity import reserve
        from app.commerce_transition.service import bind_bank_payment
        refund_account = lock(db, BankAccount, row.bank_account_id)
        refund_identity = reserve(db, refund_account, body.bank_reference, row.currency,
            body.amount, access.user_id(user), payment_type='refund')
        bind_bank_payment(db, refund_identity.id, f'local-refund:{event.id}')
        row.refunded_amount = money(row.refunded_amount + body.amount)
        row.version += 1
        event.batch_id, event.amount = row.id, -body.amount
        event.bank_account_id, event.bank_reference = row.bank_account_id, body.bank_reference
        db.flush()
        return row


@observe_command('receivable.adjust', target_arg='receivable_id', invoice_arg='body.invoice_id')
def adjust_receivable(db, receivable_id, body, user, *, contract_change_event=None):
    with db.begin_nested():
        ledger = book(db)
        invoice = _invoice(db, body.invoice_id, user)
        row = lock(db, Receivable, receivable_id)
        if row is None or row.invoice_id != invoice.id:
            raise HTTPException(404, "应收不存在")
        event, fresh = claim(db, "adjust_receivable", receivable_id, body, user, body.business_date)
        if not fresh:
            return row
        if contract_change_event is not None:
            if (contract_change_event.id is None or contract_change_event.invoice_id != invoice.id
                    or contract_change_event.action != 'amend'):
                raise ValueError('合同差额必须关联本单实际变更事件')
            event.payload = {**event.payload, 'contract_change_event_id': contract_change_event.id}
        open_date(ledger, body.business_date)
        _target_active(db, row, body.business_date)
        _version(row, body.expected_version)
        if not body.amount or body.business_date < invoice.invoice_date:
            raise ValueError("应收调整必须非零，日期不能早于订单")
        _after_history(db, body.business_date, receivable_id=row.id)
        adjusted = money(row.adjustment_amount + body.amount)
        face = money(row.amount + adjusted)
        if face < 0 or face < row.paid_amount:
            raise ValueError("调整后应收不能低于零或已核销金额，请先冲回核销")
        row.adjustment_amount = adjusted
        row.version += 1
        invoice.internal_balance = money(invoice.internal_balance + body.amount)
        event.receivable_id, event.amount = row.id, body.amount
        db.flush()
        return row


def describe(db, row, user):
    ensure_batch_access(db, row, user)
    customer = db.get(CustomerAccount, row.local_customer_id)
    account = db.get(BankAccount, row.bank_account_id)
    return {"id": row.id, "batch_no": row.batch_no, "local_customer_id": row.local_customer_id,
            "customer_name": customer.display_name if customer else None, "account_name": account.name if account else None,
            "currency": row.currency, "gross_amount": str(money(row.gross_amount)), "net_amount": str(money(row.net_amount)),
            "actual_bank_fee": str(money(row.actual_bank_fee)), "allocated_amount": str(money(row.allocated_amount)),
            "refunded_amount": str(money(row.refunded_amount)), "available_amount": str(available(row)),
            "collection_date": row.collection_date, "status": row.finance_status, "version": row.version,
            "bank_account_id": row.bank_account_id, "bank_reference": row.bank_reference,
            "rate_to_cny": str(row.rate_to_cny), "rate_to_usd": str(row.rate_to_usd)}


@observe_command('receivable.terms', target_arg='receivable_id', invoice_arg='body.invoice_id')
def set_due_date(db, receivable_id, body, user):
    with db.begin_nested():
        ledger = book(db)
        invoice = _invoice(db, body.invoice_id, user)
        row = lock(db, Receivable, receivable_id)
        if row is None or row.invoice_id != invoice.id:
            raise HTTPException(404, "应收不存在")
        event, fresh = claim(db, "receivable_terms", receivable_id, body, user, body.business_date)
        if not fresh:
            return row
        open_date(ledger, body.business_date)
        _target_active(db, row, body.business_date)
        _version(row, body.expected_version)
        _after_history(db, body.business_date, receivable_id=row.id)
        if body.due_date < invoice.invoice_date:
            raise ValueError("应收到期日不能早于订单日期")
        event.receivable_id = row.id
        event.payload = {**event.payload, "previous_due_date": str(row.due_date) if row.due_date else None}
        row.due_date = body.due_date
        row.version += 1
        db.flush()
        return row


@observe_command('payment.void', target_arg='batch_id')
def void_registration(db, batch_id, body, user):
    with db.begin_nested():
        ledger = book(db)
        row = _payment(db, batch_id, user)
        event, fresh = claim(db, "void_registration", batch_id, body, user, body.business_date)
        if not fresh:
            return row
        open_date(ledger, body.business_date)
        _version(row, body.expected_version)
        if row.finance_status != "registered":
            raise ValueError("仅未确认登记可作废，已确认收款须退款或冲正")
        if body.business_date < row.collection_date:
            raise ValueError("作废日期不能早于收款日期")
        from app.finance.transition_identity import release_unconfirmed_registration
        release_unconfirmed_registration(db, row, event, access.user_id(user))
        row.finance_status, row.status = "voided", "voided"
        event.payload = {**event.payload, "released_bank_reference": row.bank_reference}
        row.bank_reference = None
        row.version += 1
        event.batch_id = row.id
        db.flush()
        return row
