"""One-store, one-person pilot control shared by both deployments."""
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy.orm import Session

from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.auth.service import get_live_user_authorization
from app.core.time import beijing_now
from app.integration.models import IntegrationApp

from .auth import FEED_SCOPES
from .errors import FeedError
from .models import AlibabaFeedPilot, AlibabaFeedSource
from .source_service import SourceIdentity, _commit, _validated_app, source_payload


class PilotConfiguration(SourceIdentity):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    expected_version: int = Field(gt=0, strict=True)
    integration_app_id: int = Field(gt=0, strict=True)
    user_id: int = Field(gt=0, strict=True)
    owner_alias: str = Field(min_length=1, max_length=200)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("owner_alias")
    @classmethod
    def exact_alias(cls, value):
        if not value.strip():
            raise ValueError("AW owner alias must contain visible characters")
        return value


class PilotActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0, strict=True)
    enabled: StrictBool
    consent_confirmed: StrictBool = False


def read_pilot(db: Session, *, write=False):
    return db.query(AlibabaFeedPilot).filter_by(id=1).populate_existing().with_for_update(read=not write).one_or_none()


def active_pilot(db: Session):
    pilot = read_pilot(db)
    return pilot if pilot and pilot.enabled and pilot.source_id is not None and pilot.user_id is not None else None


def require_receiver(db: Session):
    pilot = active_pilot(db)
    if pilot is None:
        raise FeedError(503, "FEED_DISABLED")
    return pilot


def _draft(db, expected_version):
    pilot = read_pilot(db, write=True)
    if pilot is None:
        raise FeedError(503, "PILOT_CONFIGURATION_UNAVAILABLE")
    if pilot.version != expected_version:
        raise FeedError(409, "PILOT_VERSION_CONFLICT")
    return pilot


def _collector(db, app_id):
    try:
        app = _validated_app(db, app_id)
    except HTTPException as exc:
        raise FeedError(422, "PILOT_COLLECTOR_INVALID", "integration_app_id") from exc
    if set(app.scopes) != FEED_SCOPES:
        raise FeedError(422, "PILOT_COLLECTOR_INVALID", "integration_app_id")
    return app


def _eligible_users(db):
    superadmins = db.query(ArkUserRole.user_id).join(ArkRole, ArkRole.id == ArkUserRole.role_id).filter(ArkRole.name == "super_admin")
    readers = (db.query(ArkUserRole.user_id)
               .join(ArkRolePermission, ArkRolePermission.role_id == ArkUserRole.role_id)
               .join(ArkPermission, ArkPermission.id == ArkRolePermission.permission_id)
               .filter(ArkPermission.code == "client_desk:read"))
    return (db.query(ArkUser).filter(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
                                   ArkUser.id.in_(superadmins.statement) | ArkUser.id.in_(readers.statement))
            .order_by(ArkUser.real_name, ArkUser.username))


def _ensure_user(db, user_id):
    if user_id is None or _eligible_users(db).filter(ArkUser.id == user_id).first() is None:
        raise FeedError(422, "PILOT_USER_INVALID", "user_id")


def _payload(db, pilot):
    source = db.get(AlibabaFeedSource, pilot.source_id) if pilot.source_id is not None else None
    alias = next((name for name, user_id in (source.owner_aliases or {}).items()
                  if user_id == pilot.user_id), "") if source else ""
    return {"version": pilot.version, "enabled": pilot.enabled, "user_id": pilot.user_id,
            "owner_alias": alias, "source": source_payload(source) if source else None}


def _collector_options(db):
    rows = db.query(IntegrationApp).filter(
        IntegrationApp.is_active.is_(True),
        (IntegrationApp.expires_at.is_(None)) | (IntegrationApp.expires_at > beijing_now()),
    ).order_by(IntegrationApp.name, IntegrationApp.id)
    items = []
    for app in rows:
        if set(app.scopes or []) != FEED_SCOPES:
            continue
        roles, permissions = get_live_user_authorization(db, app.owner_user_id)
        if "super_admin" in roles or FEED_SCOPES.issubset(permissions):
            items.append({"id": app.id, "name": app.name, "public_id": app.public_id})
    return items


def get_configuration(db):
    pilot = read_pilot(db)
    if pilot is None:
        raise FeedError(503, "PILOT_CONFIGURATION_UNAVAILABLE")
    return {
        **_payload(db, pilot),
        "collectors": _collector_options(db),
        "users": [{"id": user.id, "username": user.username, "real_name": user.real_name}
                  for user in _eligible_users(db)],
    }


def _set_source_policy(source, *, enabled, actor_id=None, aliases=None):
    if aliases is not None and aliases != (source.owner_aliases or {}):
        source.owner_aliases = aliases
        source.mapping_version += 1
        source.mapping_updated_by = actor_id
    policy = {
        "ingest_enabled": enabled,
        "crm_shared": enabled,
        "consent_state": "authorized" if enabled else (
            "revoked" if source.consent_state == "revoked" else "pending"),
        "ai_egress_allowed": False,
        "private_feed_enabled": False,
    }
    if any(getattr(source, key) != policy[key] for key in ("crm_shared", "consent_state", "ai_egress_allowed", "private_feed_enabled")):
        source.consent_version += 1
    for key, value in policy.items():
        setattr(source, key, value)
    source.version += 1


def save_configuration(db, request: PilotConfiguration, *, actor_id: int):
    pilot = _draft(db, request.expected_version)
    if pilot.enabled:
        raise FeedError(409, "PILOT_PAUSE_REQUIRED")
    _collector(db, request.integration_app_id)
    _ensure_user(db, request.user_id)
    source = (db.query(AlibabaFeedSource).filter_by(source_account_uid=request.source_account_uid)
              .populate_existing().with_for_update().first())
    if source is not None and source.integration_app_id != request.integration_app_id:
        raise FeedError(409, "PILOT_SOURCE_ALREADY_BOUND", "integration_app_id")
    if source is None:
        if db.query(AlibabaFeedSource.id).filter_by(integration_app_id=request.integration_app_id).first():
            raise FeedError(409, "PILOT_COLLECTOR_ALREADY_BOUND", "integration_app_id")
        source = AlibabaFeedSource(source_account_uid=request.source_account_uid,
                                   integration_app_id=request.integration_app_id, name=request.name,
                                   owner_aliases={request.owner_alias: request.user_id}, mapping_updated_by=actor_id)
        db.add(source)
        db.flush()
    else:
        source.name = request.name
        _set_source_policy(source, enabled=False, actor_id=actor_id, aliases={request.owner_alias: request.user_id})
    pilot.source_id = source.id
    pilot.user_id = request.user_id
    pilot.version += 1
    result = _payload(db, pilot)
    _commit(db)
    return result


def set_activation(db, request: PilotActivation):
    pilot = _draft(db, request.expected_version)
    if pilot.enabled == request.enabled:
        return _payload(db, pilot)
    binding = db.query(AlibabaFeedSource.integration_app_id).filter_by(id=pilot.source_id).first()
    if request.enabled:
        if binding is None or not request.consent_confirmed:
            raise FeedError(422, "PILOT_CONSENT_REQUIRED")
        _collector(db, binding[0])
        _ensure_user(db, pilot.user_id)
    source = db.query(AlibabaFeedSource).filter_by(id=pilot.source_id).populate_existing().with_for_update().first()
    if request.enabled and (source is None or set((source.owner_aliases or {}).values()) != {pilot.user_id}):
        raise FeedError(422, "PILOT_MAPPING_REQUIRED")
    if source is not None:
        _set_source_policy(source, enabled=request.enabled)
    pilot.enabled = request.enabled
    pilot.version += 1
    result = _payload(db, pilot)
    _commit(db)
    return result


def guard_managed_source(db, source_uid, fields):
    pilot = read_pilot(db, write=True)
    if fields - {"expected_version", "verified_capabilities"} and pilot and pilot.source_id is not None:
        source = db.get(AlibabaFeedSource, pilot.source_id)
        if source and source.source_account_uid == source_uid:
            raise FeedError(409, "PILOT_MANAGED_SOURCE")
