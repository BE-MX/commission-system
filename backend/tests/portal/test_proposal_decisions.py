import pytest
from sqlalchemy import select, func
from test_proposals import proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, propose
from app.portal import proposal_decisions as service, order_queries
from app.portal.models import OrderRequest, Revision, CommandReceipt, OutboxEvent
from app.portal.schemas import AcceptInput, ReasonInput
from app.portal.errors import PortalError


def decision(ctx, order, proposal, accept=True, expected=2, reason="Please revise shipping", digest=None, commit=True):
    receipt = proposal["original_receipt"]
    body = AcceptInput(proposal_hash=digest or receipt["content_hash"]) if accept else ReasonInput(reason=reason)
    result = service.decide(ctx.db, ctx.session_token, ctx.session_csrf, order["request_id"], receipt["revision_id"], expected, body, accept=accept)
    if commit:
        ctx.db.commit()
    return result


def test_accept_and_replay_preserve_evidence(proposing):
    ctx, order = proposing
    proposal = propose(ctx, order)
    result = decision(ctx, order, proposal)
    row = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.get(Revision, row.active_revision_id)
    assert row.status == "ready_for_review" and row.accepted_revision_id == revision.id
    assert revision.customer_accepted_by is not None and revision.customer_accepted_at is not None
    assert revision.content_hash == proposal["original_receipt"]["content_hash"]
    assert row.invoice_id is None
    replay = decision(ctx, order, proposal)
    assert replay["replayed"] and replay["original_receipt"] == result["original_receipt"]
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action == "accept")) == 1
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == "order_accepted")) == 1
    next_proposal = propose(ctx, order, expected=3, remark="New terms")
    replay = decision(ctx, order, proposal)
    assert replay["current_state"] == "awaiting_customer"
    assert row.accepted_revision_id is None and row.active_revision_id != revision.id
    assert next_proposal["original_receipt"]["revision_id"] != revision.public_id


@pytest.mark.parametrize("change", ["hash", "expiry", "policy", "inventory", "capability"])
def test_accept_rejects_changed_terms(proposing, monkeypatch, change):
    ctx, order = proposing
    proposal = propose(ctx, order)
    row = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.get(Revision, row.active_revision_id)
    kwargs = {}
    if change == "hash":
        kwargs["digest"] = "0" * 64
    elif change == "expiry":
        monkeypatch.setattr(service, "beijing_now", lambda: revision.expires_at)
    elif change == "policy":
        ctx.access.mapping_version += 1
        ctx.db.commit()
    elif change == "inventory":
        ctx.observations = {}
    else:
        ctx.access.can_order = False
        ctx.db.commit()
    with pytest.raises(PortalError):
        decision(ctx, order, proposal, **kwargs)
    ctx.db.rollback()
    assert row.status == "awaiting_customer" and row.accepted_revision_id is None
    assert revision.customer_accepted_by is None


def test_reject_expired_proposal_and_replay(proposing, monkeypatch):
    ctx, order = proposing
    proposal = propose(ctx, order)
    row = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.get(Revision, row.active_revision_id)
    monkeypatch.setattr(service, "beijing_now", lambda: revision.expires_at)
    result = decision(ctx, order, proposal, accept=False)
    assert result["current_state"] == "submitted" and row.accepted_revision_id is None
    assert decision(ctx, order, proposal, accept=False)["replayed"]
    with pytest.raises(PortalError) as caught:
        decision(ctx, order, proposal, accept=False, reason="Different reason")
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"


def test_decision_rollback_is_atomic(proposing):
    ctx, order = proposing
    proposal = propose(ctx, order)
    decision(ctx, order, proposal, commit=False)
    ctx.db.rollback()
    row = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.get(Revision, row.active_revision_id)
    assert row.status == "awaiting_customer" and row.row_version == 2
    assert row.accepted_revision_id is None and revision.customer_accepted_at is None
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action == "accept")) == 0


def test_replay_requires_current_capabilities(proposing):
    ctx, order = proposing
    proposal = propose(ctx, order)
    decision(ctx, order, proposal)
    ctx.access.can_view_price = ctx.access.can_order = False
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        decision(ctx, order, proposal)
    assert caught.value.status == 403



def test_decision_http_contract_and_csrf(proposing, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http
    ctx, order = proposing
    proposal = propose(ctx, order)
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
            path = "/api/portal/v1/orders/"+order["request_id"]+"/proposals/"+proposal["original_receipt"]["revision_id"]+"/accept"
            payload = {"proposal_hash": proposal["original_receipt"]["content_hash"]}
            assert (await client.post(path, json=payload)).status_code == 428
            assert (await client.post(path, json=payload, headers={"If-Match": '"2"', "X-Portal-CSRF": "wrong"})).status_code == 403
            response = await client.post(path, json=payload, headers={"If-Match": '"2"'})
            assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
            assert response.json()["data"]["current_state"] == "ready_for_review"
            replay = await client.post(path, json=payload, headers={"If-Match": '"2"'})
            assert replay.json()["data"]["replayed"]
    asyncio.run(scenario())


def test_unrelated_revision_and_stale_version_are_rejected(proposing):
    ctx, order = proposing
    proposal = propose(ctx, order)
    with pytest.raises(PortalError) as caught:
        decision(ctx, order, proposal, expected=1)
    assert caught.value.code == "VERSION_CONFLICT"
    ctx.db.rollback()
    submitted_revision = ctx.db.scalar(select(Revision).where(Revision.kind == "submitted"))
    proposal["original_receipt"]["revision_id"] = submitted_revision.public_id
    with pytest.raises(PortalError) as caught:
        decision(ctx, order, proposal)
    assert caught.value.status == 404
