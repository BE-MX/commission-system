"""Portal prices use standard metadata and Ark's existing customer rule engine."""
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import get_settings
from app.invoice import accessory_price_service, price_service
from app.portal.domain import content_hash, decimal_value
from app.portal.errors import PortalError, reject


@dataclass(frozen=True)
class ResolvedPrice:
    amount: Decimal
    currency: str
    fingerprint: str


def resolve(db, access, item, currency):
    namespace = get_settings().PORTAL_OKKI_NAMESPACE
    if not namespace or item.source_namespace != namespace or access.okki_namespace != namespace or currency != "USD":
        reject("PRICE_UNAVAILABLE", "Pricing needs to be reviewed.", 503)
    rule = price_service.get_customer_rule_row(db, access.okki_company_id)
    if rule is not None and rule.adjust_type not in {"fixed", "percent"}:
        reject("PRICE_UNAVAILABLE", "The customer price rule needs review.", 503)
    rule_snapshot = {"id": str(rule.id), "adjust_type": rule.adjust_type,
        "adjust_value": format(rule.adjust_value, "f"),
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None} if rule is not None else None
    standard = item.standard_json
    if item.product_kind == "hair":
        fields = ("product_display", "length", "price_unit", "color")
        if not isinstance(standard, dict) or any(not isinstance(standard.get(key), str) or not standard[key] for key in fields):
            reject("PRICE_UNAVAILABLE", "The product price is not configured.", 503)
        result = price_service.resolve_price(db, customer_id=access.okki_company_id,
            product_display=standard["product_display"], length=standard["length"],
            unit=standard["price_unit"], color=standard["color"])
    elif item.product_kind == "accessory":
        try:
            result = accessory_price_service.resolve_configured_price(db,
                customer_id=access.okki_company_id, product_id=int(item.product_id),
                sku_id=int(item.sku_id), currency=currency)
        except (ValueError, TypeError):
            reject("PRICE_UNAVAILABLE", "The product price cannot be confirmed.", 503)
    else:
        reject("PRICE_UNAVAILABLE", "The product price cannot be confirmed.", 503)
    if result.get("currency") != currency or result.get("standard_price") is None:
        reject("PRICE_UNAVAILABLE", "The product price is not configured.", 503)
    try:
        standard_price = decimal_value(result["standard_price"], places=4, positive=True)
        amount = decimal_value(result.get("customer_price"), places=4, positive=True)
        if amount > Decimal("99999999.9999"):
            raise ValueError("Price overflow")
    except (PortalError, ValueError):
        reject("PRICE_UNAVAILABLE", "The product price cannot be confirmed.", 503)
    fingerprint = content_hash({"item_id": item.public_id, "standard_fingerprint": item.standard_fingerprint,
        "product_id": item.product_id, "sku_id": item.sku_id, "standard": standard,
        "customer_id": access.okki_company_id, "namespace": access.okki_namespace,
        "currency": currency, "standard_price": standard_price, "customer_price": amount,
        "rule": rule_snapshot, "color_type": result.get("color_type")})
    return ResolvedPrice(amount, currency, fingerprint)
