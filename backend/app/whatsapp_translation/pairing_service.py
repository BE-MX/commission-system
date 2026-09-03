"""Loss-safe, atomic device pairing transitions."""

from datetime import timedelta
from hashlib import sha256
from urllib.parse import quote

from app.whatsapp_translation.errors import WhatsAppTranslationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth.models import ArkRole, ArkUser
from app.auth.service import get_user_permissions
from app.core.config import get_settings
from app.core.time import beijing_now
from app.whatsapp_translation.constants import (
    ERROR_DEVICE_LIMIT,
    ERROR_DEVICE_REVOKED,
    ERROR_PAIRING_CONFLICT,
    ERROR_PAIRING_EXPIRED,
    ERROR_PAIRING_NOT_FOUND,
    ERROR_PAIRING_PENDING,
    ERROR_PAIRING_STATE,
    ERROR_USER_FORBIDDEN,
    ERROR_USER_INACTIVE,
    WHATSAPP_TRANSLATION_WRITE_PERMISSION,
)
from app.whatsapp_translation.models import TranslationDevice, TranslationPairing
from app.whatsapp_translation.schemas import (
    PairingCodeRequest,
    PairingCreate,
    PairingCreated,
    PairingExchangeResult,
)


def hash_secret(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _pairing_result(pairing: TranslationPairing) -> PairingExchangeResult:
    return PairingExchangeResult(
        status="pending",
        device_id=None,
        expires_at=pairing.expires_at,
    )


def _ready_result(device: TranslationDevice | None) -> PairingExchangeResult:
    if device is None or not device.is_active:
        raise WhatsAppTranslationError(409, ERROR_DEVICE_REVOKED, "WhatsApp translation request failed")
    return PairingExchangeResult(
        status="ready",
        device_id=device.id,
        expires_at=device.expires_at,
    )


def _get_pairing_for_update(db: Session, device_code_hash: str) -> TranslationPairing | None:
    query = (
        select(TranslationPairing)
        .where(TranslationPairing.device_code_hash == device_code_hash)
        .with_for_update()
    )
    return db.execute(query).scalar_one_or_none()


def _require_unexpired(pairing: TranslationPairing) -> None:
    if pairing.expires_at <= beijing_now():
        raise WhatsAppTranslationError(410, ERROR_PAIRING_EXPIRED, "WhatsApp translation request failed")


def create_pairing(db: Session, payload: PairingCreate) -> PairingCreated:
    settings = get_settings()
    device_code = __import__("secrets").token_urlsafe(32)
    pairing = TranslationPairing(
        device_code_hash=hash_secret(device_code),
        proposed_token_hash=payload.proposed_token_hash,
        device_name=payload.device_name,
        browser_name=payload.browser_name,
        browser_version=payload.browser_version,
        extension_version=payload.extension_version,
        status="pending",
        expires_at=beijing_now() + timedelta(minutes=settings.WHATSAPP_TRANSLATION_PAIRING_TTL_MINUTES),
    )
    db.add(pairing)
    db.commit()
    authorize_url = (
        settings.SHORT_LINK_BASE_URL.rstrip("/")
        + "/whatsapp-translation/authorize#device_code="
        + quote(device_code)
    )
    return PairingCreated(
        device_code=device_code,
        expires_at=pairing.expires_at,
        authorize_url=authorize_url,
    )


def inspect_pairing(db: Session, payload: PairingCodeRequest) -> PairingExchangeResult:
    pairing = _get_pairing_for_update(db, hash_secret(payload.device_code))
    if pairing is None:
        raise WhatsAppTranslationError(404, ERROR_PAIRING_NOT_FOUND, "WhatsApp translation request failed")
    if pairing.status == "consumed":
        return _ready_result(db.get(TranslationDevice, pairing.device_id))
    if pairing.status == "pending":
        return _pairing_result(pairing)
    _require_unexpired(pairing)
    raise WhatsAppTranslationError(409, ERROR_PAIRING_STATE, "WhatsApp translation request failed")


def approve_pairing(db: Session, device_code: str, user_id: int) -> None:
    pairing = _get_pairing_for_update(db, hash_secret(device_code))
    if pairing is None:
        raise WhatsAppTranslationError(404, ERROR_PAIRING_NOT_FOUND, "WhatsApp translation request failed")
    if pairing.status not in {"pending", "approved"}:
        raise WhatsAppTranslationError(409, ERROR_PAIRING_STATE, "WhatsApp translation request failed")
    _require_unexpired(pairing)
    if pairing.status == "approved":
        raise WhatsAppTranslationError(409, ERROR_PAIRING_STATE, "WhatsApp translation request failed")
    user = db.get(ArkUser, user_id)
    if user is None or not user.is_active:
        raise WhatsAppTranslationError(403, ERROR_USER_INACTIVE, "WhatsApp translation request failed")
    if WHATSAPP_TRANSLATION_WRITE_PERMISSION not in get_user_permissions(user):
        raise WhatsAppTranslationError(403, ERROR_USER_FORBIDDEN, "WhatsApp translation request failed")
    pairing.status = "approved"
    pairing.user_id = user.id
    pairing.approved_at = beijing_now()
    db.commit()


def reject_pairing(db: Session, device_code: str, user_id: int) -> None:
    pairing = _get_pairing_for_update(db, hash_secret(device_code))
    if pairing is None:
        raise WhatsAppTranslationError(404, ERROR_PAIRING_NOT_FOUND, "WhatsApp translation request failed")
    if pairing.status not in {"pending", "approved"}:
        raise WhatsAppTranslationError(409, ERROR_PAIRING_STATE, "WhatsApp translation request failed")
    if pairing.user_id not in {None, user_id}:
        raise WhatsAppTranslationError(403, ERROR_USER_FORBIDDEN, "WhatsApp translation request failed")
    pairing.status = "rejected"
    pairing.user_id = user_id
    db.commit()


def _require_active_authorized_user(db: Session, user_id: int | None) -> None:
    user = db.get(ArkUser, user_id)
    if user is None or not user.is_active:
        raise WhatsAppTranslationError(403, ERROR_USER_INACTIVE, "WhatsApp translation request failed")
    query = (
        select(ArkUser)
        .options(selectinload(ArkUser.roles).selectinload(ArkRole.permissions))
        .where(ArkUser.id == user_id)
    )
    fresh_user = db.execute(query).scalar_one()
    if WHATSAPP_TRANSLATION_WRITE_PERMISSION not in get_user_permissions(fresh_user):
        raise WhatsAppTranslationError(403, ERROR_USER_FORBIDDEN, "WhatsApp translation request failed")


def _lock_pairing_owner(db: Session, user_id: int | None) -> None:
    if user_id is None:
        return
    db.execute(select(ArkUser).where(ArkUser.id == user_id).with_for_update())


def _require_device_capacity(db: Session, user_id: int) -> None:
    settings = get_settings()
    active_devices = db.query(TranslationDevice).filter(
        TranslationDevice.user_id == user_id,
        TranslationDevice.is_active.is_(True),
        TranslationDevice.expires_at > beijing_now(),
    ).count()
    if active_devices >= settings.WHATSAPP_TRANSLATION_MAX_DEVICES_PER_USER:
        raise WhatsAppTranslationError(429, ERROR_DEVICE_LIMIT, "WhatsApp translation request failed")


def exchange_pairing(db: Session, device_code: str) -> PairingExchangeResult:
    pairing = _get_pairing_for_update(db, hash_secret(device_code))
    if pairing is None:
        raise WhatsAppTranslationError(404, ERROR_PAIRING_NOT_FOUND, "WhatsApp translation request failed")
    if pairing.status == "consumed":
        return _ready_result(db.get(TranslationDevice, pairing.device_id))
    if pairing.status == "pending":
        return _pairing_result(pairing)
    _require_unexpired(pairing)
    _require_active_authorized_user(db, pairing.user_id)
    _lock_pairing_owner(db, pairing.user_id)
    _require_device_capacity(db, pairing.user_id)

    settings = get_settings()
    device = TranslationDevice(
        user_id=pairing.user_id,
        token_hash=pairing.proposed_token_hash,
        device_name=pairing.device_name,
        browser_name=pairing.browser_name,
        browser_version=pairing.browser_version,
        extension_version=pairing.extension_version,
        expires_at=beijing_now() + timedelta(days=settings.WHATSAPP_TRANSLATION_DEVICE_TTL_DAYS),
    )
    db.add(device)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        pairing = _get_pairing_for_update(db, hash_secret(device_code))
        if pairing is not None and pairing.status == "consumed":
            return _ready_result(db.get(TranslationDevice, pairing.device_id))
        raise WhatsAppTranslationError(409, ERROR_PAIRING_CONFLICT, "WhatsApp translation request failed")

    pairing.status = "consumed"
    pairing.device_id = device.id
    pairing.consumed_at = beijing_now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        pairing = _get_pairing_for_update(db, hash_secret(device_code))
        if pairing is not None and pairing.status == "consumed":
            return _ready_result(db.get(TranslationDevice, pairing.device_id))
        raise WhatsAppTranslationError(409, ERROR_PAIRING_CONFLICT, "WhatsApp translation request failed")
    return _ready_result(device)



def prune_unconsumed_pairings(db: Session) -> int:
    cutoff = beijing_now() - timedelta(days=7)
    pairings = db.query(TranslationPairing).filter(
        TranslationPairing.status != "consumed",
        TranslationPairing.created_at < cutoff,
    ).all()
    for pairing in pairings:
        db.delete(pairing)
    db.commit()
    return len(pairings)
