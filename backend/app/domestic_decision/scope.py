"""Resolve current database permissions and current customer ownership."""

from fastapi import HTTPException
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.domestic.models import DomesticCustomer


def live_actor(db, jwt_actor, *permissions):
    user_id = jwt_actor.get("id") or jwt_actor.get("user_id") or jwt_actor.get("sub")
    user = db.query(ArkUser).filter(ArkUser.id == user_id).populate_existing().first()
    if not user or not user.is_active or user.deleted_at is not None:
        raise HTTPException(401, "账号不可用")
    role_rows = db.query(ArkRole.id, ArkRole.name).join(ArkUserRole, ArkUserRole.role_id == ArkRole.id).filter(ArkUserRole.user_id == user.id).all()
    roles = [r.name for r in role_rows]
    codes = [r[0] for r in db.query(ArkPermission.code).join(ArkRolePermission, ArkRolePermission.permission_id == ArkPermission.id).filter(ArkRolePermission.role_id.in_([r.id for r in role_rows])).distinct().all()]
    actor = {"id": user.id, "user_id": user.id, "real_name": user.real_name, "roles": roles, "permissions": codes}
    for permission in ("domestic_decision:read", *permissions):
        if not has_permission(actor, permission):
            raise HTTPException(403, "缺少经营分析权限")
    return actor


def has_permission(actor, permission):
    return "super_admin" in actor.get("roles", []) or permission in actor.get("permissions", [])


def customer_query(db, actor):
    query = db.query(DomesticCustomer)
    if not has_permission(actor, "domestic_decision:read_all"):
        query = query.filter(DomesticCustomer.owner_user_id == actor["id"])
    return query


def require_customer(db, actor, customer_id):
    customer = customer_query(db, actor).filter(DomesticCustomer.id == customer_id).populate_existing().first()
    if not customer:
        raise HTTPException(404, "客户不存在或不在当前范围")
    return customer
