import asyncio
import threading
from importlib import import_module

import httpx
import pytest

from social_customer_mcp.app import app, mcp
from social_customer_mcp.models import SocialCustomerRecord, SocialCustomerSearchResult


TOKEN = "test-token-that-is-at-least-32-characters"


def _headers(token=TOKEN):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }


def _result():
    return SocialCustomerSearchResult(
        matched_by="email",
        total=1,
        count=1,
        offset=0,
        has_more=False,
        next_offset=None,
        items=[
            SocialCustomerRecord(
                customer_company="Alpha Hair",
                customer_name="Alpha",
                contact_name="Alice",
                customer_email="sales@example.com",
                contact_email="alice@example.com",
                owner_user_name="未进入私海",
            )
        ],
    )


@pytest.mark.asyncio
async def test_transport_rejects_missing_and_invalid_token():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost:8100"
    ) as client:
        missing = await client.post("/", json={})
        invalid = await client.post("/", json={}, headers=_headers("wrong-token"))
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert TOKEN not in missing.text


@pytest.mark.asyncio
async def test_mcp_transport_contract_and_nonblocking_queries(monkeypatch, caplog):
    app_module = import_module("social_customer_mcp.app")
    monkeypatch.setattr(app_module.query_service, "search", lambda _params: _result())
    transport = httpx.ASGITransport(app=app)

    async with mcp.session_manager.run():
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:8100"
        ) as client:
            initialized = await client.post(
                "/",
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            listed = await client.post(
                "/",
                headers=_headers(),
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            )
            called = await client.post(
                "/",
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "social_customer_search",
                        "arguments": {"params": {"email": "sales@example.com"}},
                    },
                },
            )

            secret_lookup = "victim@example.com"

            def failed_search(_params):
                raise RuntimeError(secret_lookup)

            monkeypatch.setattr(app_module.query_service, "search", failed_search)
            failed = await client.post(
                "/",
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 31,
                    "method": "tools/call",
                    "params": {
                        "name": "social_customer_search",
                        "arguments": {"params": {"email": secret_lookup}},
                    },
                },
            )

            started = threading.Event()
            release = threading.Event()

            def slow_search(_params):
                started.set()
                release.wait(timeout=2)
                return _result()

            monkeypatch.setattr(app_module.query_service, "search", slow_search)
            call_task = asyncio.create_task(
                client.post(
                    "/",
                    headers=_headers(),
                    json={
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {
                            "name": "social_customer_search",
                            "arguments": {"params": {"email": "sales@example.com"}},
                        },
                    },
                )
            )
            try:
                assert await asyncio.to_thread(started.wait, 1)
                health = await asyncio.wait_for(client.get("/health"), timeout=0.25)
            finally:
                release.set()
            concurrent_call = await call_task

            async with httpx.AsyncClient(
                transport=transport, base_url="http://evil.example"
            ) as untrusted_client:
                bad_host = await untrusted_client.post("/", json={}, headers=_headers())
            bad_origin = await client.post(
                "/",
                json={},
                headers={**_headers(), "Origin": "https://evil.example"},
            )

    assert initialized.status_code == 200, initialized.text
    tools = (listed.json().get("result") or {}).get("tools") or []
    assert [tool["name"] for tool in tools] == ["social_customer_search"]
    assert "params" in tools[0]["inputSchema"]["properties"]
    assert "ctx" not in tools[0]["inputSchema"]["properties"]
    assert tools[0]["annotations"]["readOnlyHint"] is True

    assert called.status_code == 200, called.text
    result = called.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["items"][0]["owner_user_name"] == "未进入私海"
    assert failed.json()["result"]["isError"] is True
    assert secret_lookup not in caplog.text
    assert health.status_code == 200
    assert concurrent_call.status_code == 200
    assert bad_host.status_code == 421
    assert bad_origin.status_code == 403
