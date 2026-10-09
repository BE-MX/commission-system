"""Login lock state and owner-audited resets; original login logs stay immutable."""

from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.models import ArkAccountUnlockAudit, ArkLoginLog, ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now


class AccountUnlockError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def get_account_lock_states(db: Session, user_ids: list[int]) -> dict[int, dict]:
    """Batch state for a user-list page using the same rule as password login."""
    if not user_ids:
        return {}
    settings = get_settings()
    now = beijing_now()
    resets = db.query(
        ArkAccountUnlockAudit.user_id,
        func.max(ArkAccountUnlockAudit.through_login_log_id).label("through_id"),
    ).filter(ArkAccountUnlockAudit.user_id.in_(user_ids)).group_by(
        ArkAccountUnlockAudit.user_id,
    ).subquery()
    failures = db.query(ArkUser.id, ArkLoginLog.id, ArkLoginLog.created_at).join(
        ArkLoginLog, ArkLoginLog.username == ArkUser.username.collate("utf8mb4_unicode_ci"),
    ).outerjoin(resets, resets.c.user_id == ArkUser.id).filter(
        ArkUser.id.in_(user_ids),
        ArkLoginLog.status == "failed",
        ArkLoginLog.created_at >= now - timedelta(minutes=settings.LOGIN_LOCK_MINUTES),
        ArkLoginLog.id > func.coalesce(resets.c.through_id, 0),
    ).all()
    grouped = {user_id: [] for user_id in user_ids}
    for user_id, log_id, created_at in failures:
        grouped[user_id].append((log_id, created_at))
    states = {}
    for user_id, rows in grouped.items():
        locked = len(rows) >= settings.LOGIN_MAX_FAIL
        expires_at = None
        if locked:
            # If historical concurrency produced more than the threshold, unlock
            # only when fewer than LOGIN_MAX_FAIL failures remain in the window.
            times = sorted(created_at for _, created_at in rows)
            expires_at = times[-settings.LOGIN_MAX_FAIL] + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
        states[user_id] = {
            "login_locked": locked,
            "login_failed_count": len(rows),
            "login_lock_expires_at": expires_at.isoformat() if expires_at else None,
            "through_login_log_id": max((log_id for log_id, _ in rows), default=0),
        }
    return states


def unlock_account(db: Session, user_id: int, operator: dict) -> dict:
    """Serialize with password login on the target user, then record a reset boundary."""
    # Lazy imports avoid access_policy -> auth.service -> account_lock_service.
    from app.portal.authority import lock_authority
    from app.portal.access_policy import employee_principal
    from app.portal.errors import PortalError, TransactionBusy

    try:
        barrier = lock_authority(db)
        target = db.query(ArkUser.id, ArkUser.username, ArkUser.is_active).filter(
            ArkUser.id == user_id, ArkUser.deleted_at.is_(None),
        ).with_for_update().first()
        # Both locks precede the first ordinary read. The resulting RR snapshot
        # includes any failure committed while waiting for the target row lock.
        if barrier is not None:
            employee_principal(db, int(operator["sub"]), "user:write")
        if target is None:
            raise AccountUnlockError("用户不存在", 404)
        if not target.is_active:
            raise AccountUnlockError("账号已禁用，请先启用账号", 400)
        state = get_account_lock_states(db, [user_id])[user_id]
        if not state["login_locked"]:
            db.rollback()
            return {"unlocked": False, "login_locked": False}
        db.add(ArkAccountUnlockAudit(
            user_id=user_id,
            operator_user_id=int(operator["sub"]),
            operator_username=operator.get("username", ""),
            through_login_log_id=state["through_login_log_id"],
            failed_count=state["login_failed_count"],
            created_at=beijing_now(),
        ))
        db.commit()
        return {"unlocked": True, "login_locked": False}
    except TransactionBusy:
        db.rollback()
        raise
    except PortalError as exc:
        db.rollback()
        message = "当前账号无权执行此操作" if exc.status == 403 else "授权服务暂不可用"
        raise AccountUnlockError(message, exc.status) from exc
    except Exception:
        db.rollback()
        raise
