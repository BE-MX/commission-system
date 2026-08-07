"""Thin RBAC API for customer image products and invitations."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import ok
from app.customer_image import service
from app.customer_image.schemas import CustomerImageInviteCreate, CustomerImageProductUpsert


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
    except ValueError as exc:
        code = status.HTTP_404_NOT_FOUND if "not found" in str(exc) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, str(exc)) from exc


def _iso(value):
    return value.isoformat() if value is not None else None


def _option(row) -> dict:
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
                "prompt_fragment": value.prompt_fragment,
                "color_hex": value.color_hex,
                "pantone_code": value.pantone_code,
                "sort": value.sort,
                "is_active": value.is_active,
            }
            for value in row.values
        ],
    }


def _product(db: Session, row, *, include_prompts: bool = True) -> dict:
    options = service.list_product_options(db, row.id)
    result = {
        "id": row.id,
        "name": row.name,
        "category": row.category,
        "description": row.description,
        "config_version": row.config_version,
        "is_published": row.is_published,
        "sort": row.sort,
        "options": [_option(option) for option in options],
    }
    if include_prompts:
        result.update(fixed_prompt=row.fixed_prompt, output_prompt=row.output_prompt)
    return result


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
    rows = _call(service.list_available_customers, db, _user_id(payload), _is_admin(payload), search)
    return ok(rows)


@router.get("/products")
def list_products(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:read")),
):
    is_admin = _is_admin(payload)
    return ok([_product(db, row, include_prompts=is_admin) for row in service.list_products(db)])


@router.post("/products")
def create_product(
    body: CustomerImageProductUpsert,
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:admin")),
):
    row = _call(service.create_product, db, admin_id=_user_id(payload), payload=body)
    return ok(_product(db, row))


@router.put("/products/{product_id}")
def update_product(
    product_id: int,
    body: CustomerImageProductUpsert,
    db: Session = Depends(get_db),
    _payload: dict = Depends(require_permission("customer_image:admin")),
):
    return ok(_product(db, _call(service.update_product, db, product_id, body)))


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
    return ok(_product(db, _call(service.publish_product, db, product_id)))


@router.get("/invites")
def list_invites(
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:read")),
):
    rows = service.list_invites(db, _user_id(payload), _is_admin(payload))
    return ok([_invite(row) for row in rows])


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
    db: Session = Depends(get_db),
    payload: dict = Depends(require_permission("customer_image:read")),
):
    rows = service.list_generations(db, _user_id(payload), _is_admin(payload))
    return ok([_generation(row) for row in rows])
