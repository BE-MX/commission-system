"""Opaque Integration App token authentication for external site requests."""

from dataclasses import dataclass
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.auth.utils import hash_token
from app.core.database import get_db
from app.core.time import beijing_now
from app.integration.models import IntegrationApp


logger = logging.getLogger("commission.integration.auth")
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class SubmissionPrincipal:
    actor_user_id: int
    sales_user_id: int
    idempotency_namespace: str
    scopes: frozenset[str]


class IntegrationAuthError(Exception):
    def __init__(self, message: str, *, status_code: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _fail(message: str, *, forbidden: bool = False) -> None:
    raise IntegrationAuthError(
        message,
        status_code=(status.HTTP_403_FORBIDDEN if forbidden else status.HTTP_401_UNAUTHORIZED),
    )


def require_permission_current_integration_admin(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Recheck the JWT subject's current DB authorization for credential management."""
    try:
        user_id = int(current_user["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号无权管理站点接入凭证",
        ) from exc

    with db.no_autoflush:
        user = db.query(ArkUser).filter(ArkUser.id == user_id).first()
        if user is None or not user.is_active or user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前账号不存在、已停用或已删除",
            )
        roles = set(get_user_roles(user))
        permissions = set(get_user_permissions(user))
    if "super_admin" not in roles and "integration:admin" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足，需要当前 integration:admin 权限",
        )
    return current_user


def _touch_last_used_at(db: Session, app_id: int) -> None:
    """Update telemetry inside a connection savepoint without flushing Session state."""
    connection = db.connection()
    savepoint = connection.begin_nested()
    try:
        connection.execute(
            update(IntegrationApp)
            .where(IntegrationApp.id == app_id)
            .values(last_used_at=beijing_now())
        )
        savepoint.commit()
    except Exception:
        savepoint.rollback()
        raise


def resolve_submission_principal(
    db: Session,
    raw_token: str,
    *,
    required_scope: str,
) -> SubmissionPrincipal:
    """Resolve one site token using current App and owner authorization state."""
    token = (raw_token or "").strip()
    if not token.startswith("ark_live_"):
        _fail("站点 access token 无效")

    with db.no_autoflush:
        row = db.query(IntegrationApp).filter(
            IntegrationApp.token_hash == hash_token(token)
        ).first()
        if row is None or not row.is_active:
            _fail("站点 access token 无效或已被吊销")
        if row.expires_at is not None and row.expires_at <= beijing_now():
            _fail("站点 access token 已过期")

        owner = db.query(ArkUser).filter(ArkUser.id == row.owner_user_id).first()
        if owner is None or not owner.is_active or owner.deleted_at is not None:
            _fail("站点 access token 对应账号不存在或已停用")

        configured_scopes = row.scopes if isinstance(row.scopes, list) else []
        scopes = frozenset(str(scope) for scope in configured_scopes)
        if required_scope not in scopes:
            _fail(f"站点凭证缺少权限: {required_scope}", forbidden=True)

        roles = set(get_user_roles(owner))
        permissions = set(get_user_permissions(owner))
        if "super_admin" not in roles and required_scope not in permissions:
            _fail(f"站点凭证所有人的权限已被撤回: {required_scope}", forbidden=True)

        principal = SubmissionPrincipal(
            actor_user_id=owner.id,
            sales_user_id=owner.id,
            idempotency_namespace=row.public_id,
            scopes=scopes,
        )
        app_id = row.id

    try:
        _touch_last_used_at(db, app_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "刷新 integration_app.last_used_at 失败 app_id=%s err=%s",
            app_id,
            exc,
        )
        print(
            f"[integration.auth] last_used_at update failed id={app_id} err={exc}",
            flush=True,
        )

    return principal


def require_integration_scope(scope: str):
    """FastAPI dependency factory for exact `ark_live_` Bearer credentials."""

    def dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
        db: Session = Depends(get_db),
    ) -> SubmissionPrincipal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少站点 Bearer access token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return resolve_submission_principal(
                db,
                credentials.credentials,
                required_scope=scope,
            )
        except IntegrationAuthError as exc:
            headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.message,
                headers=headers,
            ) from exc

    return dependency
