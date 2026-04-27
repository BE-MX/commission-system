"""DHL MyDHL API 适配器"""

from datetime import datetime
from typing import Optional

import httpx

from app.services.carriers.base import CarrierAdapter, TrackingResult, TrackingEvent


DHL_STATUS_MAP = {
    "transit": "in_transit",
    "delivered": "delivered",
    "failure": "exception",
    "returned": "returned",
    "customs": "customs",
    "pre-transit": "pending",
}


class DHLAdapter(CarrierAdapter):

    ENV_URLS = {
        "test": "https://express.api.dhl.com/mydhlapi/test",
        "prod": "https://express.api.dhl.com/mydhlapi",
    }

    def __init__(self, username: str, password: str, env: str = "test", timeout: float = 30.0):
        self.base_url = self.ENV_URLS.get(env, self.ENV_URLS["test"])
        self.auth = (username, password)
        self.timeout = timeout

    async def track(self, waybill_no: str) -> TrackingResult:
        url = f"{self.base_url}/tracking"
        params = {"shipmentTrackingNumber": waybill_no}
        headers = {"Accept": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params, auth=self.auth, headers=headers)
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
            dt_str = evt.get("date", "")
            if dt_str and evt.get("time"):
                dt_str = f"{dt_str}T{evt['time']}"
            try:
                dt = datetime.fromisoformat(dt_str)
            except Exception:
                dt = datetime.now()
            loc = evt.get("serviceArea", {}).get("description", "")
            events.append(TrackingEvent(
                event_time=dt,
                description=evt.get("description", ""),
                location=loc,
                status_code=evt.get("typeCode", ""),
                raw=evt,
            ))

        events.sort(key=lambda e: e.event_time, reverse=True)
        status_obj = shipment.get("status", {})
        raw_status = status_obj.get("statusCode", "").lower()
        normalized = DHL_STATUS_MAP.get(raw_status, "in_transit")
        latest = events[0] if events else None

        return TrackingResult(
            success=True,
            waybill_no=waybill_no,
            current_status=normalized,
            current_status_text=latest.description if latest else "",
            current_location=latest.location if latest else "",
            last_event_time=latest.event_time if latest else None,
            events=events,
        )
