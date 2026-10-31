"""Bind a reviewed opening to already consumed historical commission facts."""
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from app.commission.models import CommissionBasis
from app.commission.service import ROLES
from app.finance import service as finance
from app.invoice.models import Invoice
from app.invoice.settlement_models import ReceiptBatch
from app.models.commission import CommissionBatch, CommissionDetail, PaymentCommissionStatus, SyncedPayment


def paid_snapshot(db, event, receipt, *, source_customer_id, payment_id, prior_reversals, lock=True, payment_batch=None):
    """Caller owns the book and source proof; never create historical payments.

    An original and its explicit prior negative adjustments must already be in
    confirmed commission batches. Their residual cents, rather than today's
    policy, are the entitlement available for future negative adjustments.
    """
    def current(statement):
        return statement.with_for_update().execution_options(populate_existing=True) if lock else statement
    invoice = finance.lock(db, Invoice, receipt.invoice_id) if lock else db.get(Invoice, receipt.invoice_id)
    if (event.action != 'opening_allocation' or event.receipt_id != receipt.id
            or receipt.xiaoman_receipt_id != payment_id or not invoice.xiaoman_order_id):
        raise ValueError('历史提成必须绑定原订单与原回款身份')
    adjustment_payment_ids = [r.payment_id for r in prior_reversals]
    identities = [payment_id, *adjustment_payment_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('历史提成消费身份重复')
    existing = db.scalars(current(select(CommissionBasis).where(CommissionBasis.snapshot.isnot(None)))).all()
    for row in existing:
        if not isinstance(row.snapshot, dict):
            continue
        used = [row.snapshot.get('historical_payment_id'), *row.snapshot.get('historical_adjustment_payment_ids', [])]
        if set(identities).intersection(used):
            raise ValueError('历史提成消费身份已绑定其他核销')
    payments, details = [], []
    for index, identity in enumerate(identities):
        payment = db.scalar(current(select(SyncedPayment).where(SyncedPayment.payment_id == identity)))
        status = db.scalar(current(select(PaymentCommissionStatus).where(PaymentCommissionStatus.payment_id == identity)))
        batch = db.scalar(current(select(CommissionBatch).where(CommissionBatch.id == status.batch_id))) if status else None
        candidates = db.scalars(current(select(CommissionDetail).where(CommissionDetail.payment_id == identity,
            CommissionDetail.status != 'voided'))).all()
        detail = candidates[0] if len(candidates) == 1 else None
        if (payment is None or payment.payment_id != identity or status is None or status.payment_id != identity
                or batch is None or batch.status != 'confirmed' or detail is None
                or detail.batch_id != batch.id or detail.status not in {'confirmed', 'paid'}):
            raise ValueError('历史回款缺少唯一已确认提成凭证')
        if (payment.order_id != invoice.xiaoman_order_id or payment.customer_id != source_customer_id
                or detail.order_id != payment.order_id or detail.customer_id != payment.customer_id
                or payment.payment_date > event.business_date
                or detail.payment_amount != payment.payment_amount):
            raise ValueError('历史提成订单、客户、日期或本金依据不一致')
        gross, fee = payment.payment_amount, payment.service_fee or finance.ZERO
        if ((index == 0 and (gross <= 0 or not 0 <= fee <= gross))
                or (index and (gross >= 0 or not gross <= fee <= 0))):
            raise ValueError('历史调整必须是原回款的负数冲回事实')
        payments.append(payment); details.append(detail)
    original = details[0]
    frozen = dict(rule_version='historical-opening-2026-10-03', historical_payment_id=payment_id,
        historical_adjustment_payment_ids=list(adjustment_payment_ids), historical_detail_ids=[d.id for d in details],
        historical_source_customer_id=source_customer_id)
    for role in ROLES:
        identity = getattr(original, f'{role}_id')
        rate = Decimal(getattr(original, f'{role}_rate') or 0)
        if not 0 <= rate <= 1 or (role == 'salesperson' and not identity):
            raise ValueError('历史提成受益人或比例缺失')
        if any(getattr(d, f'{role}_id') != identity or Decimal(getattr(d, f'{role}_rate') or 0) != rate for d in details):
            raise ValueError('历史冲回受益人或比例与原提成不一致')
        original_amount = Decimal(getattr(original, f'{role}_commission') or 0)
        amounts = [Decimal(getattr(d, f'{role}_commission') or 0) for d in details]
        if any(amounts) and (not identity or getattr(original, f'{role}_rate') is None):
            raise ValueError('非零历史提成缺少明确受益人或比例依据')
        remaining = finance.money(sum(amounts, finance.ZERO))
        if original_amount < 0 or any(value > 0 for value in amounts[1:]) or not 0 <= remaining <= original_amount:
            raise ValueError('历史提成冲回超过原已计提金额')
        frozen.update({f'{role}_id': identity, f'{role}_rate': str(rate), f'{role}_original_commission': str(remaining)})
    usd_gross = finance.money(sum((p.payment_amount for p in payments), finance.ZERO))
    usd_fee = finance.money(sum((p.service_fee or finance.ZERO for p in payments), finance.ZERO))
    if usd_gross - usd_fee != event.commission_amount_usd or usd_fee < 0:
        raise ValueError('期初美元本金与历史已计提及冲回不一致')
    if any(p.real_amount_rmb is None for p in payments):
        raise ValueError('历史回款缺少冻结人民币金额')
    rmb = finance.money(sum((p.real_amount_rmb for p in payments), finance.ZERO))
    if rmb < 0 or (event.amount == 0 and (usd_gross or rmb)):
        raise ValueError('历史有效资金金额与剩余提成不一致')
    frozen.update(opening_fee_usd=str(usd_fee), opening_rmb=str(rmb))
    batch = payment_batch if payment_batch is not None else db.get(ReceiptBatch, event.batch_id)
    if batch is None:
        raise ValueError('历史核销缺少原付款汇率依据')
    if (finance.money(receipt.amount * batch.rate_to_usd) != payments[0].payment_amount
            or finance.money(receipt.bank_charge * batch.rate_to_usd) != (payments[0].service_fee or finance.ZERO)
            or sum((r.amount for r in prior_reversals), finance.ZERO) != (receipt.reversed_amount or finance.ZERO)
            or sum((r.bank_charge for r in prior_reversals), finance.ZERO) != (receipt.reversed_bank_charge or finance.ZERO)
            or event.amount != receipt.amount - (receipt.reversed_amount or finance.ZERO)):
        raise ValueError('历史原核销、费用或已冲回面额与提成凭证不一致')
    for reversal, payment in zip(prior_reversals, payments[1:], strict=True):
        if (finance.money(reversal.amount * reversal.rate_to_usd) != -payment.payment_amount
                or finance.money(reversal.bank_charge * reversal.rate_to_usd) != -(payment.service_fee or finance.ZERO)
                or reversal.business_date != payment.payment_date):
            raise ValueError('历史逐笔冲回的原币金额、费用或日期与原凭证不一致')
    if any(p.exchange_rate is None or p.exchange_rate <= 0 for p in payments):
        raise ValueError('历史原回款或冲回缺少明确的冻结汇率')
    historical_rate = Decimal(payments[0].exchange_rate) / 100
    if (historical_rate <= 0 or (batch.rate_to_cny / historical_rate).quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP)
            != batch.rate_to_usd):
        raise ValueError('承接汇率与历史已计提冻结汇率不一致')
    for reversal, payment in zip(prior_reversals, payments[1:], strict=True):
        rate = Decimal(payment.exchange_rate) / 100
        if (reversal.rate_to_cny / rate).quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP) != reversal.rate_to_usd:
            raise ValueError('历史逐笔冲回冻结汇率与提成凭证不一致')
    frozen['opening_exchange_rate'] = str(historical_rate)
    for role in ROLES:
        # Preserve the already displayed/paid legacy RMB cent rounding, which
        # used round(float(USD) * effective_rate, 2), not a new FX conversion.
        rmb_amounts = [Decimal(str(round(float(getattr(d, f'{role}_commission') or 0) * float(Decimal(p.exchange_rate)/100), 2)))
            for d, p in zip(details, payments, strict=True)]
        remaining = finance.money(sum(rmb_amounts, finance.ZERO))
        if not 0 <= remaining <= rmb_amounts[0]:
            raise ValueError('历史人民币提成冲回超过原已计提金额')
        frozen[f'{role}_original_commission_rmb'] = str(remaining)
    return frozen


def bind_paid_history(db, event, receipt, *, source_customer_id, payment_id, prior_reversals, actor_id):
    frozen = paid_snapshot(db, event, receipt, source_customer_id=source_customer_id, payment_id=payment_id,
        prior_reversals=prior_reversals)
    basis = CommissionBasis(event_id=event.id, customer_id=receipt.customer_id, snapshot=frozen,
        resolved_by=actor_id, resolution_reason='Verified historical paid commission opening')
    db.add(basis); db.flush()
    return basis
