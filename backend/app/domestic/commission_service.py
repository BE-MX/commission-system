"""Customer allocation management and transactional order snapshots."""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.domestic.models import DomesticCustomerCommission, DomesticOrderCommission
from app.domestic.schemas import CommissionAllocation


class CommissionAllocationChanged(ValueError):
    def __init__(self, current):
        super().__init__("客户提成分配已变更，请核对最新分配后重新提交")
        self.detail = {"code": "COMMISSION_ALLOCATION_CHANGED", "message": str(self),
                       "commission_allocations": current}


def customer_allocations(db: Session, customer_ids: list[int], *, locked=False) -> dict[int, list[dict]]:
    result = {customer_id: [] for customer_id in customer_ids}
    if not customer_ids:
        return result
    query = (db.query(DomesticCustomerCommission, ArkUser.real_name)
            .join(ArkUser, ArkUser.id == DomesticCustomerCommission.user_id)
            .filter(DomesticCustomerCommission.customer_id.in_(customer_ids))
            .order_by(DomesticCustomerCommission.user_id))
    if locked:
        # A parent lock does not refresh a MySQL REPEATABLE READ read view.
        query = query.populate_existing().with_for_update()
    rows = query.all()
    for row, name in rows:
        result[row.customer_id].append({"user_id": row.user_id, "user_name": name,
                                        "rate": format(row.rate, ".4f")})
    return result


def initialize_default(db: Session, customer) -> None:
    """Only call for newly created customers, never infer historical allocations."""
    if customer.owner_user_id is not None:
        db.add(DomesticCustomerCommission(customer_id=customer.id,
                                         user_id=customer.owner_user_id, rate=Decimal("0.04")))
        db.flush()


def replace_allocations(db: Session, customer_id: int, allocations: list) -> None:
    """Caller holds the customer row lock and owns the transaction."""
    parsed = [CommissionAllocation.model_validate(item) for item in allocations]
    if not 1 <= len(parsed) <= 2 or len({item.user_id for item in parsed}) != len(parsed):
        raise ValueError("提成分配需要 1～2 名不同的业务员")
    if sum(item.rate for item in parsed) > 1:
        raise ValueError("提成比例合计不能超过 100%")
    users = (db.query(ArkUser).filter(ArkUser.id.in_([item.user_id for item in parsed]))
             .order_by(ArkUser.id).populate_existing().with_for_update().all())
    if len(users) != len(parsed) or any(not user.is_active or user.deleted_at for user in users):
        raise ValueError("提成业务员必须是有效在职用户")
    # ORM deletes preserve the existing domestic decision event audit hooks.
    for row in (db.query(DomesticCustomerCommission).filter_by(customer_id=customer_id)
                .populate_existing().with_for_update().all()):
        db.delete(row)
    db.flush()
    db.add_all([DomesticCustomerCommission(customer_id=customer_id, user_id=item.user_id, rate=item.rate)
                for item in parsed])
    db.flush()


def locked_allocations(db: Session, customer_id: int, expected=None) -> list[dict]:
    """Read after locking the parent, shared with every config writer."""
    current = customer_allocations(db, [customer_id], locked=True)[customer_id]
    if not current:
        raise ValueError("客户未配置提成分配，请先在客户管理中配置")
    if expected is not None:
        actual_key = sorted((row["user_id"], Decimal(row["rate"])) for row in current)
        expected_key = sorted((item.user_id, item.rate) for item in expected)
        if actual_key != expected_key:
            raise CommissionAllocationChanged(current)
    return current


def save_order_snapshot(db: Session, order_id: int, allocations: list[dict], *, replace=False) -> None:
    if replace:
        for row in (db.query(DomesticOrderCommission).filter_by(order_id=order_id)
                    .populate_existing().with_for_update().all()):
            db.delete(row)
        db.flush()
    db.add_all([DomesticOrderCommission(order_id=order_id, user_id=row["user_id"],
                                       user_name_snapshot=row["user_name"], rate=Decimal(row["rate"]))
                for row in allocations])
    db.flush()


def order_snapshot(db: Session, order_id: int) -> list[dict]:
    return [{"user_id": row.user_id, "user_name": row.user_name_snapshot,
             "rate": format(row.rate, ".4f")}
            for row in db.query(DomesticOrderCommission).filter_by(order_id=order_id)
            .order_by(DomesticOrderCommission.user_id).all()]
