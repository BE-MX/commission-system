"""Live device-token authorization for the translation extension."""

from datetime import datetime

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.auth.service import get_live_user_authorization
from app.core.config import get_settings
from app.core.time import beijing_now
from app.whatsapp_translation.constants import (
    WHATSAPP_TRANSLATION_WRITE_PERMISSION,
)
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.models import TranslationDevice


_bearer = HTTPBearer(auto_error=False)


class DeviceIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: int
    device_id: int
    real_name: str
    extension_version: str
    expires_at: datetime
    is_admin: bool


def _error(status_code: int, error_code: str, retry_after: int | None = None) -> WhatsAppTranslationError:
    return WhatsAppTranslationError(status_code, error_code, "WhatsApp translation authorization failed", retry_after)


def require_translation_device(
    db: Session,
    http_credentials: HTTPAuthorizationCredentials | None,
    extension_version: str | None,
) -> DeviceIdentity:
    settings = get_settings()
    if http_credentials is None or not http_credentials.credentials:
        raise _error(401, "invalid_bearer")
    if not extension_version or not _is_semantic_version(extension_version):
        raise _error(400, "extension_version_invalid")

    token_hash = __import__("hashlib").sha256(http_credentials.credentials.encode("utf-8")).hexdigest()
    device = db.query(TranslationDevice).filter(TranslationDevice.token_hash == token_hash).one_or_none()
    if device is None:
        raise _error(401, "device_not_found")
    if not device.is_active:
        raise _error(403, "device_revoked")
    if device.expires_at <= beijing_now():
        raise _error(401, "device_expired")

    user = db.get(ArkUser, device.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise _error(403, "user_inactive")
    roles, permissions = get_live_user_authorization(db, user.id)
    if WHATSAPP_TRANSLATION_WRITE_PERMISSION not in permissions:
        raise _error(403, "permission_denied")

    is_admin = "super_admin" in roles or "whatsapp_translation:admin" in permissions
    device.extension_version = extension_version
    device.last_used_at = beijing_now()
    db.commit()

    return DeviceIdentity(
        user_id=user.id,
        device_id=device.id,
        real_name=user.real_name,
        extension_version=extension_version,
        expires_at=device.expires_at,
        is_admin=is_admin,
    )


def _is_semantic_version(value: str) -> bool:
    segments = value.split(".")
    return len(segments) == 3 and all(segment.isdigit() for segment in segments)


def require_supported_extension(identity: DeviceIdentity) -> DeviceIdentity:
    settings = get_settings()
    minimum = tuple(int(part) for part in settings.WHATSAPP_TRANSLATION_MIN_EXTENSION_VERSION.split("."))
    current = tuple(int(part) for part in identity.extension_version.split("."))
    if current < minimum:
        raise _error(426, "extension_outdated", retry_after=300)
    return identity


def require_admin_device(identity: DeviceIdentity, db: Session) -> DeviceIdentity:
    roles, permissions = get_live_user_authorization(db, identity.user_id)
    if not ("super_admin" in roles or "whatsapp_translation:admin" in permissions):
        raise _error(403, "admin_required")
    return identity


