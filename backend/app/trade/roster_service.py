"""Native sales membership does not require an external user identity."""
from sqlalchemy import select
from sqlalchemy.orm import lazyload
from app.auth.models import ArkUser
from app.core.time import beijing_now
from app.trade.models import SalesRoster


def write_roster(db, user_id, body, actor):
    # Lock the parent even for a new membership: two creates must not both
    # observe a missing row under MySQL repeatable read.
    user = db.scalar(select(ArkUser).options(lazyload(ArkUser.roles)).where(ArkUser.id == user_id)
        .with_for_update().execution_options(populate_existing=True))
    if user is None:
        raise ValueError("业务员不存在")
    if body.active and not user.is_active:
        raise ValueError("已停用员工不能加入统计名册")
    row = db.scalar(select(SalesRoster).where(SalesRoster.ark_user_id == user_id)
        .with_for_update().execution_options(populate_existing=True))
    if (row.version if row else 0) != body.expected_version:
        raise ValueError("名册已变更，请刷新后重试")
    if body.department_id is not None:
        from app.trade.department_service import resolve_shares
        resolve_shares(db, [{"department_id": body.department_id, "rate": "100"}])
    if row is None:
        row = SalesRoster(ark_user_id=user_id, version=0)
        db.add(row)
    for key, value in body.model_dump(exclude={"expected_version"}).items():
        setattr(row, key, value)
    row.version += 1
    row.updated_by = int(actor["sub"])
    row.updated_at = beijing_now()
    db.flush()
    return row


def serialize_roster(row, user):
    return {"ark_user_id": user.id, "name": user.real_name or user.username,
        "user_active": bool(user.is_active), "configured": row is not None,
        "version": row.version if row else 0,
        "english_name": row.english_name if row else None,
        "department_id": row.department_id if row else None,
        "team": row.team if row else "", "camp": row.camp if row else "",
        "new_customer_target": row.new_customer_target if row else 0,
        "amount_target": str(row.amount_target) if row else "0.00",
        "active": bool(row and row.active and user.is_active),
        "updated_by": row.updated_by if row else None,
        "updated_at": row.updated_at if row else None}
