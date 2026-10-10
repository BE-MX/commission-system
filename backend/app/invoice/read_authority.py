"""Current employee authorization before invoice collection reads."""
import logging

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.auth.service import get_live_user_authorization

logger = logging.getLogger(__name__)
PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}


def current_user(db, claims, *permissions):
    """JWT identifies the employee; current roles determine action and scope.

    The caller may accept any of the supplied actions; collections default to read.
    Ordinary read authorization has one fresh snapshot. It does not acquire
    write barriers or hold an employee lock until the response is delivered.
    """
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise HTTPException(409, "发票查询必须从新事务开始，请重新读取", headers=PRIVATE_HEADERS)
    db.expire_all()
    try:
        actor = int(claims.get("sub") or 0)
        if actor < 1:
            raise ValueError("Invalid identity")
    except (TypeError, ValueError):
        raise HTTPException(403, "无法确认当前查询人", headers=PRIVATE_HEADERS) from None
    try:
        roles, live_permissions = get_live_user_authorization(db, actor)
    except SQLAlchemyError:
        diagnostics = []
        try:
            logger.warning("Invoice read authorization unavailable")
        except Exception as failure:
            diagnostics.append(failure)
        try:
            print("[invoice] read authorization unavailable", flush=True)
        except Exception as failure:
            diagnostics.append(failure)
        response = HTTPException(503, "发票查询授权暂不可用，请稍后重试", headers=PRIVATE_HEADERS)
        if diagnostics:
            raise response from ExceptionGroup("Invoice authorization diagnostics failed", diagnostics)
        raise response from None
    required = permissions or ("invoice:read",)
    if not roles or ("super_admin" not in roles and not set(required).intersection(live_permissions)):
        raise HTTPException(403, "当前账号无权读取发票", headers=PRIVATE_HEADERS)
    return {**claims, "id": actor, "sub": str(actor), "roles": roles, "permissions": live_permissions}
