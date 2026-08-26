"""DHL MyDHL API 适配器"""

from datetime import datetime

import httpx

from app.tracking.carriers.base import CarrierAdapter, TrackingResult, TrackingEvent


# DHL event typeCode → 系统状态
DHL_TYPECODE_MAP = {
    "PU": "in_transit",    # Picked up
    "PL": "in_transit",    # Processed
    "DF": "in_transit",    # Departed facility
    "AF": "in_transit",    # Arrived at facility
    "TR": "in_transit",    # In transit
    "AR": "in_transit",    # Arrived
    "SM": "in_transit",    # Scheduled
    "WC": "out_for_delivery", # With courier
    "OH": "customs_hold",  # On hold
    "HP": "customs_hold",  # Hold for payment
    "PY": "in_transit",    # Payment received
    "RR": "customs",       # Customs clearance update
    "CR": "in_transit",    # Clearance complete
    "OK": "delivered",     # Delivered
    "DL": "delivered",     # Delivered
    "RS": "returned",      # Returning
    "RT": "returned",      # Returned
    "NU": "exception",     # Cannot deliver
    "MS": "exception",     # Missed delivery
}


def _parse_event_datetime(event: dict) -> datetime:
    """Parse MyDHL local event time only when its instant is unambiguous."""
    value = event.get("date", "")
    if value and event.get("time"):
        value = f"{value}T{event['time']}"
    offset = event.get("GMTOffset") or event.get("gmtOffset") or event.get("gmt_offset")
    if offset and value and not value.endswith(("Z", "z")):
        if len(value) < 6 or value[-6] not in "+-":
            value = f"{value}{offset}"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        # 官方契约规定无 offset 时是事件地当地时间；仅有
        # serviceArea 文字无法唯一推出 IANA 时区，不得冒充北京时间。
        raise ValueError("DHL event missing GMT offset")
    return parsed


class DHLAdapter(CarrierAdapter):

    ENV_URLS = {
        "test": "https://express.api.dhl.com/mydhlapi/test",
        "prod": "https://express.api.dhl.com/mydhlapi",
        "production": "https://express.api.dhl.com/mydhlapi",
    }

    def __init__(self, username: str, password: str, env: str = "test", timeout: float = 30.0):
        self.base_url = self.ENV_URLS.get(env, self.ENV_URLS["test"])
        self.auth = (username, password)
        self.timeout = timeout

    async def track(self, waybill_no: str) -> TrackingResult:
        url = f"{self.base_url}/shipments/{waybill_no}/tracking"
        headers = {"Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    url,
                    auth=self.auth,
                    headers=headers,
                    params={"requestGMTOffsetPerEvent": "true"},
                )
        except Exception as e:
            return TrackingResult(False, waybill_no, "exception", "请求失败", "", None, [], error=str(e))

        if resp.status_code != 200:
            return TrackingResult(False, waybill_no, "exception", f"HTTP {resp.status_code}", "", None, [], error=resp.text[:500])

        try:
            data = resp.json()
        except Exception:
            return TrackingResult(False, waybill_no, "exception", "JSON解析失败", "", None, [], error="invalid json")

        shipments = data.get("shipments", [])
        if not shipments:
            return TrackingResult(False, waybill_no, "exception", "未找到运单", "", None, [], error="no shipments")

        shipment = shipments[0]
        raw_events = shipment.get("events", [])
        events = []
        for evt in raw_events:
            try:
                dt = _parse_event_datetime(evt)
            except (TypeError, ValueError) as exc:
                return TrackingResult(
                    False, waybill_no, "exception", "DHL事件缺少时区偏移", "",
                    None, [], error=str(exc),
                )
            loc_raw = evt.get("serviceArea", [])
            if isinstance(loc_raw, list):
                loc = loc_raw[0].get("description", "") if loc_raw else ""
            else:
                loc = loc_raw.get("description", "")
            events.append(TrackingEvent(
                event_time=dt,
                description=evt.get("description", ""),
                location=loc,
                status_code=evt.get("typeCode", ""),
                raw=evt,
            ))

        events.sort(key=lambda e: e.event_time, reverse=True)
        latest = events[0] if events else None

        # 从最新事件的 typeCode 推断状态
        latest_typecode = latest.status_code.upper() if latest else ""
        normalized = DHL_TYPECODE_MAP.get(latest_typecode, "in_transit")

        # 提取预计送达时间（优先取根节点 estimatedDeliveryDate）
        est_dt = None
        for field in ("estimatedDeliveryDate", "estimatedTimeOfDelivery", "estimatedDeliveryTime"):
            eta_str = shipment.get(field)
            if eta_str:
                try:
                    est_dt = datetime.fromisoformat(eta_str)
                    break
                except Exception:
                    continue

        return TrackingResult(
            success=True,
            waybill_no=waybill_no,
            current_status=normalized,
            current_status_text=latest.description if latest else "",
            current_location=latest.location if latest else "",
            last_event_time=latest.event_time if latest else None,
            events=events,
            estimated_delivery_date=est_dt,
        )
