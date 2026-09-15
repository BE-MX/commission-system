"""LAN HTTP -> Beijing HTTPS with isolated transports, no production DB or sessions."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.colorwork import proxy, service
from app.colorwork.router import router
from app.core.database import get_db


class Body(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content

    async def __aiter__(self):
        yield self.content


@pytest.fixture
def lan(monkeypatch):
    seen = []
    settings = SimpleNamespace(
        COLORWORK_GATEWAY_ORIGIN="https://leshine.cloud",
        COLORWORK_INTERNAL_ORIGIN="http://127.0.0.1:8787",
        COLORWORK_SSO_SECRET="office-secret-must-not-sign", JWT_SECRET_KEY="office-jwt",
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    monkeypatch.setattr(proxy, "get_settings", lambda: settings)

    def upstream(request):
        seen.append(request)
        if request.url.host != "leshine.cloud":
            return httpx.Response(401, json={"code": 401, "message": "unauthorized"})
        if request.url.path == "/api/colorwork/sso":
            if request.headers.get("authorization") != "Bearer lan-user":
                return httpx.Response(401, json={"detail": "Token无效或已过期"})
            view = request.url.params["view"]
            return httpx.Response(200, json={
                "url": service.build_sso_url(view, "beijing-signed-token"),
                "view": view, "views": ["library", "inventory", "master"], "expires_in": 120,
            })
        if request.url.path.endswith("/api/auth/ark"):
            assert request.url.params["token"] == "beijing-signed-token"
            return httpx.Response(302, headers={
                "location": "/api/colorwork/workbench/?view=" + request.url.params["view"],
                "set-cookie": "inventory_workbench_session=beijing-session; Path=/api/colorwork/workbench; HttpOnly; Secure; SameSite=Lax; Max-Age=43200",
            })
        if request.url.path.endswith("/api/auth/logout"):
            return httpx.Response(303, headers={
                "location": "https://leshine.cloud/api/colorwork/workbench/",
                "set-cookie": "inventory_workbench_session=; Path=/api/colorwork/workbench; HttpOnly; Secure; SameSite=Lax; Max-Age=0",
            })
        if "inventory_workbench_session=beijing-session" not in request.headers.get("cookie", ""):
            return httpx.Response(401, json={"detail": "session missing"})
        if request.method == "PUT" and request.headers.get("origin") != "https://leshine.cloud":
            return httpx.Response(403, json={"detail": "cross origin"})
        return httpx.Response(200, content=b"workbench contents")

    async def async_upstream(request):
        response = upstream(request)
        return httpx.Response(response.status_code, headers=response.headers, stream=Body(response.content))

    original_async, original_sync = httpx.AsyncClient, httpx.Client
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_async(
        **kwargs, transport=httpx.MockTransport(async_upstream)))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_sync(
        **kwargs, transport=httpx.MockTransport(upstream)))
    app = FastAPI()
    app.include_router(router, prefix="/api/colorwork")
    app.include_router(proxy.router, prefix="/api/colorwork")
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "lan-test", "username": "sales", "roles": ["super_admin"], "permissions": [],
    }
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app, base_url="http://192.168.101.193:8001") as client:
        yield client, seen, settings


@pytest.mark.parametrize("view", ["library", "inventory", "master"])
def test_lan_login_and_refresh_use_beijing_sso_and_cookie(lan, view):
    client, seen, _ = lan
    link = client.get("/api/colorwork/sso", params={"view": view}, headers={"authorization": "Bearer lan-user"})
    assert link.status_code == 200
    url = link.json()["url"]
    assert parse_qs(urlsplit(url).query)["token"] == ["beijing-signed-token"]
    entered = client.get(url)
    assert entered.status_code == 200
    assert entered.url.host == "192.168.101.193"
    cookie = entered.history[0].headers["set-cookie"]
    assert "secure" not in cookie.lower()
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()
    assert "Path=/api/colorwork/workbench" in cookie
    assert client.get("/api/colorwork/workbench/?view=" + view).status_code == 200
    assert all(request.url.host == "leshine.cloud" for request in seen)
    assert seen[0].headers["authorization"] == "Bearer lan-user"
    assert all("authorization" not in request.headers for request in seen[1:])


def test_lan_upload_checks_browser_origin_then_translates_upstream_origin(lan):
    client, seen, _ = lan
    client.cookies.set("inventory_workbench_session", "beijing-session")
    client.cookies.set("ark_refresh_token", "private")
    content = bytes(range(256)) * 10
    result = client.put("/api/colorwork/workbench/api/upload", content=content, headers={
        "origin": "http://192.168.101.193:8001", "authorization": "Bearer never-forward",
    })
    assert result.status_code == 200
    assert seen[-1].content == content
    assert seen[-1].headers["cookie"] == "inventory_workbench_session=beijing-session"
    assert "authorization" not in seen[-1].headers
    count = len(seen)
    assert client.put("/api/colorwork/workbench/api/upload", content=content,
                      headers={"origin": "https://evil.example"}).status_code == 403
    assert len(seen) == count


def test_lan_logout_clears_cookie_and_keeps_redirect_local(lan):
    client, _, _ = lan
    client.cookies.set("inventory_workbench_session", "beijing-session",
                       domain="192.168.101.193", path="/api/colorwork/workbench")
    result = client.get("/api/colorwork/workbench/api/auth/logout", follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"] == "/api/colorwork/workbench/"
    assert "secure" not in result.headers["set-cookie"].lower()
    assert not client.cookies.get("inventory_workbench_session")


def test_https_entry_keeps_secure_cookie(lan):
    client, _, _ = lan
    response = client.get("https://lan.example/api/colorwork/workbench/api/auth/ark?token=beijing-signed-token&view=library",
                          follow_redirects=False)
    assert response.status_code == 302
    assert "; Secure" in response.headers["set-cookie"]


@pytest.mark.parametrize("path", ["/api/colorwork/sso?view=library", "/api/colorwork/workbench/"])
def test_gateway_loop_is_stopped_before_upstream_request(lan, path):
    client, seen, _ = lan
    result = client.get(path, headers={service.RELAY_HEADER: "1", "authorization": "Bearer lan-user"})
    assert result.status_code == 503
    assert not seen


def test_gateway_sso_still_enforces_view_permission_and_owner_auth(lan):
    client, seen, _ = lan
    denied = client.get("/api/colorwork/sso?view=library", headers={"authorization": "Bearer invalid"})
    assert denied.status_code == 401
    count = len(seen)
    client.app.dependency_overrides[get_current_user] = lambda: {"sub": "lan-test", "roles": [], "permissions": []}
    assert client.get("/api/colorwork/sso?view=master").status_code == 403
    assert len(seen) == count


def test_gateway_failure_does_not_leak_bearer(lan, monkeypatch):
    client, _, _ = lan
    def fail(*args, **kwargs):
        raise httpx.ConnectError("Bearer private-token must not be displayed")
    monkeypatch.setattr(service.httpx, "Client", fail)
    response = client.get("/api/colorwork/sso?view=library", headers={"authorization": "Bearer private-token"})
    assert response.status_code == 503
    assert "private-token" not in response.text


@pytest.mark.parametrize("platform,expected", [("win32", "https://leshine.cloud"), ("linux", "")])
def test_default_config_selects_office_gateway_or_beijing_runtime(monkeypatch, platform, expected):
    from app.core import config
    monkeypatch.setattr(config, "sys", SimpleNamespace(platform=platform))
    monkeypatch.delenv("COLORWORK_GATEWAY_ORIGIN", raising=False)
    settings = config.Settings(_env_file=None, APP_ENV="development")
    assert settings.COLORWORK_GATEWAY_ORIGIN == expected
    assert config.Settings(_env_file=None, APP_ENV="development", COLORWORK_GATEWAY_ORIGIN="").COLORWORK_GATEWAY_ORIGIN == ""
