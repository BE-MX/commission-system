"""Fail-closed rollout policy; a feature switch is not remote capability evidence."""
from app.core.config import get_settings


def require_enabled():
    if not get_settings().PRESALE_SETTLEMENT_ENABLED:
        raise ValueError("预售发货结算尚未启用")


def capabilities():
    return {"enabled": get_settings().PRESALE_SETTLEMENT_ENABLED,
            "freight_delivery_enabled": False, "outbound_delivery_enabled": False,
            "reason": "小满运费承载、统计分类及分批出库契约尚待隔离验证，自动外发未启用"}


def require_delivery():
    # Deliberately no operator boolean bypass: replace only with a verified adapter.
    raise ValueError("REMOTE_CAPABILITY_UNVERIFIED：小满分批出库和运费能力尚未核验")
