"""Business services for device management, capabilities and usage."""

from datetime import timedelta

from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import beijing_now
from app.whatsapp_translation.auth import DeviceIdentity, require_translation_device
from app.whatsapp_translation.constants import (
    SUPPORTED_TARGET_LANGUAGES,
    TRANSLATION_DIRECTIONS,
    TRANSLATION_LANGUAGES,
)
from app.whatsapp_translation.models import TranslationDevice, TranslationUsageDaily


def get_session(db: Session, http_credentials: HTTPAuthorizationCredentials | None, extension_version: str | None) -> dict:
    identity = require_translation_device(db, http_credentials, extension_version)
    return {
        "device_id": identity.device_id,
        "expires_at": identity.expires_at,
        "is_admin": identity.is_admin,
        "real_name": identity.real_name,
        "user_id": identity.user_id,
    }


def get_capabilities() -> dict:
    settings = get_settings()
    return {
        "ai_config_version": 1,
        "daily_input_chars": settings.WHATSAPP_TRANSLATION_DAILY_INPUT_CHARS,
        "directions": list(TRANSLATION_DIRECTIONS),
        "max_text_chars": settings.WHATSAPP_TRANSLATION_MAX_TEXT_CHARS,
        "min_extension_version": settings.WHATSAPP_TRANSLATION_MIN_EXTENSION_VERSION,
        "rate_per_minute": settings.WHATSAPP_TRANSLATION_RATE_PER_MINUTE,
        "source_languages": list(TRANSLATION_LANGUAGES),
        "target_languages": list(SUPPORTED_TARGET_LANGUAGES),
    }


def _device_row(device: TranslationDevice) -> dict:
    return {
        "browser_name": device.browser_name,
        "browser_version": device.browser_version,
        "created_at": device.created_at,
        "device_id": device.id,
        "device_name": device.device_name,
        "expires_at": device.expires_at,
        "extension_version": device.extension_version,
        "id": device.id,
        "is_active": device.is_active,
        "last_used_at": device.last_used_at,
        "revoked_at": device.revoked_at,
        "revoke_reason": device.revoke_reason,
    }


def list_my_devices(db: Session, actor_user_id: int) -> list[dict]:
    devices = (
        db.query(TranslationDevice)
        .filter(TranslationDevice.user_id == actor_user_id)
        .order_by(TranslationDevice.created_at.desc())
        .all()
    )
    return [_device_row(device) for device in devices]


def _revoke_device(db: Session, device: TranslationDevice, actor_user_id: int, reason: str) -> None:
    device.is_active = False
    device.revoked_at = beijing_now()
    device.revoked_by = actor_user_id
    device.revoke_reason = reason
    db.commit()


def revoke_my_device(db: Session, actor_user_id: int, device_id: int, reason: str = "employee_revoked") -> dict:
    device = (
        db.query(TranslationDevice)
        .filter(
            TranslationDevice.id == device_id,
            TranslationDevice.user_id == actor_user_id,
        )
        .one_or_none()
    )
    if device is None:
        raise ValueError("device_not_found")
    _revoke_device(db, device, actor_user_id, reason)
    return _device_row(device)


def _usage_rows(db: Session, user_id: int | None) -> list[dict]:
    query = db.query(TranslationUsageDaily)
    if user_id is not None:
        query = query.filter(TranslationUsageDaily.user_id == user_id)
    return [
        {
            "device_id": row.device_id,
            "direction_counts": row.direction_counts,
            "error_counts": row.error_counts,
            "failure_count": row.failure_count,
            "input_chars": row.input_chars,
            "input_tokens": row.input_tokens,
            "language_pair_counts": row.language_pair_counts,
            "output_tokens": row.output_tokens,
            "request_count": row.request_count,
            "success_count": row.success_count,
            "usage_date": row.usage_date,
            "user_id": row.user_id,
        }
        for row in query.order_by(TranslationUsageDaily.usage_date.desc()).limit(90).all()
    ]


def get_my_usage(db: Session, actor_user_id: int) -> list[dict]:
    return _usage_rows(db, actor_user_id)


def list_admin_devices(db: Session) -> list[dict]:
    return [_device_row(device) for device in db.query(TranslationDevice).order_by(TranslationDevice.created_at.desc()).all()]


def revoke_admin_device(db: Session, actor_user_id: int, device_id: int, reason: str) -> dict:
    device = db.get(TranslationDevice, device_id)
    if device is None:
        raise ValueError("device_not_found")
    _revoke_device(db, device, actor_user_id, reason)
    return _device_row(device)


def get_admin_usage(db: Session) -> list[dict]:
    return _usage_rows(db, None)


def get_admin_health(db: Session) -> dict:
    settings = get_settings()
    now = beijing_now()
    return {
        "active_devices": db.query(TranslationDevice).filter(
            TranslationDevice.is_active.is_(True),
            TranslationDevice.expires_at > now,
        ).count(),
        "ai_config_version": 1,
        "daily_input_chars": settings.WHATSAPP_TRANSLATION_DAILY_INPUT_CHARS,
        "expired_devices": db.query(TranslationDevice).filter(
            TranslationDevice.expires_at <= now,
        ).count(),
        "preset_enabled": True,
        "window_days": 1,
    }

