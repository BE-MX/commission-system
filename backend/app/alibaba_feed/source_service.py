"""Server-side provisioning of collector source bindings."""
import logging
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.alibaba_feed.auth import FEED_SCOPES
from app.alibaba_feed.models import AlibabaFeedSource
from app.core.time import beijing_now
from app.integration.models import IntegrationApp
from app.integration.service import _active_owner

logger = logging.getLogger(__name__)


class SourceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_account_uid: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    integration_app_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)


class SourceCreate(SourceIdentity):
    ingest_enabled: bool = False
    consent_state: Literal["pending", "authorized", "revoked"] = "pending"


class VerifiedCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stable_message_ids: StrictBool = False
    reliable_order: StrictBool = False
    latest_coverage: StrictBool = False
    human_identity: StrictBool = False
    activity_scan: StrictBool = False
    deletions: StrictBool = False
    evidence_note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def evidence_required(self):
        if any(value is True for value in self.model_dump().values()) and not self.evidence_note.strip():
            raise ValueError("Capability verification requires evidence")
        return self


class SourcePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    ingest_enabled: bool | None = None
    consent_state: Literal["pending", "authorized", "revoked"] | None = None
    crm_shared: bool | None = None
    ai_egress_allowed: bool | None = None
    private_feed_enabled: bool | None = None
    owner_aliases: dict[str, StrictInt] | None = None
    verified_capabilities: VerifiedCapabilities | None = None

    @field_validator("owner_aliases")
    @classmethod
    def exact_aliases(cls, aliases):
        if aliases is not None and (len(aliases) > 500 or any(not name.strip() or len(name) > 200 or uid <= 0 for name, uid in aliases.items())):
            raise ValueError("Invalid owner mapping")
        return aliases


def source_payload(row: AlibabaFeedSource) -> dict:
    return {key: getattr(row, key) for key in ("source_account_uid", "integration_app_id", "name", "ingest_enabled", "consent_state", "crm_shared", "ai_egress_allowed", "private_feed_enabled", "owner_aliases", "mapping_version", "consent_version", "collection_generation", "version", "verified_capabilities", "capability_version", "legacy_identity_blocked")}


def _validated_app(db: Session, app_id: int) -> IntegrationApp:
    app = db.query(IntegrationApp).filter(IntegrationApp.id == app_id).populate_existing().with_for_update().first()
    if app is None:
        raise HTTPException(status_code=404, detail="接入应用不存在")
    if not app.is_active or (app.expires_at is not None and app.expires_at <= beijing_now()):
        raise HTTPException(status_code=409, detail="接入应用已停用或过期")
    scopes = set(app.scopes or [])
    if not scopes or not scopes.issubset(FEED_SCOPES) or "alibaba_feed:write" not in scopes:
        raise HTTPException(status_code=422, detail="来源必须绑定 feed 专用写入凭据")
    _active_owner(db, app.owner_user_id, scopes)
    return app


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Feed source uniqueness conflict")
        print("[alibaba_feed] source uniqueness conflict", flush=True)
        raise HTTPException(status_code=409, detail="来源或应用已绑定") from exc
    except Exception:
        db.rollback()
        logger.warning("Feed source commit failed")
        print("[alibaba_feed] source commit failed", flush=True)
        raise


def create_source(db: Session, request: SourceCreate) -> dict:
    _validated_app(db, request.integration_app_id)
    if request.ingest_enabled and request.consent_state != "authorized":
        raise HTTPException(status_code=422, detail="启用接收前必须确认来源授权")
    row = AlibabaFeedSource(**request.model_dump())
    db.add(row)
    _commit(db)
    db.refresh(row)
    return source_payload(row)


def update_source(db: Session, source_uid: str, request: SourcePatch, *, actor_id: int | None = None) -> dict:
    # Enabling follows the receiver lock order: App first, then source.
    if request.ingest_enabled is True:
        binding = db.query(AlibabaFeedSource.integration_app_id).filter(AlibabaFeedSource.source_account_uid == source_uid).first()
        if binding is None:
            raise HTTPException(status_code=404, detail="来源不存在")
        _validated_app(db, binding[0])
    row = db.query(AlibabaFeedSource).filter(AlibabaFeedSource.source_account_uid == source_uid).populate_existing().with_for_update().first()
    if row is None:
        raise HTTPException(status_code=404, detail="来源不存在")
    if row.version != request.expected_version:
        raise HTTPException(status_code=409, detail="来源配置已更新，请刷新后重试")
    values = request.model_dump(exclude_unset=True, exclude={"expected_version"})
    if any(value is None for value in values.values()):
        raise HTTPException(status_code=422, detail="来源配置字段不能为 null")
    consent = values.get("consent_state", row.consent_state)
    if consent != "authorized":
        values["ingest_enabled"] = False
    if "owner_aliases" in values:
        ids = set(values["owner_aliases"].values())
        active = {u.id for u in db.query(ArkUser).filter(ArkUser.id.in_(ids), ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)).populate_existing().all()}
        if active != ids:
            raise HTTPException(status_code=422, detail="负责人必须是有效方舟用户")
        if values["owner_aliases"] != (row.owner_aliases or {}):
            row.mapping_version += 1
            row.mapping_updated_by = actor_id
    if "verified_capabilities" in values and values["verified_capabilities"] != (row.verified_capabilities or {}):
        row.capability_version += 1
    if any(key in values and values[key] != getattr(row, key) for key in ("consent_state", "crm_shared", "ai_egress_allowed", "private_feed_enabled", "verified_capabilities")):
        row.consent_version += 1
    for key, value in values.items():
        setattr(row, key, value)
    row.version += 1
    _commit(db)
    db.refresh(row)
    return source_payload(row)


def list_sources(db: Session) -> dict:
    return {"items": [source_payload(row) for row in db.query(AlibabaFeedSource).order_by(AlibabaFeedSource.id)]}


def list_owners(db: Session) -> dict:
    rows = db.query(ArkUser).filter(ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None)).order_by(ArkUser.id)
    return {"items": [{"id": row.id, "username": row.username, "real_name": row.real_name} for row in rows]}
