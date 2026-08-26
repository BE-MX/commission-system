"""Short-lived proof that screenshot provenance was resolved by the server."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.time import utc_now

PURPOSE = "invoice_screenshot_preview"
TOKEN_TTL_MINUTES = 30


def issue_preview_token(*, actor_user_id: int, invoice_patch: dict, expected_total) -> str:
    settings = get_settings()
    now = utc_now()
    claims = {
        "purpose": PURPOSE,
        "actor_user_id": int(actor_user_id),
        "source_image_sha256": invoice_patch.get("source_image_sha256"),
        "source_order_id": invoice_patch.get("source_order_id"),
        "customer_id": str(invoice_patch.get("customer_id") or ""),
        "sales_user_id": int(invoice_patch.get("sales_user_id") or 0),
        "invoice_date": invoice_patch.get("invoice_date"),
        "currency": invoice_patch.get("currency"),
        "order_type": invoice_patch.get("order_type"),
        "expected_total": str(_money(expected_total)),
        "recognized_fields_sha256": _recognized_fields_sha256(invoice_patch),
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_preview_token(token: str, *, actor_user_id: int, invoice, request_payload=None) -> None:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise ValueError("截图预览凭证无效或已过期，请重新识别") from exc
    expected = {
        "purpose": PURPOSE,
        "actor_user_id": int(actor_user_id),
        "source_image_sha256": invoice.source_image_sha256,
        "source_order_id": invoice.source_order_id,
        "customer_id": str(invoice.customer_id or ""),
        "sales_user_id": int(invoice.sales_user_id or 0),
        "invoice_date": invoice.invoice_date.isoformat(),
        "currency": invoice.currency,
        "order_type": invoice.order_type,
        "expected_total": str(_money(invoice.total_amount or 0)),
        "recognized_fields_sha256": _recognized_fields_sha256(request_payload or invoice),
    }
    if any(claims.get(key) != value for key, value in expected.items()):
        raise ValueError("截图预览内容已被修改，请重新识别并确认")


def _money(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _recognized_fields_sha256(payload) -> str:
    items = _value(payload, "items") or []
    canonical = {
        "customer_name": str(_value(payload, "customer_name") or ""),
        "source_order_name": str(_value(payload, "source_order_name") or ""),
        "shipping_fee": str(_money(_value(payload, "shipping_fee") or 0)),
        "internal_accessory": str(_money(_value(payload, "internal_accessory") or 0)),
        "surcharge_amount": str(_money(_value(payload, "surcharge_amount") or 0)),
        "items": [_canonical_item(item) for item in items],
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_item(item) -> dict:
    item_type = str(_value(item, "item_type") or "stock")
    return {
        "product_kind": str(_value(item, "product_kind") or "hair"),
        "item_type": item_type,
        "product_id": _identifier(_value(item, "product_id")),
        "sku_id": _identifier(_value(item, "sku_id")),
        "product_name": str(_value(item, "product_name") or ""),
        "product_display": str(_value(item, "product_display") or ""),
        "net_weight_grams": str(_value(item, "net_weight_grams") or ""),
        "model": str(_value(item, "model") or ""),
        "color": str(_value(item, "color") or ""),
        "length": str(_value(item, "length") or ""),
        "quantity": int(_value(item, "quantity") or 0),
        "price_per_piece": str(
            Decimal(_value(item, "price_per_piece") or 0).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP,
            )
        ),
        "discount_amount": str(_money(_value(item, "discount_amount") or 0)),
    }


def _value(payload, key: str):
    return payload.get(key) if isinstance(payload, dict) else getattr(payload, key, None)


def _identifier(value):
    return str(value) if value is not None else None
