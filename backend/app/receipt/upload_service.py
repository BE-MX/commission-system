"""Current employee upload rights, unlocked storage, fenced registration."""
import logging
from fastapi import HTTPException
from app.portal.authority import lock_authority
from app.portal.errors import PortalError, TransactionBusy
from sqlalchemy.exc import SQLAlchemyError
from app.receipt import access, attachments, authority, retry_service

logger = logging.getLogger(__name__)


def _authorized(db, user):
    authority.fresh_boundary(db)
    try:
        lock_authority(db, force=True)
        return authority.current_user(db, user, "receipt:write", "invoice:write", any_permission=True)
    except TransactionBusy:
        raise
    except PortalError as error:
        raise HTTPException(error.status, "回款凭证授权暂不可用",
            headers={"Cache-Control": "private, no-store", "Pragma": "no-cache"}) from None
    except SQLAlchemyError as error:
        authority.unavailable(error)


def begin(db, user):
    current = _authorized(db, user)
    actor = access.user_id(current)
    db.commit()  # Release authority before proxy, image validation or storage IO.
    return actor


def finish(db, staged, user):
    try:
        current = _authorized(db, user)
        actor = access.user_id(current)
        if actor != staged.data.created_by:
            raise HTTPException(403, "上传操作人已变化")
    except (HTTPException, TransactionBusy) as denial:
        # Registration has not begun. Never run storage deletion under DB locks.
        db.rollback()
        try:
            attachments.discard_upload(staged)
        except Exception as error:
            # Preserve the permission denial; leave a private orphan for reconciliation.
            failures = [error]
            try:
                logger.warning("Receipt upload cleanup pending (%s)", type(error).__name__)
            except Exception as diagnostic:
                failures.append(diagnostic)
            try:
                print("[receipt] private upload cleanup pending", flush=True)
            except Exception as diagnostic:
                failures.append(diagnostic)
            denial.__cause__ = ExceptionGroup("Private upload cleanup pending", failures)
        raise
    # Any flush/commit uncertainty after here must keep the file for the real row.
    return attachments.register_upload(db, staged, actor)


def unavailable(error):
    retry_service._unavailable(error, message="回款凭证上传结果暂不能确认，请核对上传记录；勿自动重复上传")
