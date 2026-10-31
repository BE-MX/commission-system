"""Local facts preserve commercial intent and confirmation-time FX."""
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from app.core.config import get_settings
from app.finance.models import Currency

COMMERCIAL_FIELDS = ("commercial_source", "is_new_deal", "is_first_return", "is_private_order")


def local_mode():
    return get_settings().TRANSACTION_MODE == "local"


def consumer_phase(db):
    """Read the installed phase in the caller session; never infer from env."""
    from app.commerce_transition.service import policy
    return policy(db).phase


def formal_projection_enabled(db):
    """Both formal routes share the customer read model during transition."""
    return consumer_phase(db) in {"transition", "local_only"}


def apply_commercial(invoice, body, customer):
    values = {name: getattr(body, name) for name in COMMERCIAL_FIELDS}
    values["department_allocations"] = [item.model_dump(mode="json") for item in body.department_allocations]
    if invoice.commerce_status != "draft" and invoice.local_commercial is not None:
        if any(invoice.local_commercial.get(name, [] if name == "department_allocations" else None) != values[name] for name in values):
            raise ValueError("已确认订单的经营来源与业务标记不可覆盖")
        return
    invoice.local_commercial = {**values, "country": customer.primary_country_code, "customer_name": customer.display_name}


def freeze_order_fx(db, invoice):
    if invoice.local_rate_to_usd is not None:
        return
    if invoice.currency == "USD":
        invoice.local_rate_to_usd = Decimal(1)
        return
    rows = db.scalars(select(Currency).where(Currency.code.in_([invoice.currency, "USD"]))
        .order_by(Currency.code).with_for_update().execution_options(populate_existing=True)).all()
    currencies = {row.code: row for row in rows}
    source, usd = currencies.get(invoice.currency), currencies.get("USD")
    if source is None or usd is None or not source.active or not usd.active or source.rate_to_cny <= 0 or usd.rate_to_cny <= 0:
        raise ValueError("确认订单前须配置原币及美元汇率")
    rate = (source.rate_to_cny / usd.rate_to_cny).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    if not 0 < rate < Decimal("10000000000"):
        raise ValueError("订单汇率超出可存储精度")
    invoice.local_rate_to_usd = rate
