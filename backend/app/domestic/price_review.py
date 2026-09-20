"""Compare order prices against the default quote, excluding labor fees."""
from decimal import Decimal

from app.domestic.pricing_service import resolve_discount


def default_price(item):
    if item.default_discount_price is not None:
        return Decimal(item.default_discount_price)
    actual = Decimal(item.unit_price or 0) - Decimal(item.labor_fee or 0)
    # Historical system quotes already are the default. Only manual historical
    # quotes need reconstruction from their original price and membership snapshot.
    if item.pricing_rule != "manual_override" or item.base_price_version_snapshot == 0:
        return actual
    attrs = item.attrs_snapshot or {}
    return resolve_discount(
        product_type=attrs.get("product_type"), craft=attrs.get("craft"),
        length=attrs.get("length"), size=attrs.get("size"),
        original_price=item.original_price, membership_level=item.membership_level_snapshot,
    ).final_price


def item_price_changed(item):
    return Decimal(item.unit_price or 0) - Decimal(item.labor_fee or 0) != default_price(item)


def item_price_view(item):
    default = default_price(item)
    return {
        "default_discount_price": float(default),
        "default_line_amount": float((default + Decimal(item.labor_fee or 0)) * item.order_qty),
        "price_changed": item_price_changed(item),
    }
