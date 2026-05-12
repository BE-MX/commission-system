"""物流跟踪 — 统一状态映射层

承运商原始状态 → 统一状态码 → 中文标签
"""

# FedEx scanEvent 事件码 → 统一状态
FEDEX_STATUS_MAP = {
    "PU": "picked_up",      # Picked up
    "OC": "picked_up",      # Origin city
    "IT": "in_transit",     # In transit
    "DP": "in_transit",     # Departed
    "AR": "in_transit",     # Arrived
    "OD": "out_for_delivery",  # Out for delivery
    "CC": "customs_hold",   # Clearance clearance — 用户要求归为清关/扣押
    "CD": "customs_hold",   # Clearance delay
    "CU": "customs_hold",   # Clearance update
    "OH": "customs_hold",   # On hold
    "HP": "customs_hold",   # Hold for payment
    "DL": "delivered",      # Delivered
    "RS": "returned",       # Returning
    "HL": "returned",       # Hold at location
    "DE": "exception",      # Delivery exception
    "SE": "exception",      # Shipment exception
    "CA": "exception",      # Canceled
    "XP": "exception",      # Exception
}

# DHL typeCode → 统一状态（DHL 返回的是 typeCode，不是高层状态）
DHL_STATUS_MAP = {
    "PU": "picked_up",       # Picked up
    "PL": "in_transit",      # Processed
    "DF": "in_transit",      # Departed facility
    "AF": "in_transit",      # Arrived at facility
    "TR": "in_transit",      # In transit
    "AR": "in_transit",      # Arrived
    "SM": "in_transit",      # Scheduled
    "WC": "out_for_delivery",  # With courier — 派送中
    "OH": "customs_hold",    # On hold
    "HP": "customs_hold",    # On hold awaiting payment
    "PY": "in_transit",      # Payment received，恢复运输
    "RR": "customs_hold",    # Customs clearance update
    "CR": "in_transit",      # Clearance processing complete
    "OK": "delivered",       # Delivered
    "DL": "delivered",       # Delivered
    "RS": "returned",        # Returning
    "RT": "returned",        # Returned
    "NU": "exception",       # Cannot deliver
    "MS": "exception",       # Missed delivery
}

# DHL 高层状态（兼容旧数据）→ 统一状态
DHL_HIGHLEVEL_MAP = {
    "pre-transit": "picked_up",
    "transit": "in_transit",
    "delivered": "delivered",
    "failure": "exception",
    "unknown": "in_transit",
}

# 触发钉钉推送的状态集合
PUSH_TRIGGER_STATUSES = {"out_for_delivery", "customs_hold", "delivered", "exception"}

# 统一状态中文显示
STATUS_LABELS = {
    "picked_up": "已揽收",
    "in_transit": "运输中",
    "customs_hold": "清关/扣押",
    "out_for_delivery": "派送中",
    "delivered": "已签收",
    "returned": "已退回",
    "exception": "异常",
    "pending": "待查询",
}


def normalize_status(carrier: str, raw_status: str) -> str:
    """将承运商原始状态归一化为统一状态码。

    carrier: 物流商标识（fedex / dhl / ...）
    raw_status: 承运商返回的原始状态码或高层状态
    """
    carrier_lower = (carrier or "").lower().strip()
    raw = (raw_status or "").strip()

    if not raw:
        return "pending"

    if carrier_lower == "fedex":
        return FEDEX_STATUS_MAP.get(raw.upper(), "in_transit")

    if carrier_lower == "dhl":
        # 优先按 typeCode 匹配（2字母大写），再按高层状态匹配
        return DHL_STATUS_MAP.get(raw.upper()) or DHL_HIGHLEVEL_MAP.get(raw.lower(), "in_transit")

    # 如果传入的已经是统一状态码，直接返回
    if raw in STATUS_LABELS:
        return raw

    return "in_transit"


def get_status_label(unified_status: str) -> str:
    """统一状态码 → 中文标签"""
    return STATUS_LABELS.get(unified_status, unified_status or "未知")
