"""Coordination settings, historical initialization and exception queue."""
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError

from app.auth.models import ArkUser
from app.domestic.models import DomesticCustomer
from app.domestic_followup import collaboration_access as access, collaboration_projection as views, visibility
from app.domestic_followup.collaboration_models import FollowupResponsibility, FollowupScope
from app.domestic_followup.collaboration_service import fingerprint, record_event
from app.domestic_followup.collaboration_tasks import active_tasks
from app.domestic_followup.models import DomesticFollowupConfig


def _require_configure(db, user):
    if not access.can_configure(db, user):
        raise PermissionError("需要内贸跟进设置管理及协调权限")


def _require_coordinate(db, user):
    if not access.can_run_coordination(db, user):
        raise PermissionError("需要内贸跟进协调权限")


def _scope_row(scope, user_name):
    return {"id": scope.id, "user_id": scope.user_id, "user_name": user_name, "customer_id": scope.customer_id,
            "province": scope.province, "city": scope.city}


def list_scopes(db, user, page, page_size):
    _require_configure(db, user)
    query = select(FollowupScope, ArkUser.real_name).join(ArkUser, ArkUser.id == FollowupScope.user_id)
    records = db.execute(query.order_by(FollowupScope.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [_scope_row(scope, name) for scope, name in records],
            "total": db.scalar(select(func.count()).select_from(FollowupScope))}


def add_scope(db, user, payload):
    _require_configure(db, user)
    member = db.get(ArkUser, payload.user_id)
    if member is None or not visibility.holds(db, payload.user_id, access.READ):
        raise ValueError("请选择仍在职且有内贸跟进读取权限的人员")
    if payload.customer_id:
        if access.lock_customer(db, payload.customer_id) is None:
            raise LookupError("客户不存在")
        key = f"c:{payload.customer_id}"
    else:
        region = select(DomesticCustomer.id).where(DomesticCustomer.province == payload.province)
        if payload.city:
            region = region.where(DomesticCustomer.city == payload.city)
        if db.scalar(region.limit(1)) is None:
            raise ValueError("请选择客户档案已有的地区")
        key = f"r:{payload.province}:{payload.city or ''}"
    query = select(FollowupScope).where(FollowupScope.user_id == payload.user_id, FollowupScope.scope_key == key)
    scope = db.scalar(query)
    if scope is None:
        try:
            with db.begin_nested():
                scope = FollowupScope(**payload.model_dump(), scope_key=key, added_by_user_id=access.user_id(user))
                db.add(scope)
                db.flush()
        except IntegrityError as exc:
            # Another coordinator may have just added this exact same grant.
            scope = db.scalar(query.with_for_update())
            if scope is None:
                raise exc
    return _scope_row(scope, member.real_name)


def delete_scope(db, user, scope_id):
    _require_configure(db, user)
    scope = db.get(FollowupScope, scope_id)
    if scope and scope.customer_id:
        access.lock_customer(db, scope.customer_id)
    if scope:
        db.delete(scope)
        db.flush()
    return {"id": scope_id}


def users_for_scope(db, user, q):
    _require_configure(db, user)
    stmt = select(ArkUser.id, ArkUser.real_name).where(ArkUser.id.in_(visibility.holder_ids(access.READ)))
    if q:
        stmt = stmt.where(ArkUser.real_name.contains(q, autoescape=True))
    return [{"user_id": member, "name": name} for member, name in
            db.execute(stmt.order_by(ArkUser.real_name, ArkUser.id).limit(50))]


def coordination_settings(db, user, days=None):
    _require_configure(db, user)
    if days is not None:
        row = db.get(DomesticFollowupConfig, views.PENDING_DAYS_KEY, with_for_update=True)
        if row is None:
            row = DomesticFollowupConfig(key=views.PENDING_DAYS_KEY)
            db.add(row)
        row.value = days
        row.updated_by = access.user_id(user)
        db.flush()
    return {"pending_handoff_days": views.pending_handoff_days(db)}


def _scoped_customers(user):
    return select(DomesticCustomer).where(DomesticCustomer.id.in_(access.scoped_ids(access.user_id(user))))


def _initialization_row(db, customer, *, lock=False):
    owner = customer.owner_user_id
    tasks = [task for task in active_tasks(db, customer.id, lock=lock)
             if task.task_type == "plan" and task.purpose in (None, "development")]
    issues = []
    if customer.status != 1:
        issues.append("customer_inactive")
    if not customer.province:
        issues.append("missing_region")
    if owner is None:
        issues.append("missing_owner")
    elif not access.qualified(db, owner, customer.id, lock=lock):
        issues.append("owner_ineligible")
    if any(task.assignee_user_id != owner for task in tasks):
        issues.append("development_conflict")
    return {
        "customer_id": customer.id, "shop_name": customer.shop_name, "owner_user_id": owner,
        "candidate_owner_user_id": owner if not issues else None, "issues": issues,
        "token": fingerprint([customer.id, customer.status, owner, customer.province, customer.city, issues,
                              [[task.id, task.assignee_user_id, task.purpose, task.due_date.isoformat(),
                                task.updated_at.isoformat()] for task in tasks]]),
    }


def preview_initialization(db, user, page, page_size):
    _require_coordinate(db, user)
    stmt = _scoped_customers(user).where(~exists().where(FollowupResponsibility.customer_id == DomesticCustomer.id))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(DomesticCustomer.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_initialization_row(db, customer) for customer in rows], "total": total}


def apply_initialization(db, user, entries):
    _require_coordinate(db, user)
    if len({entry.customer_id for entry in entries}) != len(entries):
        raise ValueError("初始化清单包含重复客户")
    actor = access.user_id(user)
    results = []
    # Stable lock order across batches and interactive actions.
    for entry in sorted(entries, key=lambda entry: entry.customer_id):
        customer = access.lock_customer(db, entry.customer_id)
        if customer is None or not access.can_coordinate(db, user, customer, lock=True):
            results.append({"customer_id": entry.customer_id, "status": "changed", "owner_user_id": None})
            continue
        existing = access.responsibility_for(db, customer.id, lock=True)
        if existing:
            results.append({"customer_id": customer.id, "status": "existing", "owner_user_id": existing.owner_user_id})
            continue
        row = _initialization_row(db, customer, lock=True)
        if row["token"] != entry.token:
            results.append({"customer_id": customer.id, "status": "changed", "owner_user_id": None})
            continue
        owner = row["candidate_owner_user_id"]
        responsibility = FollowupResponsibility(
            customer_id=customer.id, owner_user_id=owner, version=1,
            status="following" if owner else "unassigned", stage="new" if owner else None,
        )
        db.add(responsibility)
        record_event(db, responsibility, actor, "initialize", new_owner=owner, details={"issues": row["issues"]})
        results.append({"customer_id": customer.id, "status": "initialized", "owner_user_id": owner})
    db.flush()
    return {"items": results}


def coordination_queue(db, user, page, page_size):
    _require_coordinate(db, user)
    stmt = (_scoped_customers(user)
            .join(FollowupResponsibility, FollowupResponsibility.customer_id == DomesticCustomer.id)
            .add_columns(FollowupResponsibility).order_by(DomesticCustomer.id))
    rows = []
    pending_days = views.pending_handoff_days(db)
    for customer, responsibility in db.execute(stmt):
        reasons = views.coordination_reasons(db, customer, responsibility, views.pending_handoff(db, customer.id),
                                             pending_days=pending_days)
        if reasons:
            rows.append({"customer_id": customer.id, "shop_name": customer.shop_name,
                         "owner_user_id": responsibility.owner_user_id, "state": responsibility.status,
                         "coordination_reasons": reasons})
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": len(rows)}
