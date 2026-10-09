"""Portal coordination for existing employee authority mutation endpoints."""
from fastapi import HTTPException

from app.portal.access_policy import employee_principal
from app.portal.authority import authority_changed, lock_authority
from app.portal.errors import PortalError, TransactionBusy


def begin_employee_authority_write(db, current_user, permission):
    """Call before the endpoint's first DB read; keep its existing commit boundary.

    Installed authority persists while the storefront is disabled. Only a
    verified pre-portal schema retains the legacy employee path.
    """
    try:
        if lock_authority(db) is None:
            return
        try:
            actor_id = int(current_user.get("sub") or 0)
        except (TypeError, ValueError):
            raise HTTPException(403, "无法确认当前操作人") from None
        employee_principal(db, actor_id, permission)
        authority_changed(db)
    except TransactionBusy:
        raise
    except PortalError as error:
        message = "当前账号无权执行此操作" if error.status == 403 else "授权服务暂不可用"
        raise HTTPException(error.status, message, headers={"Cache-Control":"private, no-store", "Pragma":"no-cache"}) from None


def begin_employee_document_write(db, current_user, *permissions):
    """Before local invoice edits: barrier, live permissions, then document locks.

    Installed authority protects both portal and ordinary local edits, ON/OFF. Do not use
    this around remote synchronization: that would hold authority across I/O.
    Return fresh roles/scopes so stale JWT read_all or super_admin cannot survive.
    Editing a document does not itself change the authority version.
    """
    try:
        if lock_authority(db) is None:
            return current_user
        try:
            actor_id = int(current_user.get("id") or current_user.get("sub") or 0)
        except (TypeError, ValueError):
            raise HTTPException(403, "无法确认当前操作人") from None
        return employee_principal(db, actor_id, *permissions)
    except TransactionBusy:
        raise  # Dedicated app handler returns a safe no-store 503.
    except PortalError as error:
        message = "当前账号无权编辑发票" if error.status == 403 else "发票授权服务暂不可用"
        raise HTTPException(error.status, message, headers={"Cache-Control":"private, no-store", "Pragma":"no-cache"}) from None
