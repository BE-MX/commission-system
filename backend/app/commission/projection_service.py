"""Idempotent native financial events; refunds inherit cumulative cent rounding."""
from decimal import Decimal
from sqlalchemy import select
from app.commission.models import CommissionBasis, CommissionEventProjection
from app.commission.service import ROLES
from app.finance.models import FinanceEvent
from app.finance.service import ZERO, book, lock, money
from app.invoice.settlement_models import ReceiptBatch
from app.models.commission import SyncedPayment
from app.receipt.models import Receipt


def _projected_rmb(projection, payment, role):
    frozen = getattr(projection, f'{role}_commission_rmb')
    if frozen is not None:
        return frozen
    # Pre-opening native projections used this exact display conversion.
    # Keep paid cents; migration does not retroactively replace float rounding.
    return Decimal(str(round(float(getattr(projection, f'{role}_commission')) * float(payment.exchange_rate), 2)))


def sync_events(db, through):
    """Include late-resolved older income; never silently manufacture a basis."""
    book(db)
    count = 0
    originals = db.scalars(select(FinanceEvent).where(FinanceEvent.action.in_(["allocate", "opening_allocation"]),
        FinanceEvent.business_date <= through).order_by(FinanceEvent.id).with_for_update()).all()
    for original in originals:
        basis = db.scalar(select(CommissionBasis).where(CommissionBasis.event_id == original.id).with_for_update().execution_options(populate_existing=True))
        if basis is None or basis.snapshot is None:
            continue
        batch = lock(db, ReceiptBatch, original.batch_id)
        receipt = lock(db, Receipt, original.receipt_id)
        events = db.scalars(select(FinanceEvent).where(FinanceEvent.receipt_id == original.receipt_id,
            FinanceEvent.action.in_(["allocate", "opening_allocation", "reverse_allocation"]), FinanceEvent.business_date <= through)
            .order_by(FinanceEvent.id).with_for_update()).all()
        reversed_base = reversed_fee = reversed_gross = ZERO
        previous_fee_usd = previous_rmb = ZERO
        previous_commissions = {role: ZERO for role in ROLES}
        previous_commissions_rmb = {role: ZERO for role in ROLES}
        historical = original.action == "opening_allocation"
        opening = original.payload.get("opening", {}) if historical else {}
        if historical and not basis.snapshot.get("historical_payment_id"):
            raise ValueError("历史核销缺少已付提成消费身份，禁止制造新收入")
        fee_left = receipt.bank_charge - Decimal(opening.get("reversed_bank_charge", "0"))
        fee_usd = (Decimal(basis.snapshot["opening_fee_usd"]) if historical else money(fee_left * batch.rate_to_usd))
        total_rmb = (Decimal(basis.snapshot["opening_rmb"]) if historical else money(original.amount * batch.rate_to_cny))
        exchange_rate = Decimal(basis.snapshot['opening_exchange_rate']) if historical else batch.rate_to_cny / batch.rate_to_usd
        original_commissions_rmb = {role: Decimal(basis.snapshot[f'{role}_original_commission_rmb']) if historical else
            money(Decimal(basis.snapshot[f'{role}_original_commission']) * exchange_rate) for role in ROLES}
        projected = {row.event_id: row for row in db.scalars(select(CommissionEventProjection).where(
            CommissionEventProjection.event_id.in_([event.id for event in events])).with_for_update()).all()}
        payments = {row.payment_id: row for row in db.scalars(select(SyncedPayment).where(
            SyncedPayment.payment_id.in_([row.payment_id for row in projected.values()])).with_for_update()).all()}
        if not historical and original.id in projected:
            positive = projected[original.id]
            original_commissions_rmb = {role: _projected_rmb(positive, payments[positive.payment_id], role) for role in ROLES}
        # Pre-189 negatives already consumed displayed RMB cents. Freeze the
        # latest such boundary and prorate only its remaining responsibility.
        # Recomputing the whole cumulative ratio can make a small refund pay
        # back a cent that old rounding had already deducted.
        legacy_ids = [event.id for event in events if event.action == 'reverse_allocation' and event.id in projected
            and any(getattr(projected[event.id], f'{role}_commission_rmb') is None for role in ROLES)]
        legacy_boundary = max(legacy_ids, default=0)
        consumed = [event for event in events if event.action == 'reverse_allocation' and event.id <= legacy_boundary]
        if any(event.id not in projected for event in consumed):
            raise ValueError('既有提成冲回缺少完整投影，须先核验已扣金额')
        consumed_base = -sum((event.commission_amount_usd for event in consumed), ZERO)
        consumed_rmb = {role: -sum((_projected_rmb(projected[event.id], payments[projected[event.id].payment_id], role)
            for event in consumed), ZERO) for role in ROLES}
        for event in events:
            if event.action == "opening_allocation":
                # The existing confirmed historical batch already consumed it.
                # No positive SyncedPayment or projection can be manufactured.
                continue
            if event.action == "allocate":
                fee, rmb = fee_usd, total_rmb
                commissions = {role: Decimal(basis.snapshot[f"{role}_original_commission"]) for role in ROLES}
                commissions_rmb = original_commissions_rmb
            else:
                prior_commissions_rmb = previous_commissions_rmb.copy()
                reversed_base -= event.commission_amount_usd
                reversed_fee += Decimal(event.payload["reversed_bank_charge"])
                reversed_gross -= event.amount
                if not ZERO <= reversed_base <= original.commission_amount_usd or not ZERO <= reversed_gross <= original.amount:
                    raise ValueError("核销冲回累计超过原提成依据")
                cumulative_fee = (fee_usd if reversed_fee == fee_left else
                    money(fee_usd * reversed_fee / fee_left) if historical and fee_left else money(reversed_fee * batch.rate_to_usd))
                cumulative_rmb = (total_rmb if reversed_gross == original.amount else
                    money(total_rmb * reversed_gross / original.amount) if historical and original.amount else money(reversed_gross * batch.rate_to_cny))
                fee, rmb = previous_fee_usd - cumulative_fee, previous_rmb - cumulative_rmb
                previous_fee_usd, previous_rmb = cumulative_fee, cumulative_rmb
                cumulative = {role: (Decimal(basis.snapshot[f"{role}_original_commission"]) if reversed_base == original.commission_amount_usd
                    else money(Decimal(basis.snapshot[f"{role}_original_commission"]) * reversed_base / original.commission_amount_usd)
                    if historical and original.commission_amount_usd else money(reversed_base * Decimal(basis.snapshot[f"{role}_rate"]))) for role in ROLES}
                commissions = {role: previous_commissions[role] - cumulative[role] for role in ROLES}
                previous_commissions = cumulative
                cumulative_rmb_commissions = {role: original_commissions_rmb[role] if reversed_base == original.commission_amount_usd else
                    consumed_rmb[role] + money((original_commissions_rmb[role] - consumed_rmb[role]) *
                        (reversed_base - consumed_base) / (original.commission_amount_usd - consumed_base))
                    if event.id > legacy_boundary and original.commission_amount_usd > consumed_base else
                    money(original_commissions_rmb[role] * reversed_base / original.commission_amount_usd)
                    if original.commission_amount_usd else ZERO for role in ROLES}
                commissions_rmb = {role: previous_commissions_rmb[role] - cumulative_rmb_commissions[role] for role in ROLES}
                previous_commissions_rmb = cumulative_rmb_commissions
            if event.id in projected:
                if event.action == 'reverse_allocation':
                    prior = projected[event.id]
                    previous_commissions_rmb = {role: prior_commissions_rmb[role] -
                        _projected_rmb(prior, payments[prior.payment_id], role) for role in ROLES}
                continue
            payment_id = f"ark-finance:{event.id}"
            gross = money(event.commission_amount_usd + fee)
            db.add(SyncedPayment(payment_id=payment_id, order_id=f"local:{receipt.invoice_id}",
                customer_id=basis.customer_id, payment_date=event.business_date, payment_amount=gross,
                service_fee=fee, exchange_rate=exchange_rate, real_amount_rmb=rmb))
            db.add(CommissionEventProjection(event_id=event.id, basis_id=basis.id, payment_id=payment_id,
                **{f"{role}_commission": commissions[role] for role in ROLES},
                **{f"{role}_commission_rmb": commissions_rmb[role] for role in ROLES}))
            count += 1
        db.flush()
    return count
