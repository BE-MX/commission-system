"""Current, source-bound authentication for collector credentials."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.utils import hash_token
from app.auth.models import ArkUser, ArkRole, ArkUserRole, ArkPermission, ArkRolePermission
from app.auth.service import get_live_user_authorization
from app.core.database import get_db
from app.core.time import beijing_now
from app.alibaba_feed.errors import FeedError
from app.integration.auth import IntegrationAuthError, resolve_submission_principal
from app.integration.models import IntegrationApp
from app.alibaba_feed.models import AlibabaFeedSource

_bearer = HTTPBearer(auto_error=False)
FEED_SCOPES = frozenset({"alibaba_feed:read", "alibaba_feed:write"})


@dataclass(frozen=True)
class FeedPrincipal:
    source_id: int
    source_account_uid: str
    actor_user_id: int
    idempotency_namespace: str
    scopes: frozenset[str]
    generation: int
    integration_app_id: int
    token_hash: str


def resolve_feed_principal(db: Session, raw_token: str, *, required_scope: str) -> FeedPrincipal:
    if required_scope not in FEED_SCOPES:
        raise ValueError("Unsupported feed scope")
    principal = resolve_submission_principal(db, raw_token, required_scope=required_scope)
    app = db.query(IntegrationApp).filter(IntegrationApp.public_id == principal.idempotency_namespace).populate_existing().with_for_update().first()
    if app is None or app.token_hash != hash_token(raw_token.strip()) or not app.is_active:
        raise IntegrationAuthError("来源凭证已失效", status_code=401)
    if not set(app.scopes or []).issubset(FEED_SCOPES):
        raise IntegrationAuthError("来源凭证权限无效", status_code=403)
    source = db.query(AlibabaFeedSource).filter(AlibabaFeedSource.integration_app_id == app.id).populate_existing().with_for_update().first()
    if source is None or not source.ingest_enabled or source.consent_state != "authorized":
        raise IntegrationAuthError("来源未启用或未授权", status_code=403)
    return FeedPrincipal(source.id, source.source_account_uid, principal.actor_user_id,
                         principal.idempotency_namespace, principal.scopes,
                         source.collection_generation, app.id, app.token_hash)


def require_feed_scope(scope: str):
    if scope not in FEED_SCOPES:
        raise ValueError("Unsupported feed scope")

    def dependency(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
                   db: Session = Depends(get_db)) -> FeedPrincipal:
        from .pilot_service import require_receiver
        pilot = require_receiver(db)
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="缺少来源 Bearer token")
        try:
            principal = resolve_feed_principal(db, credentials.credentials, required_scope=scope)
        except IntegrationAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        if principal.source_id != pilot.source_id:
            raise FeedError(403, "SOURCE_SCOPE_DENIED")
        return principal
    return dependency


def require_current_feed_admin(current_user: dict = Depends(get_current_user),
                               db: Session = Depends(get_db)) -> dict:
    try:
        user_id = int(current_user["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="来源管理权限不足") from exc
    user = db.query(ArkUser).filter(ArkUser.id == user_id).populate_existing().first()
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status_code=403, detail="当前账号已停用")
    roles, permissions = get_live_user_authorization(db, user_id)
    if "super_admin" not in roles and "alibaba_feed:admin" not in permissions:
        raise HTTPException(status_code=403, detail="需要当前 alibaba_feed:admin 权限")
    return current_user


def recheck_feed_principal(db: Session, principal: FeedPrincipal, *, required_scope: str) -> None:
    """Locking current reads defeat repeatable-read snapshots after a slow upload."""
    app = db.query(IntegrationApp).filter(IntegrationApp.id == principal.integration_app_id).populate_existing().with_for_update().first()
    if (app is None or not app.is_active or app.token_hash != principal.token_hash
            or app.owner_user_id != principal.actor_user_id
            or app.public_id != principal.idempotency_namespace
            or (app.expires_at is not None and app.expires_at <= beijing_now())):
        raise FeedError(401, "TOKEN_INVALID")
    scopes = set(app.scopes or [])
    if required_scope not in scopes or not scopes.issubset(FEED_SCOPES):
        raise FeedError(403, "SOURCE_SCOPE_DENIED")
    owner = db.query(ArkUser).filter(ArkUser.id == app.owner_user_id).populate_existing().with_for_update().first()
    if owner is None or not owner.is_active or owner.deleted_at is not None:
        raise FeedError(401, "TOKEN_INVALID")
    roles = {r[0] for r in db.query(ArkRole.name).join(ArkUserRole, ArkUserRole.role_id == ArkRole.id).filter(ArkUserRole.user_id == owner.id).with_for_update().all()}
    permissions = {r[0] for r in db.query(ArkPermission.code).join(ArkRolePermission, ArkRolePermission.permission_id == ArkPermission.id).join(ArkUserRole, ArkUserRole.role_id == ArkRolePermission.role_id).filter(ArkUserRole.user_id == owner.id).with_for_update().all()}
    if "super_admin" not in roles and required_scope not in permissions:
        raise FeedError(403, "SOURCE_SCOPE_DENIED")
