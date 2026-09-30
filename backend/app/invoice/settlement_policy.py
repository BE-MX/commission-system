"""Fail-closed rollout policy for the verified presale delivery path."""
from app.core.config import get_settings


def require_enabled():
    if not capabilities()["enabled"]:
        raise ValueError("预售全流程尚未启用")


def capabilities():
    settings = get_settings()
    warehouse = settings.OKKI_PRESALE_WAREHOUSE_ID
    ready = bool(settings.PRESALE_SETTLEMENT_ENABLED and settings.PRESALE_DELIVERY_ENABLED
                 and isinstance(warehouse, int) and not isinstance(warehouse, bool) and warehouse > 0)
    return {"enabled": ready, "freight_delivery_enabled": ready,
            "outbound_delivery_enabled": ready,
            "reason": "" if ready else "预售建单暂未开放：全流程派发或出库仓库尚未启用"}


def require_delivery():
    if not capabilities()["enabled"]:
        raise ValueError("预售全流程派发尚未启用")
