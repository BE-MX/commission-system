from copy import deepcopy

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, func, select

from test_order_queries import submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context
from test_quotes import body as quote_body
from app.invoice.models import InvoiceDelegateGrant
from app.portal import proposal_service as service, order_queries
from app.portal.errors import PortalError
from app.portal.models import CommandReceipt, OrderRequest, RequestLine, Revision
from app.portal.schemas import ProposalInput


@pytest.fixture
def proposing(submitted):
    ctx, order = submitted
    metadata = MetaData()
    from app.core.database import Base
    for name in ("ark_user_roles", "ark_roles", "ark_role_permissions", "ark_permissions"):
        source = Base.metadata.tables[name]
        Table(name, metadata, *(Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable) for c in source.columns))
    Table(InvoiceDelegateGrant.__tablename__, metadata, *(Column(c.name, Integer() if c.primary_key else c.type,
        primary_key=c.primary_key, nullable=c.nullable) for c in InvoiceDelegateGrant.__table__.columns))
    metadata.create_all(ctx.db.get_bind())
    return ctx, order


def body(ctx, **overrides):
    return ProposalInput.model_validate({**quote_body(ctx).model_dump(mode="json"),
        "fees": {"shipping_amount": "45.00", "packaging_amount": "2.00", "surcharge_amount": "0.00"},
        "payment_terms": "prepaid", "valid_for_hours": 24, "reason": "Confirmed freight", **overrides})


def propose(ctx, order, expected=1, actor=1, **overrides):
    result = service.create(ctx.db, actor, order["request_id"], expected, body(ctx, **overrides))
    ctx.db.commit()
    return result


def test_proposal_current_prices_fees_and_snapshot_replay(proposing):
    ctx, order = proposing
    original = ctx.db.scalar(select(Revision))
    original_hash = original.content_hash
    line_key = ctx.db.scalar(select(RequestLine)).line_key
    result = propose(ctx, order)
    assert result["current_state"] == "awaiting_customer"
    detail = order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])
    assert detail["product_amount"] == "81.00" and detail["total_amount"] == "128.00"
    assert detail["fees"]["status"] == "confirmed" and detail["items"][0]["line_key"] == line_key
    assert detail["proposal"]["content_hash"] == result["original_receipt"]["content_hash"]
    assert detail["proposal"]["expired"] is False and detail["proposal"]["accepted"] is False
    assert original.content_hash == original_hash and original.fees_status == "pending"
    replay = propose(ctx, order)
    assert replay["replayed"] and replay["original_receipt"] == result["original_receipt"]
    assert ctx.db.scalar(select(func.count()).select_from(Revision)) == 2
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action=="propose")) == 1


def test_proposal_payload_conflict_and_stale_version(proposing):
    ctx, order = proposing
    propose(ctx, order)
    with pytest.raises(PortalError) as caught:
        propose(ctx, order, remark="Changed")
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    ctx.db.rollback()
    with pytest.raises(PortalError) as caught:
        propose(ctx, order, expected=7)
    assert caught.value.code == "VERSION_CONFLICT"


def test_other_employee_requires_explicit_delegate_grant(proposing):
    ctx, order = proposing
    with pytest.raises(PortalError) as caught:
        propose(ctx, order, actor=2)
    assert caught.value.status == 404
    ctx.db.rollback()
    ctx.db.add(InvoiceDelegateGrant(delegate_user_id=2, sales_user_id=1, created_by=1))
    ctx.db.commit()
    assert propose(ctx, order, actor=2)["current_state"] == "awaiting_customer"


@pytest.mark.parametrize("field,value", [("payment_terms", "arbitrary"), ("valid_for_hours", 7), ("customer_po", "Changed")])
def test_proposal_rejects_unapproved_policy_or_po_change(proposing, field, value):
    ctx, order = proposing
    with pytest.raises(PortalError) as caught:
        propose(ctx, order, **{field: value})
    assert caught.value.status == 422
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Revision)) == 1


def test_proposal_failure_rolls_back_version_receipt_and_lines(proposing):
    ctx, order = proposing
    service.create(ctx.db, 1, order["request_id"], 1, body(ctx))
    ctx.db.rollback()
    row = ctx.db.scalar(select(OrderRequest))
    assert row.status == "submitted" and row.row_version == 1
    assert ctx.db.scalar(select(func.count()).select_from(Revision)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(RequestLine)) == 1


def test_new_proposal_from_ready_state_clears_acceptance_not_history(proposing):
    ctx, order = proposing
    first = propose(ctx, order)
    row = ctx.db.scalar(select(OrderRequest))
    row.status = "ready_for_review"
    row.accepted_revision_id = row.active_revision_id
    ctx.db.commit()
    old_id = row.active_revision_id
    old_hash = ctx.db.get(Revision, old_id).content_hash
    result = propose(ctx, order, expected=2, remark="Updated delivery note")
    assert result["current_state"] == "awaiting_customer" and row.accepted_revision_id is None
    assert row.active_revision_id != old_id and ctx.db.get(Revision, old_id).content_hash == old_hash


def test_proposal_http_and_price_revocation(proposing, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx, order = proposing
    app = FastAPI()
    app.include_router(router, prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1"}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = "/api/portal/admin/v1/orders/"+order["request_id"]+"/proposals"
            payload = body(ctx).model_dump(mode="json")
            assert (await client.post(path, json=payload)).status_code == 428
            response = await client.post(path, json=payload, headers={"If-Match": '"1"'})
            assert response.status_code == 200 and response.json()["data"]["current_state"] == "awaiting_customer"
            replay = await client.post(path, json=payload, headers={"If-Match": '"1"'})
            assert replay.json()["data"]["replayed"]
    asyncio.run(scenario())
    ctx.access.can_order = ctx.access.can_view_price = False
    ctx.db.commit()
    detail = order_queries.customer_detail(ctx.db, ctx.session_token, order["request_id"])
    assert "proposal" not in detail and "total_amount" not in detail


def test_expired_pending_proposal_can_be_replaced_without_customer_action(proposing, monkeypatch):
    from app.portal import quote_service
    from app.portal.inventory import InventoryObservation
    ctx, order = proposing
    first = propose(ctx, order)
    row = ctx.db.scalar(select(OrderRequest))
    old = ctx.db.get(Revision, row.active_revision_id)
    old_hash = old.content_hash
    with pytest.raises(PortalError) as caught:
        propose(ctx, order, expected=2)
    assert caught.value.code == "VERSION_CONFLICT"
    ctx.db.rollback()
    now = old.expires_at
    monkeypatch.setattr(service, "beijing_now", lambda: now)
    monkeypatch.setattr(quote_service, "beijing_now", lambda: now)
    ctx.observations = {key: InventoryObservation(value.quantity, value.unit, now, value.source)
                        for key, value in ctx.observations.items()}
    result = propose(ctx, order, expected=2)
    assert result["row_version"] == 3 and row.active_revision_id != old.id
    assert old.content_hash == old_hash
    assert result["original_receipt"]["revision_id"] != first["original_receipt"]["revision_id"]
