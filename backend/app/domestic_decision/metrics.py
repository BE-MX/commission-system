"""Metric definitions and arithmetic share explicit grains and safe zero bases."""

from decimal import Decimal
from datetime import timedelta
from app.domestic_decision.models import DecisionConfig

METRIC_VERSION = "domestic-v1"
DEFAULT_CONFIG = {"coverage_start": None, "aftersales_order_types": [], "quality_threshold": 0.8, "dormant_days": 90, "rule_version": "rules-v1", "inactive_lifecycle_statuses": ["closed", "paused", "inactive", "lost", "停业", "暂停合作"]}
METRICS = [
    {"code": "amount", "label": "订单额", "grain": "order_id", "formula": "SUM(unique order.total_amount)", "unit": "元", "version": METRIC_VERSION},
    {"code": "matched_amount", "label": "匹配产品金额", "grain": "order_item_id", "formula": "SUM(order_qty * unit_price)", "unit": "元", "version": METRIC_VERSION},
    {"code": "quantity", "label": "件数", "grain": "order_item_id", "formula": "SUM(order_qty)", "unit": "件", "version": METRIC_VERSION},
    {"code": "order_count", "label": "相关订单数", "grain": "order_id", "formula": "COUNT(DISTINCT order_id)", "unit": "单", "version": METRIC_VERSION},
    {"code": "customer_count", "label": "购买客户数", "grain": "customer_id", "formula": "COUNT(DISTINCT customer_id)", "unit": "客户", "version": METRIC_VERSION},
]


def decimal(value):
    return Decimal(str(value or 0))


def number(value):
    return float(decimal(value).quantize(Decimal("0.01")))


def config_values(db):
    result = dict(DEFAULT_CONFIG)
    rows = db.query(DecisionConfig).order_by(DecisionConfig.key).all()
    result.update({r.key: r.value for r in rows})
    result["config_version"] = {r.key: r.version for r in rows}
    return result


def comparison_period(payload):
    if payload.comparison_mode == "none":
        return None
    if payload.comparison_mode == "previous":
        duration = payload.end_date - payload.start_date + timedelta(days=1)
        return payload.start_date - duration, payload.start_date - timedelta(days=1)
    def previous_year(day):
        try:
            return day.replace(year=day.year - 1)
        except ValueError:
            return day.replace(year=day.year - 1, day=28)
    return previous_year(payload.start_date), previous_year(payload.end_date)


def change(current, previous):
    return {"current": current, "previous": previous, "absolute": number(decimal(current) - decimal(previous)), "rate": float((decimal(current) - decimal(previous)) / decimal(previous)) if decimal(previous) > 0 else None, "baseline_status": "positive" if decimal(previous) > 0 else "zero_or_negative"}
