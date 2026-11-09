"""Scope membership grants summary access and is checked live for writes."""
from sqlalchemy import and_, exists, or_, select

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.domestic.models import DomesticCustomer
from app.domestic_followup.collaboration_models import (
    FollowupCollaborator, FollowupCollaborationEvent, FollowupHandoff, FollowupResponsibility, FollowupScope,
)

READ = "domestic_followup:read"
WRITE = "domestic_followup:write"
COORDINATE = "domestic_followup:coordinate"
ADMIN = "domestic_followup:admin"


def _holds(db, user_id, code, *, lock=False):
    if lock:
        # Locking read avoids reusing an earlier repeatable-read snapshot during a write.
        stmt = (select(ArkUser.id)
                .join(ArkUserRole, ArkUserRole.user_id == ArkUser.id)
                .join(ArkRole, ArkRole.id == ArkUserRole.role_id)
                .outerjoin(ArkRolePermission, ArkRolePermission.role_id == ArkRole.id)
                .outerjoin(ArkPermission, ArkPermission.id == ArkRolePermission.permission_id)
                .where(ArkUser.id == user_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
                       or_(ArkRole.name == "super_admin", ArkPermission.code == code))
                .limit(1).with_for_update(read=True))
        return db.scalar(stmt) is not None
    from app.domestic_followup.visibility import holds
    return holds(db, user_id, code)


def user_id(user):
    return int(user["sub"])


def claims_allow(user, code):
    return "super_admin" in (user.get("roles") or ()) or code in (user.get("permissions") or ())


def _scope_matches():
    return or_(
        FollowupScope.customer_id == DomesticCustomer.id,
        and_(
            FollowupScope.customer_id.is_(None),
            FollowupScope.province == DomesticCustomer.province,
            or_(FollowupScope.city.is_(None), FollowupScope.city == DomesticCustomer.city),
        ),
    )


def scoped_ids(member_id):
    return select(DomesticCustomer.id).where(
        exists().where(FollowupScope.user_id == member_id, _scope_matches())
    ).correlate(None)


def managed_customer_ids():
    return select(DomesticCustomer.id).where(or_(
        exists().where(FollowupResponsibility.customer_id == DomesticCustomer.id),
        exists().where(_scope_matches()),
    )).correlate(None)


def responsible_ids(member_id):
    return select(FollowupResponsibility.customer_id).where(
        FollowupResponsibility.owner_user_id == member_id
    )


def collaborator_ids(member_id):
    return select(FollowupCollaborator.customer_id).where(FollowupCollaborator.user_id == member_id)


def incoming_ids(member_id):
    return select(FollowupHandoff.customer_id).where(
        FollowupHandoff.recipient_user_id == member_id, FollowupHandoff.status == "pending",
        FollowupHandoff.kind == "offer",
    )


def responsibility_for(db, customer_id, *, lock=False):
    if lock:
        return db.scalar(select(FollowupResponsibility).where(FollowupResponsibility.customer_id == customer_id)
                         .with_for_update().execution_options(populate_existing=True))
    return db.get(FollowupResponsibility, customer_id)


def lock_customer(db, customer_id):
    return db.scalar(select(DomesticCustomer).where(DomesticCustomer.id == customer_id)
                     .with_for_update().execution_options(populate_existing=True))


def customer_is_managed(db, customer, *, lock=False):
    if lock:
        if responsibility_for(db, customer.id, lock=True) is not None:
            return True
        explicit = select(FollowupScope.id).where(FollowupScope.customer_id == customer.id)
        if db.scalar(explicit.limit(1).with_for_update(read=True)) is not None:
            return True
        if not customer.province:
            return False
        regional = select(FollowupScope.id).where(
            FollowupScope.customer_id.is_(None), FollowupScope.province == customer.province,
            or_(FollowupScope.city.is_(None), FollowupScope.city == customer.city),
        )
        return db.scalar(regional.limit(1).with_for_update(read=True)) is not None
    return db.scalar(managed_customer_ids().where(DomesticCustomer.id == customer.id)) is not None


def in_scope(db, member_id, customer_id, *, lock=False):
    if lock:
        customer = db.get(DomesticCustomer, customer_id)
        keys = [f"c:{customer_id}"]
        if customer and customer.province:
            keys.append(f"r:{customer.province}:")
            if customer.city:
                keys.append(f"r:{customer.province}:{customer.city}")
        stmt = select(FollowupScope.id).where(FollowupScope.user_id == member_id, FollowupScope.scope_key.in_(keys))
        return db.scalar(stmt.limit(1).with_for_update(read=True)) is not None
    return db.scalar(scoped_ids(member_id).where(DomesticCustomer.id == customer_id)) is not None


def qualified(db, member_id, customer_id, *, lock=False):
    return in_scope(db, member_id, customer_id, lock=lock) and all(
        _holds(db, member_id, code, lock=lock) for code in (READ, WRITE)
    )


def eligible_member_ids(customer_id):
    from app.domestic_followup.visibility import holder_ids

    return (select(FollowupScope.user_id).join(DomesticCustomer, _scope_matches())
            .where(DomesticCustomer.id == customer_id, FollowupScope.user_id.in_(holder_ids(READ)),
                   FollowupScope.user_id.in_(holder_ids(WRITE))).distinct())


def can_coordinate(db, user, customer, *, lock=False):
    actor = user_id(user)
    return (claims_allow(user, COORDINATE) and in_scope(db, actor, customer.id, lock=lock)
            and _holds(db, actor, COORDINATE, lock=lock))


def can_configure(db, user):
    actor = user_id(user)
    return all(claims_allow(user, code) and _holds(db, actor, code) for code in (COORDINATE, ADMIN))


def can_run_coordination(db, user):
    return claims_allow(user, COORDINATE) and _holds(db, user_id(user), COORDINATE)


def eligible_actor(db, user, customer, *, lock=False):
    return claims_allow(user, WRITE) and qualified(db, user_id(user), customer.id, lock=lock)


def has_live_write(db, user, *, lock=False):
    return claims_allow(user, WRITE) and _holds(db, user_id(user), WRITE, lock=lock)


def has_summary_access(db, user, customer):
    actor = user_id(user)
    if not claims_allow(user, READ) or not _holds(db, actor, READ):
        return False
    return in_scope(db, actor, customer.id)


def has_history_access(db, user, customer):
    actor = user_id(user)
    if not has_summary_access(db, user, customer):
        return False
    responsibility = responsibility_for(db, customer.id)
    return (can_coordinate(db, user, customer)
            or (responsibility is not None and responsibility.owner_user_id == actor)
            or db.get(FollowupCollaborator, (customer.id, actor)) is not None)


def can_develop(db, user, customer, *, lock=False):
    """When writing, the caller first locks the customer row."""
    if customer.status != 1:
        return False
    actor = user_id(user)
    responsibility = responsibility_for(db, customer.id, lock=lock)
    if (responsibility is None or responsibility.owner_user_id is None
            or responsibility.status not in ("following", "handoff")
            or not eligible_actor(db, user, customer, lock=lock)):
        return False
    if responsibility.owner_user_id == actor:
        return True
    return (qualified(db, responsibility.owner_user_id, customer.id, lock=lock)
            and (can_coordinate(db, user, customer, lock=lock)
                 or db.get(FollowupCollaborator, (customer.id, actor),
                           with_for_update={"read": True} if lock else None, populate_existing=lock) is not None))


def create_initial_responsibility(db, customer_id, owner_user_id):
    """Only use when creating a new customer in the same transaction."""
    responsibility = FollowupResponsibility(customer_id=customer_id, owner_user_id=owner_user_id,
                                            status="following", stage="new")
    db.add(FollowupScope(user_id=owner_user_id, customer_id=customer_id, scope_key=f"c:{customer_id}",
                         added_by_user_id=owner_user_id))
    db.add(responsibility)
    db.add(FollowupCollaborationEvent(
        customer_id=customer_id, actor_user_id=owner_user_id, action="initialize", to_user_id=owner_user_id,
        responsibility_version=1, details={"source": "quick_create"},
    ))
    db.flush()
    return responsibility



def history_customer_ids(member_id, coordinate=False):
    """SQL equivalent of the incremental history grant for bulk projections."""
    from app.domestic_followup.visibility import holder_ids

    allowed = or_(
        DomesticCustomer.id.in_(responsible_ids(member_id)),
        DomesticCustomer.id.in_(collaborator_ids(member_id)),
    )
    if coordinate:
        allowed = or_(allowed, exists(holder_ids(COORDINATE).where(ArkUser.id == member_id)))
    return scoped_ids(member_id).where(
        allowed, exists(holder_ids(READ).where(ArkUser.id == member_id))
    )
