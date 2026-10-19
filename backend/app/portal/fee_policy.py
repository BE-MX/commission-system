"""Weight-tiered shipping and payment-method surcharge for customer-confirmed requests.

Pure calculation over a validated SitePolicy. A result is either "confirmed"
(complete amounts the customer sees before submitting) or "manual" (the sales
representative must quote fees in a proposal). Disabled policy returns None so
the original pending-fees flow is unchanged.
"""
from decimal import Decimal, ROUND_HALF_UP

from app.portal.domain import CENT

MANUAL_REASONS = ("unknown_weight", "over_limit")


def unit_weight(item, family=None):
    """Grams per sale unit: family rule first, else a gram-based inventory conversion."""
    if family is not None:
        return Decimal(family.unit_weight_grams).normalize()
    if item.inventory_unit == "g":
        return Decimal(item.conversion_factor).normalize()
    return None


def surcharge_name(term):
    label = term.method_label or term.code
    return f"Payment surcharge ({label} {Decimal(term.surcharge_percent).normalize():f}%)"


def shipping_fee(policy, grams):
    for tier in policy.auto_fees.shipping_tiers:
        if grams <= tier.max_grams:
            return Decimal(tier.fee)
    return None


def estimate(policy, term, product_amount, line_weights):
    """line_weights: per-line total grams, or None when any line weight is unknown."""
    if not policy.auto_fees.enabled:
        return None
    base = {"payment_term_code": term.code, "surcharge_percent": term.surcharge_percent,
            "manual_above_grams": policy.auto_fees.shipping_tiers[-1].max_grams}
    if any(value is None for value in line_weights):
        return {**base, "status": "manual", "reason": "unknown_weight", "weight_grams": None}
    grams = sum(line_weights, Decimal("0"))
    weight = format(grams.normalize(), "f")
    shipping = shipping_fee(policy, grams)
    if shipping is None:
        return {**base, "status": "manual", "reason": "over_limit", "weight_grams": weight}
    products = Decimal(product_amount)
    percent = Decimal(term.surcharge_percent)
    surcharge = ((products + shipping) * percent / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    return {**base, "status": "confirmed", "reason": None, "weight_grams": weight,
            "shipping_amount": format(shipping, ".2f"), "packaging_amount": "0.00",
            "surcharge_amount": format(surcharge, ".2f"),
            "surcharge_name": surcharge_name(term) if surcharge else "",
            "total_amount": format(products + shipping + surcharge, ".2f")}
