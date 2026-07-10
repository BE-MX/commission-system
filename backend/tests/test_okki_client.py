"""OKKI client_credentials token lifecycle tests (HTTP mocked)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.invoice import okki_client, xiaoman_service
from app.invoice.models import XiaomanSettings  # noqa: F401 - register metadata


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def _patch_credentials(monkeypatch, client_id="cid", secret="sec"):
    monkeypatch.setattr(
        okki_client, "get_settings",
        lambda: SimpleNamespace(
            OKKI_CLIENT_ID=client_id,
            OKKI_CLIENT_SECRET=secret,
            OKKI_API_BASE="https://okki.test",
        ),
    )


def test_fetch_token_success_and_error(monkeypatch):
    _patch_credentials(monkeypatch)
    monkeypatch.setattr(okki_client.httpx, "post", lambda *a, **kw: _FakeResp(
        {"token_type": "Bearer", "expires_in": 28800, "access_token": "tok_abc"}
    ))
    token, expires_at = okki_client.fetch_token()
    assert token == "tok_abc"
    assert expires_at > datetime.utcnow() + timedelta(hours=7)

    # OAuth 错误体 → OkkiApiError 且带可读信息
    monkeypatch.setattr(okki_client.httpx, "post", lambda *a, **kw: _FakeResp(
        {"error": "invalid_client", "error_description": "Client authentication failed"}
    ))
    with pytest.raises(okki_client.OkkiApiError, match="Client authentication failed"):
        okki_client.fetch_token()


def test_fetch_token_requires_credentials(monkeypatch):
    _patch_credentials(monkeypatch, client_id="", secret="")
    with pytest.raises(okki_client.OkkiApiError, match="OKKI_CLIENT_ID"):
        okki_client.fetch_token()


def test_ensure_access_token_uses_cache_and_refreshes(db, monkeypatch):
    row = xiaoman_service.get_or_create_settings(db)
    row.access_token = "cached_token"
    row.token_expires_at = datetime.utcnow() + timedelta(hours=2)
    db.commit()

    def _no_fetch():
        raise AssertionError("有效缓存时不应重新请求 token")

    monkeypatch.setattr(okki_client, "fetch_token", _no_fetch)
    assert okki_client.ensure_access_token(db) == "cached_token"

    # 过期（含 5 分钟缓冲内）→ 重新获取并落库
    row.token_expires_at = datetime.utcnow() + timedelta(minutes=2)
    db.commit()
    future = datetime.utcnow() + timedelta(hours=8)
    monkeypatch.setattr(okki_client, "fetch_token", lambda: ("fresh_token", future))
    assert okki_client.ensure_access_token(db) == "fresh_token"
    db.commit()
    assert row.access_token == "fresh_token"
    assert row.token_expires_at == future

    # force 无视缓存
    monkeypatch.setattr(okki_client, "fetch_token", lambda: ("forced_token", future))
    assert okki_client.ensure_access_token(db, force=True) == "forced_token"


def test_get_order_enums_retries_once_on_auth_failure(db, monkeypatch):
    _patch_credentials(monkeypatch)
    row = xiaoman_service.get_or_create_settings(db)
    row.access_token = "stale_token"
    row.token_expires_at = datetime.utcnow() + timedelta(hours=2)
    db.commit()

    calls = {"get": 0}

    def _fake_get(url, headers=None, timeout=None):
        calls["get"] += 1
        if headers["Authorization"] == "Bearer stale_token":
            return _FakeResp({"error": "access_denied"}, status_code=401)
        return _FakeResp({"code": 200, "data": {
            "order_status_list": [{"code": "1", "name": "草稿"}],
            "currency_list": [], "price_contract_list": [],
        }})

    monkeypatch.setattr(okki_client.httpx, "get", _fake_get)
    monkeypatch.setattr(
        okki_client, "fetch_token",
        lambda: ("renewed_token", datetime.utcnow() + timedelta(hours=8)),
    )

    enums = okki_client.get_order_enums(db)
    assert calls["get"] == 2
    assert enums["order_status_list"] == [{"code": "1", "name": "草稿"}]
    assert row.access_token == "renewed_token"
