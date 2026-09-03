"""Thin HTTP routes for the WhatsApp translation domain."""

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.security import HTTPBearer

from app.auth.dependencies import require_permission
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


@router.post("/pairings/inspect", dependencies=[Depends(require_permission("whatsapp_translation:write")), Depends(no_store)])
def inspect_pairing_route(payload: PairingCodeRequest, db=Depends(get_db)):
    return ok(inspect_pairing(db, payload).model_dump(mode="json"))


@router.post("/pairings/approve", dependencies=[Depends(require_permission("whatsapp_translation:write")), Depends(no_store)])
def approve_pairing_route(payload: PairingCodeRequest, current_user=Depends(require_permission("whatsapp_translation:write")), db=Depends(get_db)):
    approve_pairing(db, payload.device_code, int(current_user["sub"]))
    return ok()


@router.post("/pairings/reject", dependencies=[Depends(require_permission("whatsapp_translation:write")), Depends(no_store)])
def reject_pairing_route(payload: PairingCodeRequest, current_user=Depends(require_permission("whatsapp_translation:write")), db=Depends(get_db)):
    reject_pairing(db, payload.device_code, int(current_user["sub"]))
    return ok()


@router.get("/devices/me", dependencies=[Depends(require_permission("whatsapp_translation:write"))])
def list_my_devices_route(current_user=Depends(require_permission("whatsapp_translation:write")), db=Depends(get_db)):
    return ok(service.list_my_devices(db, int(current_user["sub"])))


@router.delete("/devices/me/{device_id}", dependencies=[Depends(require_permission("whatsapp_translation:write"))])
def revoke_my_device_route(device_id: int, current_user=Depends(require_permission("whatsapp_translation:write")), db=Depends(get_db)):
    return ok(service.revoke_my_device(db, int(current_user["sub"]), device_id))


@router.get("/usage/me", dependencies=[Depends(require_permission("whatsapp_translation:write"))])
def get_my_usage_route(current_user=Depends(require_permission("whatsapp_translation:write")), db=Depends(get_db)):
    return ok(service.get_my_usage(db, int(current_user["sub"])))


@router.get("/session", dependencies=[Depends(no_store)])
def session_route(identity=Depends(device_identity)):
    return ok(service.get_session(identity))


@router.get("/capabilities")
def capabilities_route(identity=Depends(device_identity)):
    return ok(service.get_capabilities())


@router.post("/translate", dependencies=[Depends(no_store)])
def translate_route(payload: translation_service.TranslateRequest, identity=Depends(device_identity), db=Depends(get_db)):
    return ok(translation_service.translate_text(db, identity, payload).model_dump(mode="json"))


@router.get("/admin/devices", dependencies=[Depends(require_permission("whatsapp_translation:admin"))])
def list_admin_devices_route(db=Depends(get_db)):
    return ok(service.list_admin_devices(db))


@router.delete("/admin/devices/{device_id}", dependencies=[Depends(require_permission("whatsapp_translation:admin"))])
def revoke_admin_device_route(device_id: int, current_user=Depends(require_permission("whatsapp_translation:admin")), db=Depends(get_db)):
    return ok(service.revoke_admin_device(db, int(current_user["sub"]), device_id, "admin_revoked"))


@router.get("/admin/usage", dependencies=[Depends(require_permission("whatsapp_translation:admin"))])
def get_admin_usage_route(db=Depends(get_db)):
    return ok(service.get_admin_usage(db))


@router.get("/admin/health", dependencies=[Depends(require_permission("whatsapp_translation:admin"))])
def get_admin_health_route(db=Depends(get_db)):
    return ok(service.get_admin_health(db))

