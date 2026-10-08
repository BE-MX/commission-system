"""Current employee authorization before local quotation-source mutations."""
import logging
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.auth.dependencies import require_permission
from app.portal.upstream_authority import begin_employee_document_write

PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}
logger = logging.getLogger(__name__)


def begin_write(db, claims, permission):
    """Keep price writes ordered with acceptance/approval and authority changes.

    JWT only locates an employee once the permanent protocol is installed.
    A verified pre-portal schema retains its original JWT permission rule.
    Caller owns the single transaction commit; no remote I/O belongs here.
    """
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise HTTPException(409, "价格维护必须从新事务开始，请重新提交", headers=PRIVATE_HEADERS)
    db.expire_all()
    try:
        actor = begin_employee_document_write(db, claims, permission)
        if actor is claims:
            # The existing helper returns the input only after verifying the
            # absent barrier against the exact supported pre-portal schema.
            require_permission(permission)(claims)
        return actor
    except HTTPException as error:
        if error.status_code == 403:
            raise HTTPException(403, "当前账号无权维护价格", headers=PRIVATE_HEADERS) from None
        raise
    except SQLAlchemyError:
        diagnostics = []
        try:
            logger.warning("Price authorization unavailable")
        except Exception as failure:
            diagnostics.append(failure)
        try:
            print("[invoice-price] authorization unavailable", flush=True)
        except Exception as failure:
            diagnostics.append(failure)
        response = HTTPException(503, "价格维护授权暂不可用，请稍后重试", headers=PRIVATE_HEADERS)
        if diagnostics:
            raise response from ExceptionGroup("Price authorization diagnostics failed", diagnostics)
        raise response from None
