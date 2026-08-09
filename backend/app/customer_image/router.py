"""Thin RBAC API for customer image products and invitations."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok, page_result
from app.customer_image import file_service, service
from app.customer_image.schemas import (
    CustomerImageInviteCreate,
    CustomerImageProductAssetCopy,
    CustomerImageReferenceOrder,
    CustomerImageProductUpsert,
)
from app.design_image import library_service
from app.design_image import service as design_image_service


router = APIRouter()


def _user_id(payload: dict) -> int:
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token format invalid") from None
    if user_id <= 0:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token format invalid")
    return user_id


def _is_admin(payload: dict) -> bool:
    return "super_admin" in payload.get("roles", []) or "customer_image:admin" in payload.get(
        "permissions", []
    )


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except service.CustomerImageNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CustomerScopeConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.CustomerImageConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except design_image_service.DesignImageNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except design_image_service.DesignImageConsistencyError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except file_service.shared_files.ImageValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except file_service.shared_files.ImageStorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "image storage unavailable") from exc
    except ValueError as exc:
        code = status.HTTP_404_NOT_FOUND if "not found" in str(exc) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, str(exc)) from exc


def _iso(value):
    return value.isoformat() if value is not None else None


def _option(row, *, include_prompts: bool) -> dict:
    return {
        "id": row.id,
        "key": row.key,
        "label": row.label,
        "control_type": row.control_type,
        "required": row.required,
        "default_value": row.default_value,
        "sort": row.sort,
        "values": [
            {
                "id": value.id,
                "value": value.value,
                "label": value.label,
                "color_hex": value.color_hex,
                "pantone_code": value.pantone_code,
                "sort": value.sort,
                "is_active": value.is_active,
            } | ({"prompt_fragment": value.prompt_fragment} if include_prompts else {})
            for value in row.values
        ],
    }


def _cover_descriptor(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "width": row.width,
        "height": row.height,
        "content_url": f"/api/customer-image/products/{row.product_id}/cover",
    }


def _product(row, *, include_prompts: bool = True, cover=None) -> dict:
    result = {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "description": row.description,
        "config_version": row.config_version,
        "is_published": row.is_published,
        "sort": row.sort,
        "cover": _cover_descriptor(cover),
        "options": [_option(option, include_prompts=include_prompts) for option in row.options],
    }
    if include_prompts:
        result.update(fixed_prompt=row.fixed_prompt, output_prompt=row.output_prompt)
    return result


def _product_with_cover(db: Session, row, *, include_prompts: bool = True) -> dict:
    cover = service.list_current_product_covers(db, [row.id]).get(row.id)
    return _product(row, include_prompts=include_prompts, cover=cover)


def _product_asset(row) -> dict:
    content_url = f"/api/customer-image/products/{row.product_id}/assets/{row.id}/content"
    return {
        "id": row.id,
        "product_id": row.product_id,
        "role": row.role,
        "position": row.position,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "width": row.width,
        "height": row.height,
        "content_url": content_url,
    }


def _library_asset(row) -> dict:
    content_url = f"/api/customer-image/library-assets/{row.id}/content"
    return {
        "id": row.id,
        "scope": row.scope,
        "title": row.title,
        "mime_type": row.mime_type,
        "file_size": row.file_size,
        "width": row.width,
        "height": row.height,
        "created_at": _iso(row.created_at),
        "content_url": content_url,
        "thumbnail_url": f"{content_url}?thumbnail=true",
    }


async def _read_bounded(upload: UploadFile) -> bytes:
    byte_limit = file_service.shared_files.effective_max_upload_bytes()
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = await upload.read(min(1024 * 1024, byte_limit - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > byte_limit:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "image too large")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        await upload.close()


def _invite(row, *, include_suffix: bool = True) -> dict:
    result = {
        "id": row.id,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name_snapshot,
        "created_by": row.created_by,
        "starts_at": _iso(row.starts_at),
        "expires_at": _iso(row.expires_at),
        "quota_total": row.quota_total,
        "quota_used": row.quota_used,
        "revoked_at": _iso(row.revoked_at),
        "created_at": _iso(row.created_at),
    }
    if include_suffix:
        result["token_suffix"] = row.token_suffix
    return result


def _generation(row) -> dict:
    return {
        "id": row.id,
        "invite_id": row.invite_id,
        "product_id": row.product_id,
        "product_name": row.product_name_snapshot,
        "status": row.status,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "billing_certainty": row.billing_certainty,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "estimated_cost_microusd": row.estimated_cost_microusd,
        "created_at": _iso(row.created_at),
        "finished_at": _iso(row.finished_at),
    }


@router.get("/customers")
def list_customers(
    search: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:write")),
):
    if not search.strip():
        return ok([])
    rows = _call(service.list_available_customers, db, _user_id(payload), _is_admin(payload), search)
    return ok(rows)


@router.get("/products")
def list_products(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission(
        "customer_image:read", "customer_image:write", "customer_image:admin"
    )),
):
    is_admin = _is_admin(payload)
    rows = service.list_products(db, include_inactive=is_admin)
    covers = service.list_current_product_covers(db, [row.id for row in rows])
    return ok([
        _product(row, include_prompts=is_admin, cover=covers.get(row.id))
        for row in rows
    ])


@router.get("/products/{product_id}/cover")
def get_product_cover_content(
    product_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission(
        "customer_image:read", "customer_image:write", "customer_image:admin"
    )),
):
    cover = _call(
        service.get_current_product_cover,
        db,
        product_id,
        include_inactive=_is_admin(payload),
    )
    stream = _call(file_service.open_product_asset_content, db, product_id, cover.id)
    return StreamingResponse(
        stream,
        media_type=cover.mime_type,
        headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(stream.close),
    )


@router.post("/products")
def create_product(
    body: CustomerImageProductUpsert,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:admin")),
):
    row = _call(service.create_product, db, admin_id=_user_id(payload), payload=body)
    row = service.get_product(db, row.id, include_inactive=True)
    return ok(_product_with_cover(db, row))


@router.put("/products/{product_id}")
def update_product(
    product_id: int,
    body: CustomerImageProductUpsert,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    _call(service.update_product, db, product_id, body)
    return ok(_product_with_cover(
        db, service.get_product(db, product_id, include_inactive=True)
    ))


@router.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    _call(service.delete_product, db, product_id)
    return ok()


@router.post("/products/{product_id}/publish")
def publish_product(
    product_id: int,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    _call(service.publish_product, db, product_id)
    return ok(_product_with_cover(
        db, service.get_product(db, product_id, include_inactive=True)
    ))


@router.post("/products/{product_id}/unpublish")
def unpublish_product(
    product_id: int,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    _call(service.unpublish_product, db, product_id)
    return ok(_product_with_cover(
        db, service.get_product(db, product_id, include_inactive=True)
    ))


@router.get("/products/{product_id}/assets")
def list_product_assets(
    product_id: int,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    rows = _call(service.list_current_product_assets, db, product_id)
    return ok([_product_asset(row) for row in rows])


@router.post("/products/{product_id}/assets/upload")
async def upload_product_asset(
    product_id: int,
    role: str = Form(...),
    position: int = Form(..., ge=0),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    if role not in {"cover", "reference"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid asset role")
    if role == "cover" and position != 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "cover position must be zero")
    product = _call(service.get_product, db, product_id, include_inactive=True)
    content = await _read_bounded(file)
    row = _call(
        file_service.replace_product_asset_from_upload,
        db,
        product,
        role,
        position,
        content,
        file.content_type or "application/octet-stream",
    )
    return ok(_product_asset(row))


@router.post("/products/{product_id}/assets/library")
def copy_product_asset_from_library(
    product_id: int,
    body: CustomerImageProductAssetCopy,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:admin")),
):
    if body.role == "cover" and body.position != 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "cover position must be zero")
    product = _call(service.get_product, db, product_id, include_inactive=True)
    row = _call(
        file_service.replace_product_asset_from_library,
        db,
        product,
        body.role,
        body.position,
        body.source_asset_id,
        admin_id=_user_id(payload),
    )
    return ok(_product_asset(row))


@router.delete("/products/{product_id}/references/{asset_id}")
def retire_product_reference(
    product_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    _call(service.retire_product_reference, db, product_id, asset_id)
    return ok()


@router.put("/products/{product_id}/references/order")
def reorder_product_references(
    product_id: int,
    body: CustomerImageReferenceOrder,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    rows = _call(service.reorder_product_references, db, product_id, body.asset_ids)
    return ok([_product_asset(row) for row in rows])


@router.get("/products/{product_id}/assets/{asset_id}/content")
def get_product_asset_content(
    product_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    asset = _call(service.get_current_product_asset, db, product_id, asset_id)
    stream = _call(file_service.open_product_asset_content, db, product_id, asset_id)
    return StreamingResponse(
        stream,
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(stream.close),
    )


@router.get("/library-assets")
def list_library_assets(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:admin")),
):
    owner_id = _user_id(payload)
    rows = [
        *_call(library_service.list_library_assets, db, owner_id, "public"),
        *_call(library_service.list_library_assets, db, owner_id, "private"),
    ]
    rows.sort(key=lambda row: (row.created_at, row.id), reverse=True)
    return ok({"items": [_library_asset(row) for row in rows]})


@router.get("/library-assets/{asset_id}/content")
def get_library_asset_content(
    asset_id: int,
    thumbnail: bool = Query(False),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:admin")),
):
    content = _call(
        library_service.open_library_asset_content,
        db,
        _user_id(payload),
        asset_id,
        thumbnail=thumbnail,
    )
    return StreamingResponse(
        content.stream,
        media_type=content.mime_type,
        headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(content.stream.close),
    )


@router.get("/invites")
def list_invites(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission(
        "customer_image:read", "customer_image:write", "customer_image:admin"
    )),
):
    rows, total = service.list_invites(
        db, _user_id(payload), _is_admin(payload), page, page_size
    )
    return ok(page_result([_invite(row) for row in rows], total, page, page_size))


@router.post("/invites")
def create_invite(
    body: CustomerImageInviteCreate,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:write")),
):
    invite, plaintext = _call(
        service.create_invite,
        db,
        creator_id=_user_id(payload),
        is_admin=_is_admin(payload),
        payload=body,
    )
    base_url = get_settings().SHORT_LINK_BASE_URL.rstrip("/")
    return ok({
        "invite": _invite(invite, include_suffix=False),
        "invite_url": f"{base_url}/create/{plaintext}",
    })


@router.post("/invites/{invite_id}/revoke")
def revoke_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:write")),
):
    row = _call(service.revoke_invite, db, invite_id, _user_id(payload), _is_admin(payload))
    return ok(_invite(row))


@router.get("/generations")
def list_generations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    payload: dict = Depends(require_any_permission("customer_image:read", "customer_image:admin")),
):
    rows, total = service.list_generations(
        db, _user_id(payload), _is_admin(payload), page, page_size
    )
    return ok(page_result([_generation(row) for row in rows], total, page, page_size))
