"""Reuse commission batches with explicit positive/negative source dependencies."""
from sqlalchemy import select
from app.commission.models import CommissionBasis, CommissionEventProjection
from app.commission.service import ROLES
from app.models.commission import CommissionBatch, PaymentCommissionStatus
from app.finance.service import lock


def native_detail(db, payment, batch_id, included):
    projection = db.scalar(select(CommissionEventProjection).where(CommissionEventProjection.payment_id == payment.payment_id)
        .with_for_update().execution_options(populate_existing=True))
    if projection is None:
        raise ValueError("本地提成来源投影缺失")
    basis = lock(db, CommissionBasis, projection.basis_id)
    original_id = basis.snapshot.get("historical_payment_id") or f"ark-finance:{basis.event_id}"
    if projection.event_id != basis.event_id and original_id not in included:
        source = db.scalar(select(PaymentCommissionStatus).where(PaymentCommissionStatus.payment_id == original_id).with_for_update())
        source_batch = lock(db, CommissionBatch, source.batch_id) if source else None
        # Only confirmed original batches are irreversible. Draft calculated
        # income may be voided, so its reversal waits or joins the same batch.
        if source_batch is None or source_batch.status != "confirmed":
            return None
    frozen = basis.snapshot
    detail = dict(batch_id=batch_id, payment_id=payment.payment_id, order_id=payment.order_id,
        customer_id=payment.customer_id, payment_amount=payment.payment_amount,
        calc_rule_note=f"本地冻结依据 {basis.id}，{frozen['rule_version']}")
    for role in ROLES:
        detail[f"{role}_id"] = frozen[f"{role}_id"]
        detail[f"{role}_rate"] = frozen[f"{role}_rate"]
        detail[f"{role}_commission"] = getattr(projection, f"{role}_commission")
    return detail
