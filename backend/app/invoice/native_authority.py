"""Live human authority before native economic HTTP writes.

Lock order starts at the existing employee/portal barrier. No JWT role, supplied
route or cached capabilities can grant a command. Caller keeps commit ownership.
"""
from fastapi import HTTPException
from app.auth.service import get_live_user_authorization
from app.portal.upstream_authority import begin_employee_document_write


def require_write(db, user, *permissions, any_permission=False):
    try:
        actor = int(user.get("sub") or user.get("id") or 0)
    except (TypeError, ValueError):
        actor = 0
    if actor < 1:
        raise HTTPException(403, "无法确认当前操作人")
    scope = (db.get_transaction(), db.get_nested_transaction())
    if db.in_transaction() and db.info.get("portal_authority_scope") != scope:
        raise HTTPException(409, "交易写入必须从新授权事务开始，请重新提交")
    claims = {"sub": str(actor), "id": actor}
    owns_boundary = not db.in_transaction()
    try:
        begin_employee_document_write(db, claims, *(permissions if not any_permission else ()))
        roles, current = get_live_user_authorization(db, actor)
        allowed = bool(set(permissions).intersection(current)) if any_permission else all(item in current for item in permissions)
        if not roles or ("super_admin" not in roles and not allowed):
            raise HTTPException(403, "当前账号无权执行此交易操作")
    except Exception:
        if owns_boundary:
            db.rollback()
        raise
    return {**claims, "roles": roles, "permissions": current}
