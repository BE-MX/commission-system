"""Invitation-authenticated customer image portal API."""

from __future__ import annotations

import threading
import time
import logging
from collections import OrderedDict, deque
from datetime import UTC, datetime
from typing import BinaryIO

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException
from python_multipart.exceptions import FormParserError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.response import ok
from app.customer_image import file_service, service
from app.customer_image.models import CustomerImageInvite
from app.customer_image.schemas import (
    CustomerImagePublicAsset,
    CustomerImagePublicContext,
    CustomerImagePublicOption,
    CustomerImagePublicOptionValue,
    CustomerImagePublicProduct,
)
from app.customer_image.token_service import InviteUnavailableError, resolve_active_invite
from app.pm.auth import client_ip


router = APIRouter()
logger = logging.getLogger("commission")
AUTH_ERROR = "This invitation is unavailable. Please request a new link from your sales contact."
RATE_ERROR = "Too many logo uploads. Please wait one minute and try again."
PUBLIC_PREFIX = "/api/customer-image/public"
SECURITY_HEADERS = {
    "Cache-Control": "private, no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _is_public_path(path: str) -> bool:
    return path == PUBLIC_PREFIX or path.startswith(f"{PUBLIC_PREFIX}/")


class PublicSecurityHeadersMiddleware:
    """Apply security headers to every public portal response, including framework errors."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not _is_public_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_with_headers(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                security_names = {name.lower().encode("latin-1") for name in SECURITY_HEADERS}
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in security_names
                ]
                for name, value in SECURITY_HEADERS.items():
                    encoded_name = name.lower().encode("latin-1")
                    headers.append((encoded_name, value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as exc:
            if response_started:
                raise
            message = f"[customer-image] unhandled public API error: {exc}"
            logger.warning(message)
            print(message, flush=True)
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
                headers=SECURITY_HEADERS,
            )
            await response(scope, receive, send)


class UploadTooLargeError(Exception):
    """Raised before decoding when a logo exceeds the configured byte ceiling."""


def read_upload_content(stream: BinaryIO, byte_limit: int) -> bytes:
    content = stream.read(byte_limit + 1)
    if len(content) > byte_limit:
        raise UploadTooLargeError
    return content


def _upload_too_large_message(byte_limit: int) -> str:
    if byte_limit % (1024 * 1024) == 0:
        return f"Logo image cannot exceed {byte_limit // (1024 * 1024)} MiB."
    return f"Logo image cannot exceed {byte_limit} bytes."


class BoundedSlidingWindowLimiter:
    """Per-process bounded limiter; multiple workers require a shared store."""

    def __init__(self, limit: int = 10, window_seconds: int = 60, max_keys: int = 10_000):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                self._hits.move_to_end(key)
                return False
            hits.append(now)
            self._hits.move_to_end(key)
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


logo_rate_limiter = BoundedSlidingWindowLimiter()


def require_invite(
    request: Request, response: Response, db: Session = Depends(get_db)
) -> CustomerImageInvite:
    response.headers.update(SECURITY_HEADERS)
    parts = request.headers.get("Authorization", "").split(" ")
    if len(parts) != 2 or parts[0] != "Invite" or not parts[1]:
        raise HTTPException(status_code=401, detail=AUTH_ERROR, headers=SECURITY_HEADERS)
    try:
        return resolve_active_invite(db, parts[1], datetime.now(UTC))
    except InviteUnavailableError:
        raise HTTPException(status_code=401, detail=AUTH_ERROR, headers=SECURITY_HEADERS) from None


def _asset_data(asset, *, product=False) -> dict:
    return CustomerImagePublicAsset(
        id=asset.id,
        role=asset.role if product else None,
        position=asset.position if product else None,
        mime_type=asset.mime_type,
        file_size=asset.file_size,
        width=asset.width,
        height=asset.height,
    ).model_dump(exclude_none=True)


def _product_data(product) -> dict:
    return CustomerImagePublicProduct(
        id=product.id,
        name=product.name,
        category=product.category,
        description=product.description,
        assets=[
            _asset_data(asset, product=True)
            for asset in sorted(product.assets, key=lambda row: (row.role, row.position, row.id))
        ],
        options=[CustomerImagePublicOption(
            key=option.key,
            label=option.label,
            control_type=option.control_type,
            required=option.required,
            default_value=option.default_value,
            values=[CustomerImagePublicOptionValue(
                value=value.value,
                label=value.label,
                color_hex=value.color_hex,
                pantone_code=value.pantone_code,
            ) for value in option.values],
        ) for option in product.options],
    ).model_dump()


@router.get("/context")
def context(db: Session = Depends(get_db), invite: CustomerImageInvite = Depends(require_invite)):
    products = service.list_public_products(db, invite.id)
    current_logo = (
        service.get_public_invite_asset(db, invite.id, invite.current_logo_asset_id)
        if invite.current_logo_asset_id else None
    )
    data = CustomerImagePublicContext(
        brand_name="莱莎产品效果图",
        customer_display_name=invite.customer_name_snapshot,
        expires_at=invite.expires_at,
        quota={"total": invite.quota_total, "used": invite.quota_used, "remaining": invite.quota_total - invite.quota_used},
        current_logo=CustomerImagePublicAsset(**_asset_data(current_logo)) if current_logo else None,
        visible_product_count=len(products),
    ).model_dump(mode="json")
    return ok(data)


@router.get("/products")
def products(db: Session = Depends(get_db), invite: CustomerImageInvite = Depends(require_invite)):
    return ok([_product_data(product) for product in service.list_public_products(db, invite.id)])


@router.post("/logo")
async def upload_logo(
    request: Request,
    db: Session = Depends(get_db),
    invite: CustomerImageInvite = Depends(require_invite),
):
    if not logo_rate_limiter.allow(f"{invite.id}:{client_ip(request)}"):
        raise HTTPException(status_code=429, detail=RATE_ERROR, headers=SECURITY_HEADERS)
    byte_limit = file_service.effective_max_upload_bytes()
    try:
        async with request.form(max_files=1, max_fields=1, max_part_size=byte_limit + 1) as form:
            values = form.getlist("file")
            if list(form.keys()) != ["file"] or len(values) != 1 or not isinstance(values[0], UploadFile):
                raise HTTPException(status_code=400, detail="Exactly one logo file is required")
            file = values[0]
            content = read_upload_content(file.file, byte_limit)
            normalized = file_service.normalize_upload(content, file.content_type or "")
            asset = file_service.replace_current_logo(db, invite.id, normalized)
    except UploadTooLargeError:
        raise HTTPException(status_code=413, detail=_upload_too_large_message(byte_limit)) from None
    except (MultiPartException, FormParserError) as exc:
        raise HTTPException(status_code=400, detail="Invalid logo upload") from exc
    except file_service.shared_files.ImageValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc), headers=SECURITY_HEADERS) from exc
    except (file_service.shared_files.ImageStorageError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Image storage unavailable", headers=SECURITY_HEADERS) from exc
    return ok(_asset_data(asset))


def _content(asset, content):
    return StreamingResponse(
        content,
        media_type=asset.mime_type,
        headers=SECURITY_HEADERS,
        background=BackgroundTask(content.close),
    )


@router.get("/products/{product_id}/assets/{asset_id}/content")
def product_asset_content(
    product_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    invite: CustomerImageInvite = Depends(require_invite),
):
    try:
        asset = service.get_public_product_asset(db, invite.id, product_id, asset_id)
        content = file_service.open_product_asset_content(db, product_id, asset_id)
    except (service.CustomerImageNotFoundError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Asset not found", headers=SECURITY_HEADERS) from None
    return _content(asset, content)


@router.get("/assets/{asset_id}/content")
def invite_asset_content(
    asset_id: int,
    db: Session = Depends(get_db),
    invite: CustomerImageInvite = Depends(require_invite),
):
    try:
        asset = service.get_public_invite_asset(db, invite.id, asset_id)
        content = file_service.open_invite_asset_content(db, invite.id, asset_id)
    except (service.CustomerImageNotFoundError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Asset not found", headers=SECURITY_HEADERS) from None
    return _content(asset, content)
