"""Frozen original beneficiaries and deterministic cumulative return clawbacks.

No function commits: receipt projection belongs to the return activation transaction.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, time, timedelta

from sqlalchemy import or_, and_

from app.models.commission import CommissionDetail, SyncedPayment, PaymentCommissionStatus
from app.models.customer import CustomerCommissionSnapshot
from app.sales_return.models import ReturnAllocation, ReturnReceipt

CENT = Decimal("0.01")
ROLES = ("salesperson", "supervisor", "second_supervisor")
DETAIL_FIELDS = ("payment_amount", "salesperson_id", "salesperson_rate", "salesperson_commission",
                 "supervisor_id", "supervisor_rate", "supervisor_commission",
                 "second_supervisor_id", "second_supervisor_rate", "second_supervisor_commission", "calc_rule_note")


class PendingCommissionBasis(ValueError):
    """An active refund must not disappear from an apparently complete batch."""


def _decimal(value):
    return Decimal(str(value or 0))


def _stored_expected(basis):
    if basis.get("expected") is not None:
        return basis["expected"]
    if basis.get("status") == "frozen" and basis.get("order_id") and basis.get("customer_id"):
        return {"order_id": basis["order_id"], "customer_id": basis["customer_id"],
                "commission_basis_usd": basis.get("principal_usd")}
    return None


def freeze_basis(db, original_payment_id: str, expected=None) -> dict:
    """Reuse the first frozen original basis, or freeze effective detail amounts.

    Current customer assignment is deliberately insufficient historical evidence.
    An uncalculated original remains pending until its verified commission exists.
    """
    allocations = db.query(ReturnAllocation).filter(
        ReturnAllocation.original_payment_id == str(original_payment_id)
    ).order_by(ReturnAllocation.id).with_for_update().populate_existing().all()
    if expected is None:
        expected = next((_stored_expected(a.basis or {}) for a in allocations
                         if _stored_expected(a.basis or {}) is not None), None)
    expected = ({"order_id": str(expected.get("order_id") or ""),
                 "customer_id": str(expected.get("customer_id") or ""),
                 "commission_basis_usd": str(expected.get("commission_basis_usd"))}
                if expected is not None else None)
    details = db.query(CommissionDetail).filter(
        CommissionDetail.payment_id == str(original_payment_id),
        CommissionDetail.status != "voided",
    ).order_by(CommissionDetail.id).with_for_update().populate_existing().all()
    payment = db.query(SyncedPayment).filter(SyncedPayment.payment_id == str(original_payment_id)).with_for_update().populate_existing().first()
    basis = {"status": "pending_basis", "original_payment_id": str(original_payment_id),
             "reason": "原回款尚无可验证的有效提成明细，请核对原期人员和实际计提依据"}
    if expected is not None:
        basis["expected"] = expected
    if not payment:
        return basis
    principal = _decimal(payment.payment_amount) - _decimal(payment.service_fee)
    if expected is not None:
        try:
            expected_principal = Decimal(expected["commission_basis_usd"])
            matches = (expected["order_id"] == str(payment.order_id)
                       and expected["customer_id"] == str(payment.customer_id)
                       and expected_principal.is_finite() and expected_principal == principal)
        except (ArithmeticError, ValueError, TypeError):
            matches = False
        if not matches:
            return {**basis, "reason": "原款同步记录的订单、客户或计提本金与退货冻结取证不一致，请核对原款变更"}
    for detail in details:
        if (str(detail.order_id) != str(payment.order_id) or str(detail.customer_id) != str(payment.customer_id)
                or _decimal(detail.payment_amount) != _decimal(payment.payment_amount)):
            return {**basis, "reason": "原有效提成明细的订单、客户或回款金额与原款冻结取证不一致"}
    identity = {"order_id": str(payment.order_id), "customer_id": str(payment.customer_id),
                "principal_usd": str(principal)}
    for allocation in allocations:
        frozen = allocation.basis or {}
        if frozen.get("status") != "frozen":
            continue
        if (_decimal(frozen.get("principal_usd")) != principal
                or (expected is not None and (frozen.get("order_id") != identity["order_id"]
                                              or frozen.get("customer_id") != identity["customer_id"]))
                or (frozen.get("order_id") is not None and frozen["order_id"] != identity["order_id"])
                or (frozen.get("customer_id") is not None and frozen["customer_id"] != identity["customer_id"])):
            return {**basis, "reason": "已有冻结提成依据的订单、客户或本金与本次原款取证不一致"}
        return {**frozen, **identity, **({"expected": expected} if expected is not None else {})}
    if not details:
        # Historical records predating the original collection are verifiable;
        # a current snapshot created after that date cannot prove original terms.
        cutoff = datetime.combine(payment.payment_date + timedelta(days=1), time.min)
        snapshot = db.query(CustomerCommissionSnapshot).filter(
            CustomerCommissionSnapshot.customer_id == payment.customer_id,
            CustomerCommissionSnapshot.is_complete.is_(True),
            CustomerCommissionSnapshot.created_at < cutoff,
            CustomerCommissionSnapshot.updated_at < cutoff,
        ).order_by(CustomerCommissionSnapshot.created_at.desc(), CustomerCommissionSnapshot.id.desc()).with_for_update().first()
        if snapshot is None:
            return basis
        sv_amount = Decimal(0)
        if snapshot.supervisor_id and snapshot.supervisor_id != snapshot.salesperson_id:
            sv_rate = (Decimal("0.015") if snapshot.salesperson_attribute == "develop"
                       and snapshot.supervisor_attribute == "develop" else _decimal(snapshot.supervisor_rate))
            sv_amount = principal * sv_rate
        sv2_amount = (principal * _decimal(snapshot.second_supervisor_rate)
                      if snapshot.second_supervisor_id and snapshot.second_supervisor_id != snapshot.salesperson_id else Decimal(0))
        detail = {"payment_amount": str(payment.payment_amount), "calc_rule_note": "退货引用原期归属快照冻结"}
        for role, amount in (("salesperson", principal * _decimal(snapshot.salesperson_rate)),
                             ("supervisor", sv_amount), ("second_supervisor", sv2_amount)):
            detail[f"{role}_id"] = getattr(snapshot, f"{role}_id")
            rate = getattr(snapshot, f"{role}_rate")
            detail[f"{role}_rate"] = str(rate) if rate is not None else None
            detail[f"{role}_commission"] = str(amount.quantize(CENT, ROUND_HALF_UP))
        return {"status": "frozen", "original_payment_id": str(original_payment_id),
                **identity, **({"expected": expected} if expected is not None else {}),
                "snapshot_id": snapshot.id, "details": [detail]}
    basis = {"status": "frozen", "original_payment_id": str(original_payment_id),
             **identity, **({"expected": expected} if expected is not None else {}),
             "details": [{field: (str(getattr(detail, field)) if isinstance(getattr(detail, field), Decimal)
                                   else getattr(detail, field)) for field in DETAIL_FIELDS}
                         for detail in details]}
    return basis


def project_receipt(db, receipt):
    """Insert one stable, local-only commission input; never update source facts."""
    db.flush()
    key = f"ark_return:{receipt.id}"
    existing = db.query(SyncedPayment).filter(SyncedPayment.payment_id == key).with_for_update().first()
    if existing:
        if existing.source != "ark_return" or _decimal(existing.payment_amount) != _decimal(receipt.amount_usd):
            raise ValueError("退货回款投影与冻结事实冲突")
        return existing
    payment = SyncedPayment(payment_id=key, source="ark_return", order_id=receipt.order_id,
                            customer_id=receipt.customer_id, payment_date=receipt.collection_date,
                            payment_amount=receipt.amount_usd, service_fee=0)
    db.add(payment)
    db.flush()
    return payment


def frozen_positive_rows(db, payment):
    """A referenced positive payment replays the same people and actual amounts."""
    allocation = db.query(ReturnAllocation).filter(
        ReturnAllocation.original_payment_id == payment.payment_id
    ).order_by(ReturnAllocation.id).with_for_update().first()
    if allocation is None:
        return None
    basis = freeze_basis(db, payment.payment_id, expected=_stored_expected(allocation.basis or {}))
    if basis.get("status") != "frozen":
        raise PendingCommissionBasis(f"原回款 {payment.payment_id}: {basis['reason']}")
    for related in db.query(ReturnAllocation).filter(ReturnAllocation.original_payment_id == payment.payment_id).with_for_update().all():
        if (related.basis or {}).get("status") != "frozen":
            candidate = freeze_basis(db, payment.payment_id, expected=_stored_expected(related.basis or {}))
            if candidate.get("status") == "frozen":
                related.basis = candidate
    return [{**row, "payment_id": payment.payment_id, "order_id": payment.order_id,
             "customer_id": payment.customer_id} for row in basis["details"]]


def return_rows(db, payment):
    receipt_id = int(payment.payment_id.removeprefix("ark_return:"))
    receipt = db.query(ReturnReceipt).filter(ReturnReceipt.id == receipt_id).with_for_update().first()
    if receipt is None:
        raise PendingCommissionBasis(f"找不到退货回款 {payment.payment_id}")
    allocations = db.query(ReturnAllocation).filter(ReturnAllocation.return_id == receipt.return_id).with_for_update().all()
    if not allocations:
        raise PendingCommissionBasis(f"退货 {receipt.return_id} 缺少原回款分摊")
    result = []
    for allocation in allocations:
        basis = freeze_basis(db, allocation.original_payment_id, expected=_stored_expected(allocation.basis or {}))
        if basis.get("status") != "frozen":
            raise PendingCommissionBasis(f"原回款 {allocation.original_payment_id}: {basis['reason']}")
        # Recover a pending allocation after verified original details become available.
        allocation.basis = basis
        cash_principal = _decimal(allocation.original_principal_usd)
        principal = _decimal(basis.get("principal_usd"))
        if cash_principal <= 0 or principal <= 0:
            raise PendingCommissionBasis("原回款可退本金依据必须大于零")
        previous = db.query(ReturnReceipt, ReturnAllocation).join(
            ReturnAllocation, ReturnAllocation.return_id == ReturnReceipt.return_id
        ).filter(ReturnAllocation.original_payment_id == allocation.original_payment_id,
                 or_(ReturnReceipt.collection_date < receipt.collection_date,
                     and_(ReturnReceipt.collection_date == receipt.collection_date, ReturnReceipt.id < receipt.id))).with_for_update().all()
        before = sum((_decimal(a.refund_amount_usd) * (1 if r.effect_kind == "activate" else -1)
                      for r, a in previous), Decimal(0))
        delta = _decimal(allocation.refund_amount_usd) * (1 if receipt.effect_kind == "activate" else -1)
        after = before + delta
        if min(before, after) < 0 or max(before, after) > cash_principal:
            raise ValueError("累计退款超出冻结原回款本金")
        for original in basis["details"]:
            row = dict(original)
            row.update(payment_id=payment.payment_id, order_id=payment.order_id,
                       customer_id=payment.customer_id, payment_amount=-delta)
            for role in ROLES:
                original_amount = _decimal(original.get(f"{role}_commission"))
                # Difference of cumulative rounded targets absorbs the final cent.
                # Cash eligibility can exclude bank fees that the original
                # commission base included. Preserve the original effective
                # rate; refunding all cash need not claw back fee commission.
                # Conversely, refunds may never exceed the original commission.
                before_target = (original_amount * min(before / principal, Decimal(1))).quantize(CENT, ROUND_HALF_UP)
                after_target = (original_amount * min(after / principal, Decimal(1))).quantize(CENT, ROUND_HALF_UP)
                row[f"{role}_commission"] = before_target - after_target
            row["calc_rule_note"] = f"退货原款 {allocation.original_payment_id}；原实际提成累计比例扣回"
            result.append(row)
    return result


def assert_batch_complete(db, batch):
    """Includes late prior-period events and refunds arriving after calculation."""
    pending = db.query(SyncedPayment.payment_id).outerjoin(
        PaymentCommissionStatus, PaymentCommissionStatus.payment_id == SyncedPayment.payment_id
    ).filter(
        SyncedPayment.source == "ark_return", SyncedPayment.payment_date <= batch.period_end,
        PaymentCommissionStatus.id.is_(None),
    ).with_for_update().all()
    if pending:
        raise PendingCommissionBasis("退货计提尚未完整，请作废重算或补齐原款依据：" + ", ".join(p[0] for p in pending[:20]))
