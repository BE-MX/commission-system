"""Canonical proof storage never falls back or bypasses invoice visibility."""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.receipt import attachments, storage_proxy
from app.receipt.models import ReceiptAttachment
from tests.test_receipt_management import USER, api_client


def request(hop=False):
    headers = [(b"authorization", b"Bearer test-only")]
    if hop:
        headers.append((b"x-ark-receipt-proxy-hop", b"1"))
    return Request({"type": "http", "headers": headers})


@pytest.fixture
def proxy(monkeypatch):
    settings = SimpleNamespace(RECEIPT_STORAGE_PROXY_URL="https://storage.test.invalid")
    monkeypatch.setattr(storage_proxy, "get_settings", lambda: settings)
    return settings


def test_forward_fixed_origin_auth_and_no_redirects(proxy, monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 30, "follow_redirects": False}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return httpx.Response(200, json={"code": 200, "data": {"id": "test"}})
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return httpx.Response(200, content=b"image", headers={"content-type": "image/png"})
    monkeypatch.setattr(httpx, "Client", Client)
    storage_proxy.forward(request(), "/api/receipts/attachments", b"image", "test.png")
    assert calls[0][0] == "https://storage.test.invalid/api/receipts/attachments"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-only"
    assert calls[0][1]["headers"][storage_proxy.HOP_HEADER] == "1"
    assert calls[0][1]["files"]["file"][1] == b"image"
    result = storage_proxy.forward(request(), "/api/receipts/attachments/test")
    assert result.body == b"image" and result.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("url", ["http://storage.test", "https://u:p@storage.test", "https://storage.test/path", "https://storage.test?x=1"])
def test_invalid_origin_rejected(proxy, url):
    proxy.RECEIPT_STORAGE_PROXY_URL = url
    with pytest.raises(HTTPException) as error:
        storage_proxy.origin()
    assert error.value.status_code == 503


def test_loop_rejected_before_network(proxy):
    with pytest.raises(HTTPException, match="循环"):
        storage_proxy.forward(request(True), "/api/receipts/attachments/test")


def test_shared_metadata_binding_and_owner_file_check(db, proxy, tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "STORAGE_ROOT", tmp_path)
    row = ReceiptAttachment(id="test", filename="test.png", storage_key="test.png", content_type="image/png",
                            size=20, sha256="a" * 64, created_by=1)
    db.add(row); db.flush()
    attachments.bind(db, [row.id], 1, 1)
    proxy.RECEIPT_STORAGE_PROXY_URL = ""
    with pytest.raises(ValueError, match="文件缺失"):
        attachments.bind(db, [row.id], 1, 1)


def test_private_route_checks_owner_before_proxy(db, proxy, monkeypatch):
    row = ReceiptAttachment(id="test", filename="test.png", storage_key="test.png", content_type="image/png",
                            size=20, sha256="a" * 64, created_by=99)
    db.add(row); db.commit()
    monkeypatch.setattr(storage_proxy, "forward", lambda *a: pytest.fail("permission bypass"))
    with api_client(db, USER) as client:
        assert client.get("/api/receipts/attachments/test").status_code == 404
