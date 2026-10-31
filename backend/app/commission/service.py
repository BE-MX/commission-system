"""Capture native commission entitlement before any downstream sync can drift."""
from decimal import Decimal
from sqlalchemy import select

from app.auth.models import ArkUser
from app.commission.models import CommissionBasis
from app.core.time import beijing_now
from app.finance.service import book, lock, money
from app.finance.models import FinanceEvent
from app.models.customer import CustomerCommissionSnapshot
from app.receipt.access import user_id


ROLES = ("salesperson", "supervisor", "second_supervisor")


def freeze_snapshot(db, snapshot):
    if not snapshot or not snapshot.is_complete:
        return None
    frozen = {"source_snapshot_id": snapshot.id, "rule_version": "native-2026-10-03",
        "salesperson_attribute": snapshot.salesperson_attribute, "supervisor_attribute": snapshot.supervisor_attribute}
    for role in ROLES:
        identity = getattr(snapshot, f"{role}_id")
        raw_rate = getattr(snapshot, f"{role}_rate")
        if role == "salesperson" and (not identity or raw_rate is None):
            return None
        rate = Decimal(raw_rate or 0)
        if role != "salesperson" and (not identity or identity == snapshot.salesperson_id):
            rate = Decimal(0)
        elif role == "supervisor" and rate > 0 and snapshot.salesperson_attribute == snapshot.supervisor_attribute == "develop":
            rate = Decimal("0.0150")
        if not rate.is_finite() or not 0 <= rate <= 1:
            return None
        # Native entitlement never guesses identity from names or current owners.
        if identity:
            if not identity.startswith("ark:") or not identity[4:].isdigit():
                return None
            person = db.scalar(select(ArkUser).where(ArkUser.id == int(identity[4:])).with_for_update())
            if person is None:
                return None
            frozen[f"{role}_name"] = person.real_name
        frozen[f"{role}_id"] = identity
        frozen[f"{role}_rate"] = str(rate)
    return frozen


def capture(db, event, customer_id):
    """Called inside the allocation transaction while its finance book is held."""
    candidates = db.scalars(select(CustomerCommissionSnapshot).where(
        CustomerCommissionSnapshot.customer_id == customer_id,
        CustomerCommissionSnapshot.is_current.is_(True))
        .order_by(CustomerCommissionSnapshot.id).with_for_update().execution_options(populate_existing=True)).all()
    snapshot = freeze_snapshot(db, candidates[0]) if len(candidates) == 1 else None
    if snapshot:
        source = candidates[0]
        if any(value and value.date() > event.business_date for value in (source.created_at, source.updated_at, source.operated_at)):
            snapshot = None
    if snapshot:
        snapshot.update({f"{role}_original_commission": str(money(event.commission_amount_usd * Decimal(snapshot[f"{role}_rate"]))) for role in ROLES})
    row = CommissionBasis(event_id=event.id, customer_id=customer_id, snapshot=snapshot,
        pending_reason=None if snapshot else "原核销时缺少唯一完整的本地提成归属，需核验后补全")
    db.add(row)
    db.flush()
    return row


def resolve(db, basis_id, snapshot_id, reason, user):
    with db.begin_nested():
        book(db)
        row = lock(db, CommissionBasis, basis_id)
        if row is None:
            raise ValueError("提成依据不存在")
        if row.snapshot is not None:
            if row.snapshot.get("source_snapshot_id") == snapshot_id and row.resolution_reason == reason and row.resolved_by == user_id(user):
                return row
            raise ValueError("提成依据已冻结，不能改写既有计提或退款归属")
        snapshot = lock(db, CustomerCommissionSnapshot, snapshot_id)
        if snapshot is None or snapshot.customer_id != row.customer_id:
            raise ValueError("提成快照不属于原核销客户")
        frozen = freeze_snapshot(db, snapshot)
        if frozen is None or not reason.strip():
            raise ValueError("需要完整本地归属及原业务日期适用依据")
        original = lock(db, FinanceEvent, row.event_id)
        frozen.update({f"{role}_original_commission": str(money(original.commission_amount_usd * Decimal(frozen[f"{role}_rate"]))) for role in ROLES})
        row.snapshot = frozen
        row.resolved_by, row.resolved_at, row.resolution_reason = user_id(user), beijing_now(), reason.strip()
        db.flush()
        return row


def write_policy(db, customer_id, body, user):
    from app.customer.models import CustomerAccount
    from app.services.rate_utils import calc_commission_rates
    with db.begin_nested():
        book(db)
        if db.get(CustomerAccount, customer_id) is None:
            raise ValueError("客户不存在")
        identity = f"ark:{customer_id}"
        current = db.scalars(select(CustomerCommissionSnapshot).where(
            CustomerCommissionSnapshot.customer_id == identity, CustomerCommissionSnapshot.is_current.is_(True))
            .with_for_update().execution_options(populate_existing=True)).all()
        if len(current) > 1 or (current[0].id if current else None) != body.expected_snapshot_id:
            raise ValueError("提成归属已变化或重复，请刷新核验")
        values = {}
        for role in ROLES:
            person_id = getattr(body, f"{role}_id")
            if person_id:
                person = db.scalar(select(ArkUser).where(ArkUser.id == person_id).with_for_update())
                if person is None or not person.is_active or person.deleted_at:
                    raise ValueError("提成受益人必须是有效本地用户")
            values[f"{role}_id"] = f"ark:{person_id}" if person_id else None
        if body.supervisor_id and body.supervisor_id != body.salesperson_id and body.supervisor_attribute is None:
            raise ValueError("一级主管属性缺失")
        rates = calc_commission_rates(values["salesperson_id"], body.salesperson_attribute,
            values["supervisor_id"], body.supervisor_attribute, values["second_supervisor_id"])
        if current:
            current[0].is_current = False
        row = CustomerCommissionSnapshot(customer_id=identity, **values,
            salesperson_attribute=body.salesperson_attribute, supervisor_attribute=body.supervisor_attribute,
            **{f"{role}_rate": rates[index] for index, role in enumerate(ROLES)},
            is_complete=True, is_current=True, source="manual", is_manual_reset=bool(current),
            reset_reason=body.reason, operator=str(user_id(user)), operated_at=beijing_now())
        db.add(row)
        db.flush()
        return row
