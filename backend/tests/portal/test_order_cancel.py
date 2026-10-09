from copy import deepcopy

import pytest
from sqlalchemy import func, select

from test_order_queries import submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context
from app.portal import order_commands as service, order_queries
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, CommandReceipt, OrderRequest, OutboxEvent, Quote, RequestLine, Revision
from app.portal.schemas import ReasonInput


def cancel(ctx, order, expected=1, reason="Plans changed"):
    result = service.cancel(ctx.db, ctx.session_token, ctx.session_csrf, order["request_id"], expected, ReasonInput(reason=reason))
    ctx.db.commit()
    return result


@pytest.mark.parametrize("state", ["submitted", "awaiting_customer", "ready_for_review"])
def test_cancel_retains_history_and_replays_without_repeating_events(submitted, state):
    ctx, order = submitted
    row = ctx.db.scalar(select(OrderRequest))
    row.status = state
    ctx.db.commit()
    old = deepcopy(ctx.db.scalar(select(Quote)).lines_json)
    result = cancel(ctx, order)
    assert result["current_state"] == "cancelled" and result["row_version"] == 2
    replay = cancel(ctx, order, expected=1)
    assert replay["replayed"] and replay["original_receipt"] == result["original_receipt"]
    assert ctx.db.scalar(select(Quote)).lines_json == old
    assert ctx.db.scalar(select(Quote)).status == "consumed"
    assert ctx.db.scalar(select(func.count()).select_from(Revision)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(RequestLine)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action=="cancel")) == 1
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type=="order_cancelled")) == 1
    assert order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])["available_actions"] == []


def test_cancel_version_conflict_and_different_replay_body(submitted):
    ctx, order = submitted
    with pytest.raises(PortalError) as caught:
        cancel(ctx, order, expected=2)
    assert caught.value.code == "VERSION_CONFLICT"
    ctx.db.rollback()
    cancel(ctx, order)
    with pytest.raises(PortalError) as caught:
        cancel(ctx, order, reason="Another reason")
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("state", ["invoice_created", "rejected"])
def test_cancel_rejects_terminal_order(submitted, state):
    ctx, order = submitted
    ctx.db.scalar(select(OrderRequest)).status = state
    ctx.db.commit()
    with pytest.raises(PortalError):
        cancel(ctx, order)
    ctx.db.rollback()
    assert ctx.db.scalar(select(OrderRequest)).status == state


def test_cancel_rechecks_capability_even_for_replay(submitted):
    ctx, order = submitted
    cancel(ctx, order)
    ctx.access.can_order = False
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        cancel(ctx, order)
    assert caught.value.status == 403


def test_cancel_rollback_restores_state_and_removes_receipt(submitted):
    ctx, order = submitted
    service.cancel(ctx.db, ctx.session_token, ctx.session_csrf, order["request_id"], 1, ReasonInput(reason="Changed"))
    ctx.db.rollback()
    assert ctx.db.scalar(select(OrderRequest)).status == "submitted"
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action=="cancel")) == 0
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action=="order.cancelled")) == 0


def test_detail_advertises_cancel_only_with_current_capabilities(submitted, monkeypatch):
    ctx, order = submitted
    monkeypatch.setattr(order_queries, "get_settings", lambda: ctx.settings)
    assert order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])["available_actions"] == ["cancel"]
    ctx.settings.PORTAL_WRITES_ENABLED = False
    assert order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])["available_actions"] == []


def test_conversion_lineage_blocks_cancel_even_if_request_state_is_wrong(submitted, portal_metadata, monkeypatch):
    from app.portal.models import Conversion
    ctx, order = submitted
    monkeypatch.setattr(order_queries, "get_settings", lambda: ctx.settings)
    row = ctx.db.scalar(select(OrderRequest))
    ctx.db.execute(portal_metadata.tables["ark_invoices"].insert(), {"id": 1})
    ctx.db.add(Conversion(request_id=row.id, approved_revision_id=row.active_revision_id,
        operation_key="test-conversion", payload_hash="a"*64, invoice_id=1, invoice_document_version=1,
        status="created", created_by=1))
    ctx.db.commit()
    assert order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])["available_actions"] == []
    with pytest.raises(PortalError) as caught:
        cancel(ctx, order)
    assert caught.value.code == "INVOICE_ALREADY_CREATED"
    ctx.db.rollback()
    assert ctx.db.scalar(select(OrderRequest)).status == "submitted"


def test_cancel_http_requires_version_and_replays_original_receipt(submitted, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http
    ctx, order = submitted
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(http, "get_settings", lambda: ctx.settings)
    app = FastAPI()
    app.include_router(http.router, prefix="/api/portal/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
            headers={"X-Real-IP": "203.0.113.1", "Origin": ctx.settings.PORTAL_ORIGIN,
                     "X-Portal-CSRF": ctx.session_csrf}) as client:
            client.cookies.set("__Host-portal_session", ctx.session_token)
            path = "/api/portal/v1/orders/"+order["request_id"]+"/cancel"
            payload = {"reason": "Plans changed"}
            assert (await client.post(path, json=payload)).status_code == 428
            assert (await client.post(path, json=payload, headers={"If-Match": "1"})).status_code == 422
            response = await client.post(path, json=payload, headers={"If-Match": '"1"'})
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            result = response.json()["data"]
            assert result["current_state"] == "cancelled" and not result["replayed"]
            replay = await client.post(path, json=payload, headers={"If-Match": '"1"'})
            assert replay.json()["data"]["original_receipt"] == result["original_receipt"]
            assert replay.json()["data"]["replayed"]
    asyncio.run(scenario())
