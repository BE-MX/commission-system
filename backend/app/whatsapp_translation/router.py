"""Thin HTTP routes for the WhatsApp translation domain."""

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.security import HTTPBearer

from app.auth.dependencies import get_current_user
from app.auth.models import ArkUser
from app.auth.service import get_live_user_authorization
from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.whatsapp_translation.auth import require_translation_device
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.pairing_service import (
    approve_pairing,
    create_pairing,
    exchange_pairing,
    hash_secret,
    inspect_pairing,
    reject_pairing,
)
from app.whatsapp_translation.quota_service import BoundedSlidingWindowLimiter, client_ip
from app.whatsapp_translation.schemas import PairingCodeRequest, PairingCreate
from app.whatsapp_translation import service, translation_service


router = APIRouter(tags=["WhatsApp 实时翻译"])
_bearer = HTTPBearer(auto_error=False)
pairing_create_limiter = BoundedSlidingWindowLimiter(limit=30)
pairing_exchange_limiter = BoundedSlidingWindowLimiter(limit=30)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def device_identity(
    db=Depends(get_db),
    credentials=Depends(_bearer),
    extension_version: str | None = Header(default=None, alias="X-Ark-Extension-Version"),
):
    return require_translation_device(db, credentials, extension_version)


def _live_translation_actor(db, current_user: dict, permission: str) -> dict:
    user = db.get(ArkUser, int(current_user["sub"]))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise WhatsAppTranslationError(403, "user_inactive", "WhatsApp translation authorization failed")
    roles, permissions = get_live_user_authorization(db, user.id)
    if "super_admin" not in roles and permission not in permissions:
        raise WhatsAppTranslationError(403, "permission_denied", "WhatsApp translation authorization failed")
    return current_user


def translation_permission(permission: str):
    def checker(current_user=Depends(get_current_user), db=Depends(get_db)):
        return _live_translation_actor(db, current_user, permission)

    return checker


@router.get("/health", dependencies=[Depends(no_store)])
def health_route():
    settings = get_settings()
    return ok({
        "status": "ok",
        "min_extension_version": settings.WHATSAPP_TRANSLATION_MIN_EXTENSION_VERSION,
    })


@router.post("/pairings", dependencies=[Depends(no_store)])
def create_pairing_route(payload: PairingCreate, request: Request, db=Depends(get_db)):
    # Machine-to-machine public endpoint: the raw extension token never reaches Ark.
    allowed, retry_after = pairing_create_limiter.allow(client_ip(request))
    if not allowed:
        raise WhatsAppTranslationError(429, "rate_limited", "Pairing rate limit exceeded", retry_after)
    return ok(create_pairing(db, payload).model_dump(mode="json"))


@router.post("/pairings/exchange", dependencies=[Depends(no_store)])
def exchange_pairing_route(payload: PairingCodeRequest, request: Request, db=Depends(get_db)):
    # Public endpoint uses one-time code exchange; no Ark JWT is available yet.
    allowed, retry_after = pairing_exchange_limiter.allow(hash_secret(payload.device_code))
    if not allowed:
        raise WhatsAppTranslationError(429, "rate_limited", "Pairing rate limit exceeded", retry_after)
    return ok(exchange_pairing(db, payload.device_code).model_dump(mode="json"))


@router.post("/pairings/inspect", dependencies=[Depends(no_store)])
def inspect_pairing_route(payload: PairingCodeRequest, current_user=Depends(translation_permission("whatsapp_translation:write")), db=Depends(get_db)):
    return ok(inspect_pairing(db, payload).model_dump(mode="json"))


@router.post("/pairings/approve", dependencies=[Depends(no_store)])
def approve_pairing_route(payload: PairingCodeRequest, current_user=Depends(translation_permission("whatsapp_translation:write")), db=Depends(get_db)):
    approve_pairing(db, payload.device_code, int(current_user["sub"]))
    return ok()


@router.post("/pairings/reject", dependencies=[Depends(no_store)])
def reject_pairing_route(payload: PairingCodeRequest, current_user=Depends(translation_permission("whatsapp_translation:write")), db=Depends(get_db)):
    reject_pairing(db, payload.device_code, int(current_user["sub"]))
    return ok()


@router.get("/devices/me")
def list_my_devices_route(current_user=Depends(translation_permission("whatsapp_translation:write")), db=Depends(get_db)):
    return ok(service.list_my_devices(db, int(current_user["sub"])))


@router.delete("/devices/me/{device_id}")
def revoke_my_device_route(device_id: int, current_user=Depends(translation_permission("whatsapp_translation:write")), db=Depends(get_db)):
    return ok(service.revoke_my_device(db, int(current_user["sub"]), device_id))


@router.get("/usage/me")
def get_my_usage_route(current_user=Depends(translation_permission("whatsapp_translation:write")), db=Depends(get_db)):
    return ok(service.get_my_usage(db, int(current_user["sub"])))


@router.get("/session", dependencies=[Depends(no_store)])
def session_route(identity=Depends(device_identity)):
    return ok(service.get_session(identity))


@router.get("/capabilities", dependencies=[Depends(no_store)])
def capabilities_route(identity=Depends(device_identity)):
    return ok(service.get_capabilities())


@router.post("/translate", dependencies=[Depends(no_store)])
def translate_route(payload: translation_service.TranslateRequest, identity=Depends(device_identity), db=Depends(get_db)):
    return ok(translation_service.translate_text(db, identity, payload).model_dump(mode="json"))


@router.get("/admin/devices")
def list_admin_devices_route(current_user=Depends(translation_permission("whatsapp_translation:admin")), db=Depends(get_db)):
    return ok(service.list_admin_devices(db))


@router.delete("/admin/devices/{device_id}")
def revoke_admin_device_route(device_id: int, current_user=Depends(translation_permission("whatsapp_translation:admin")), db=Depends(get_db)):
    return ok(service.revoke_admin_device(db, int(current_user["sub"]), device_id, "admin_revoked"))


@router.get("/admin/usage")
def get_admin_usage_route(current_user=Depends(translation_permission("whatsapp_translation:admin")), db=Depends(get_db)):
    return ok(service.get_admin_usage(db))


@router.get("/admin/health")
def get_admin_health_route(current_user=Depends(translation_permission("whatsapp_translation:admin")), db=Depends(get_db)):
    return ok(service.get_admin_health(db))
