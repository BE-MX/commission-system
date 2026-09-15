"""Carrier authentication failures must not look like missing shipments."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.tracking.carriers import dhl
from app.tracking import router


@pytest.mark.parametrize("status", [401, 403])
async def test_dhl_auth_error_is_actionable(monkeypatch, status):
    response = httpx.Response(status, json={
        "reasons": [{"msg": "Unauthorized"}],
        "details": {"msgId": "Id-test-auth"},
    })
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = response
    monkeypatch.setattr(dhl.httpx, "AsyncClient", lambda **kwargs: client)

    result = await dhl.DHLAdapter("user", "secret", env="production").track("0000000000")

    assert not result.success
    assert "DHL 接口鉴权失败" in result.error
    assert str(status) in result.error
    assert "正式环境" in result.error
    assert "Id-test-auth" in result.error
    assert "secret" not in result.error
    assert "reasons" not in result.error


async def test_dhl_auth_error_handles_non_json_response(monkeypatch):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = httpx.Response(401, text="Unauthorized")
    monkeypatch.setattr(dhl.httpx, "AsyncClient", lambda **kwargs: client)
    result = await dhl.DHLAdapter("user", "secret").track("0000000000")
    assert not result.success
    assert "测试环境" in result.error
    assert "请求编号" not in result.error


@pytest.mark.parametrize("result,code", [
    ({"status": "error", "error": "DHL 接口鉴权失败"}, 502),
    ({"error": "waybill missing"}, 404),
    ({"status": "ok", "new_events": 0}, 200),
])
async def test_refresh_distinguishes_upstream_failure(monkeypatch, result, code):
    monkeypatch.setattr(router, "refresh_single", AsyncMock(return_value=result))
    response = await router.refresh_shipment("0000000000", db=object(), _user={})
    assert response["code"] == code
