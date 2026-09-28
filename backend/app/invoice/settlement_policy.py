"""Fail-closed rollout policy; a feature switch is not remote capability evidence."""
from app.core.config import get_settings


def require_enabled():
    if not get_settings().PRESALE_SETTLEMENT_ENABLED:
        raise ValueError("预售发货结算尚未启用")


def capabilities():
    return {"enabled": get_settings().PRESALE_SETTLEMENT_ENABLED,
            "freight_delivery_enabled": False, "outbound_delivery_enabled": False,
            "reason": "预售建单暂未开放：方舟全流程、权限和数据库迁移尚待验收"}


def require_delivery():
    # Deliberately no operator boolean bypass: replace only with a verified adapter.
    raise ValueError("REMOTE_CAPABILITY_UNVERIFIED：预售端到端发货能力尚未验收")
