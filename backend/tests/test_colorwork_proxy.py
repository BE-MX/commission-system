"""Same-origin file proxy tests with in-memory upstreams, no database/network."""
import gzip
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.colorwork import proxy


class Body(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.closed = False

    async def __aiter__(self):
        yield self.data

    async def aclose(self):
        self.closed = True


@pytest.fixture
def harness(monkeypatch):
    seen = []
    body = Body(gzip.compress(b"test file contents"))

    async def handle(request):
        seen.append((request, await request.aread()))
        return httpx.Response(206, headers={
            "content-encoding": "gzip", "content-type": "application/octet-stream",
            "content-disposition": "attachment; filename=test.bin", "content-range": "bytes 0-17/18",
            "set-cookie": "inventory_workbench_session=next; Path=/api/colorwork/workbench; HttpOnly",
        }, stream=body)

    original = httpx.AsyncClient
    monkeypatch.setattr(proxy.httpx, "AsyncClient", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handle),
    ))
    monkeypatch.setattr(proxy, "get_settings", lambda: SimpleNamespace(
        COLORWORK_INTERNAL_ORIGIN="http://127.0.0.1:8787",
    ))
    app = FastAPI()
    app.include_router(proxy.router, prefix="/api/colorwork")
    with TestClient(app, base_url="https://leshine.cloud") as client:
        yield client, seen, body


def test_download_keeps_bytes_headers_and_only_module_cookie(harness):
    client, seen, body = harness
    response = client.get("/api/colorwork/workbench/api/files/a%20b?inline=1", headers={
        "cookie": "ark_session=private; inventory_workbench_session=allowed",
        "authorization": "Bearer private", "range": "bytes=0-17",
        "x-forwarded-proto": "http", "x-forwarded-host": "evil.example",
        "referer": "https://leshine.cloud/secret", "connection": "x-private",
        "x-private": "secret",
    })
    assert response.status_code == 206
    assert response.content == b"test file contents"
    assert response.headers["content-disposition"] == "attachment; filename=test.bin"
    assert response.headers["content-security-policy"] == "frame-ancestors 'self'"
    request, content = seen[0]
    assert request.url.host == "127.0.0.1"
    assert request.url.raw_path == b"/api/colorwork/workbench/api/files/a%20b?inline=1"
    assert request.headers["cookie"] == "inventory_workbench_session=allowed"
    assert request.headers["range"] == "bytes=0-17"
    assert request.headers["x-forwarded-proto"] == "https"
    assert request.headers["x-forwarded-host"] == "leshine.cloud"
    assert not {"authorization", "referer", "x-private"} & set(request.headers)
    assert body.closed


def test_binary_upload_and_cross_origin_rejection(harness):
    client, seen, _ = harness
    content = bytes(range(256)) * 400
    client.put("/api/colorwork/workbench/api/upload", content=content,
               headers={"origin": "https://leshine.cloud", "content-type": "application/octet-stream"})
    assert seen[0][1] == content
    response = client.put("/api/colorwork/workbench/api/upload", content=content,
                          headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert len(seen) == 1


def test_runtime_failure_is_readable_without_token(harness, monkeypatch):
    client, _, _ = harness

    async def fail(*args, **kwargs):
        raise httpx.ConnectError("secret-token URL must not be logged")

    original = httpx.AsyncClient

    def factory(**kwargs):
        result = original(**kwargs)
        result.send = fail
        return result

    monkeypatch.setattr(proxy.httpx, "AsyncClient", factory)
    response = client.get("/api/colorwork/workbench/api/auth/ark?token=secret-token")
    assert response.status_code == 503
    assert "secret-token" not in response.text


@pytest.mark.asyncio
async def test_interrupted_upstream_closes_resources():
    class Broken(Body):
        async def __aiter__(self):
            yield b"first"
            raise httpx.ReadError("broken")

    body = Broken(b"")
    response = httpx.Response(200, stream=body)
    client = httpx.AsyncClient()
    with pytest.raises(httpx.ReadError):
        async for _ in proxy._stream(response, client):
            pass
    assert body.closed
    assert client.is_closed
