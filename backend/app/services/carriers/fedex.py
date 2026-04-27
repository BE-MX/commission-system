"""FedEx Track API 适配器（OAuth2 + Track v1）"""

import time
from datetime import datetime
from typing import Optional

import httpx

from app.services.carriers.base import CarrierAdapter, TrackingResult, TrackingEvent


FEDEX_STATUS_MAP = {
    "PU": "picked_up", "OC": "picked_up",
    "IT": "in_transit", "DP": "in_transit", "AR": "in_transit",
    "OD": "out_for_delivery",
    "CC": "customs", "CD": "customs", "CU": "customs",
    "OH": "customs_hold",
    "DL": "delivered",
    "RS": "returned", "HL": "returned",
    "DE": "exception", "SE": "exception", "CA": "exception", "XP": "exception",
}


class FedExAdapter(CarrierAdapter):

    PROD_BASE = "https://apis.fedex.com"
    SAND_BASE = "https://apis-sandbox.fedex.com"

    def __init__(self, client_id: str, client_secret: str, sandbox: bool = False, timeout: float = 30.0):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = self.SAND_BASE if sandbox else self.PROD_BASE
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.base_url + "/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + body.get("expires_in", 3600)
        return self._token

    async def track(self, waybill_no: str) -> TrackingResult:
        try:
            token = await self._get_token()
        except Exception as e:
            return TrackingResult(False, waybill_no, "exception", "Token获取失败", "", None, [], error=str(e))

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.base_url + "/track/v1/trackingnumbers",
                    json={
                        "includeDetailedScans": True,
                        "trackingInfo": [{"trackingNumberInfo": {"trackingNumber": waybill_no}}],
                    },
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "X-locale": "zh_CN",
                    },
                )
                resp.raise_for_status()
                body = resp.json()
        except Exception as e:
            return TrackingResult(False, waybill_no, "exception", "API请求失败", "", None, [], error=str(e))

        return self._parse_response(waybill_no, body)

    def _parse_response(self, waybill_no: str, body: dict) -> TrackingResult:
        try:
            results = body.get("output", {}).get("completeTrackResults", [])
            if not results:
                return TrackingResult(False, waybill_no, "exception", "无追踪结果", "", None, [], error="empty")

            r = results[0].get("trackResults", [{}])[0]
            latest = r.get("latestStatusDetail", {})
            raw_code = latest.get("code", "")
            raw_text = latest.get("description", "")

            events = []
            for evt in r.get("scanEvents", []):
                dt_str = evt.get("date", "")
                try:
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.now()
                loc = evt.get("scanLocation", {})
                loc_str = f"{loc.get('city', '')} - {loc.get('countryCode', '')}".strip(" -")
                events.append(TrackingEvent(
                    event_time=dt,
                    description=evt.get("eventDescription", ""),
                    location=loc_str,
                    status_code=evt.get("eventType", ""),
                    raw=evt,
                ))

            events.sort(key=lambda e: e.event_time, reverse=True)
            cur_loc = events[0].location if events else ""
            last_time = events[0].event_time if events else None
            normalized = FEDEX_STATUS_MAP.get(raw_code.upper(), "in_transit")

            return TrackingResult(
                success=True,
                waybill_no=waybill_no,
                current_status=normalized,
                current_status_text=raw_text,
                current_location=cur_loc,
                last_event_time=last_time,
                events=events,
            )
        except Exception as e:
            return TrackingResult(False, waybill_no, "exception", "解析失败", "", None, [], error=str(e))
