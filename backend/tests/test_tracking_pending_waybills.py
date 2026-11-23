from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest

from app.tracking import polling_service
from app.tracking.carriers import dhl
from app.tracking.carriers.fedex import FedExAdapter
from app.tracking.carriers.base import TrackingResult
from app.tracking.models import ShipmentTracking, TrackingEvent
from app.tracking.status import normalize_status


@pytest.mark.parametrize("http_status,body,missing", [
    (404, {}, True), (200, {"shipments": []}, True), (200, {"error": "bad format"}, False),
    (503, {"reason": "unavailable"}, False),
])
async def test_dhl_missing_is_distinct_from_failure(monkeypatch, http_status, body, missing):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = httpx.Response(http_status, json=body)
    monkeypatch.setattr(dhl.httpx, "AsyncClient", lambda **kw: client)
    result = await dhl.DHLAdapter("test", "test").track("1234567890")
    assert not result.success
    assert result.not_found is missing


async def test_dhl_registered_without_events_exposes_only_destination_code(monkeypatch):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = httpx.Response(200, json={"shipments": [{
        "receiverDetails": {"postalAddress": {"countryCode": "GB"}},
        "shipperDetails": {"postalAddress": {"countryCode": "CN"}}, "events": [],
    }]})
    monkeypatch.setattr(dhl.httpx, "AsyncClient", lambda **kw: client)
    result = await dhl.DHLAdapter("test", "test").track("1234567890")
    assert result.success and not result.not_found and result.current_status == "pending"
    assert normalize_status("DHL", result.current_status) == "pending"
    assert result.destination_country == "GB" and result.events == []


@pytest.mark.parametrize("code,missing", [("TRACKING.TRACKINGNUMBER.NOTFOUND", True), ("SYSTEM.ERROR", False)])
def test_fedex_does_not_treat_per_shipment_errors_as_in_transit(code, missing):
    body = {"output": {"completeTrackResults": [{"trackResults": [{"error": {"code": code}}]}]}}
    result = FedExAdapter("test", "test")._parse_response("012345678901", body)
    assert not result.success and result.not_found is missing


@pytest.mark.parametrize("age,missing,physical,active,status", [
    (timedelta(days=7, seconds=-1), True, False, True, "承运商暂无记录，等待揽收"),
    (timedelta(days=7), True, False, False, "长期未揽收"),
    (timedelta(days=1), False, False, False, "原状态"),
    (timedelta(days=8), True, True, False, "原状态"),
])
async def test_poll_pending_window(db, monkeypatch, age, missing, physical, active, status):
    now = datetime(2026, 11, 23, 0, 0)
    shipment = ShipmentTracking(waybill_no="1234567890", carrier="dhl", carrier_name="DHL",
                                current_status_text="原状态", dingtalk_user_id="u", dingtalk_user_name="test",
                                created_at=now-age, consecutive_errors=9)
    db.add(shipment)
    if physical:
        db.add(TrackingEvent(waybill_no=shipment.waybill_no, carrier="dhl", event_time=now-age,
                             status_code="PU", description="Picked up"))
    db.commit()
    result = TrackingResult(False, shipment.waybill_no, "pending", "", "", None, [],
                            error="no shipments" if missing else "timeout", not_found=missing)
    adapter = AsyncMock()
    adapter.track.return_value = result
    monkeypatch.setattr(polling_service, "get_adapter", lambda carrier: adapter)
    monkeypatch.setattr(polling_service, "beijing_now", lambda: now)
    await polling_service.poll_single(db, shipment)
    assert shipment.is_active is active
    assert shipment.current_status_text == status
    assert shipment.consecutive_errors == (0 if missing and not physical else 10)
