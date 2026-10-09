from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from test_quotes import quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, create
from app.core.time import beijing_now
from app.invoice.models import CustomerPriceRule
from app.portal import order_service as service, quote_service, catalog_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, CatalogGrant, OrderRequest, OutboxEvent, Quote, RequestLine, Revision
from app.portal.schemas import SubmitInput


@pytest.fixture
def submission(quoting):
    quote = create(quoting)
    return quoting, uuid4(), SubmitInput(quote_id=quote["quote_id"], quote_content_hash=quote["content_hash"],
                                        customer_po="PO-1", remark="Please review")


def submit(ctx, key, body):
    result = service.submit(ctx.db, ctx.session_token, ctx.session_csrf, key, body)
    ctx.db.commit()
    return result


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_submission_creates_one_request_revision_lines_and_event(submission):
    ctx, key, body = submission
    first = submit(ctx, key, body)
    assert first["status"] == "submitted" and first["product_amount"] == "81.00"
    assert first["total_amount"] is None and first["replayed"] is False
    order = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.scalar(select(Revision))
    line = ctx.db.scalar(select(RequestLine))
    assert order.active_revision_id == revision.id and order.accepted_revision_id is None
    assert order.invoice_id is None and order.servicing_user_id == ctx.access.sales_user_id
    assert revision.kind == "submitted" and revision.fees_status == "pending"
    assert revision.delivery_json["address_line1"] == "10 Example Street"
    assert line.unit_price == Decimal("27.0000") and line.unit_weight_grams == Decimal("20")
    assert ctx.db.scalar(select(Quote)).status == "consumed"
    event = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.event_type=="order_submitted"))
    assert event.payload_json == {"request_id": first["request_id"]}
    assert "Example" not in str(event.payload_json)
    for _ in range(3):
        replay = submit(ctx, key, body)
        assert replay["request_id"] == first["request_id"] and replay["replayed"]
    assert count(ctx.db, OrderRequest) == count(ctx.db, Revision) == count(ctx.db, RequestLine) == 1
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type=="order_submitted")) == 1


def test_same_key_different_content_conflicts_and_new_key_cannot_reuse_quote(submission):
    ctx, key, body = submission
    submit(ctx, key, body)
    with pytest.raises(PortalError) as caught:
        submit(ctx, key, body.model_copy(update={"remark": "different"}))
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    ctx.db.rollback()
    with pytest.raises(PortalError) as caught:
        submit(ctx, uuid4(), body)
    assert caught.value.code == "QUOTE_UNAVAILABLE"
    ctx.db.rollback()
    assert count(ctx.db, OrderRequest) == 1


def test_success_replay_survives_expiry_source_failure_and_closed_writes(submission, monkeypatch):
    ctx, key, body = submission
    first = submit(ctx, key, body)
    def unavailable(*args, **kwargs):
        pytest.fail("Committed replay read inventory or price")
    monkeypatch.setattr(catalog_service, "load_observations", unavailable)
    monkeypatch.setattr(quote_service.pricing, "resolve", unavailable)
    monkeypatch.setattr(quote_service, "beijing_now", lambda: beijing_now()+timedelta(days=1))
    ctx.settings.PORTAL_WRITES_ENABLED = False
    ctx.access.can_order = False
    ctx.db.commit()
    result = submit(ctx, key, body)
    assert result["request_id"] == first["request_id"] and result["replayed"]
    assert service.by_key(ctx.db, ctx.session_token, key)["request_id"] == first["request_id"]


def test_replay_and_recovery_strip_amount_after_price_revocation(submission):
    ctx, key, body = submission
    submit(ctx, key, body)
    ctx.access.can_order = ctx.access.can_view_price = False
    ctx.db.commit()
    for result in (submit(ctx, key, body), service.by_key(ctx.db, ctx.session_token, key)):
        assert not {"product_amount", "total_amount", "currency"} & result.keys()
    ctx.access.status = "suspended"
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        submit(ctx, key, body)
    assert caught.value.status == 401


@pytest.mark.parametrize("change", ["price", "grant", "mapping", "policy", "stock", "source", "po", "hash", "expired"])
def test_new_submission_rechecks_quote_and_current_authority(submission, change, monkeypatch):
    ctx, key, body = submission
    if change == "price":
        ctx.db.get(CustomerPriceRule, 1).adjust_value = Decimal("-20")
    elif change == "grant":
        ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id==ctx.items[0].id)).status = "disabled"
    elif change == "mapping":
        ctx.access.mapping_version += 1
    elif change == "policy":
        ctx.site.policy_version += 1
    elif change == "stock":
        ctx.observations.clear()
    elif change == "source":
        ctx.db.execute(text("UPDATE okki_products SET disable_flag=1 WHERE product_id=101"))
    elif change == "po":
        body = body.model_copy(update={"customer_po": "changed"})
    elif change == "hash":
        body = body.model_copy(update={"quote_content_hash": "0"*64})
    else:
        expires = ctx.db.scalar(select(Quote)).expires_at
        monkeypatch.setattr(quote_service, "beijing_now", lambda: expires)
    ctx.db.commit()
    with pytest.raises(PortalError):
        submit(ctx, key, body)
    ctx.db.rollback()
    assert count(ctx.db, OrderRequest) == count(ctx.db, Revision) == count(ctx.db, RequestLine) == 0
    assert ctx.db.scalar(select(Quote)).status == "valid"


def test_transaction_rollback_preserves_quote_and_removes_all_submission_artifacts(submission):
    ctx, key, body = submission
    service.submit(ctx.db, ctx.session_token, ctx.session_csrf, key, body)
    ctx.db.rollback()
    assert ctx.db.scalar(select(Quote)).status == "valid"
    for model in (OrderRequest, Revision, RequestLine):
        assert count(ctx.db, model) == 0
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type=="order_submitted")) == 0
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action=="order.submitted")) == 0
    assert submit(ctx, key, body)["status"] == "submitted"


def test_recovery_unknown_key_is_not_found(submission):
    ctx, key, _ = submission
    with pytest.raises(PortalError) as caught:
        service.by_key(ctx.db, ctx.session_token, key)
    assert caught.value.status == 404


def test_other_account_cannot_replay_or_recover_known_key(submission):
    from app.portal import auth_service
    from app.portal.models import Account, Membership
    from test_auth_service import send_code, verify
    ctx, key, body = submission
    submit(ctx, key, body)
    account = Account(email_normalized="second@example.com", email_display="second@example.com",
                      contact_name="Second", status="active")
    ctx.db.add(account)
    ctx.db.flush()
    ctx.db.add(Membership(site_id=ctx.site.id, account_id=account.id, access_id=ctx.access.id, status="active"))
    ctx.db.commit()
    ctx.preauth, ctx.token, ctx.csrf = auth_service.bootstrap(ctx.db, "127.0.0.2")
    ctx.db.commit()
    challenge, code = send_code(ctx, "second@example.com")
    _, session, token = verify(ctx, challenge, code)
    for call in (lambda: service.by_key(ctx.db, token, key),
                 lambda: service.submit(ctx.db, token, auth_service._csrf(session), key, body)):
        with pytest.raises(PortalError) as caught:
            call()
        assert caught.value.status == 404
        ctx.db.rollback()
    assert count(ctx.db, OrderRequest) == 1


def test_failure_after_revision_flush_leaves_no_partial_order(submission):
    from sqlalchemy import event
    ctx, key, body = submission
    def crash(db, flush_context):
        if any(isinstance(row, Revision) for row in db.new):
            raise RuntimeError("Injected failure after revision SQL")
    event.listen(ctx.db, "after_flush", crash)
    try:
        with pytest.raises(RuntimeError, match="Injected failure"):
            submit(ctx, key, body)
    finally:
        event.remove(ctx.db, "after_flush", crash)
        ctx.db.rollback()
    assert count(ctx.db, OrderRequest) == count(ctx.db, Revision) == 0
    assert ctx.db.scalar(select(Quote)).status == "valid"
    assert submit(ctx, key, body)["replayed"] is False


def test_order_http_retry_and_unique_conflict_recovery(submission, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from sqlalchemy.exc import IntegrityError
    from app.core.database import get_db
    from app.portal import router as http
    ctx, key, body = submission
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(http, "get_settings", lambda: ctx.settings)
    app = FastAPI()
    app.include_router(http.router, prefix="/api/portal/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url=ctx.settings.PORTAL_ORIGIN, headers={"X-Real-IP": "203.0.113.1",
            "Origin": ctx.settings.PORTAL_ORIGIN, "X-Portal-CSRF": ctx.session_csrf}) as client:
            path = "/api/portal/v1/orders"
            client.cookies.set("__Host-portal_session", ctx.session_token)
            payload = body.model_dump(mode="json")
            assert (await client.post(path, json=payload)).status_code == 428
            headers = {"Idempotency-Key": str(key)}
            first = await client.post(path, json=payload, headers=headers)
            assert first.status_code == 201 and first.headers["cache-control"] == "no-store"
            replay = await client.post(path, json=payload, headers=headers)
            assert replay.status_code == 200 and replay.json()["data"]["replayed"]
            recovered = await client.get(path+"/by-key/"+str(key))
            assert recovered.json()["data"]["request_id"] == first.json()["data"]["request_id"]
            def collision(*args, **kwargs):
                raise IntegrityError("test", {}, Exception(1062, "Duplicate entry for key uq_op_request_key"))
            monkeypatch.setattr(service, "submit", collision)
            recovered = await client.post(path, json=payload, headers=headers)
            assert recovered.status_code == 200 and recovered.json()["data"]["replayed"]
            def unrelated(*args, **kwargs):
                raise IntegrityError("test", {}, Exception(1452, "Foreign key violation"))
            monkeypatch.setattr(service, "submit", unrelated)
            assert (await client.post(path, json=payload, headers=headers)).status_code == 500
    asyncio.run(scenario())


@pytest.mark.parametrize("target", ["revision", "line", "missing_line"])
def test_recovery_rejects_persisted_evidence_drift(submission, target):
    ctx, key, body = submission
    submit(ctx, key, body)
    # Simulate storage corruption outside guarded ORM; never an authorized writer.
    if target == "revision":
        ctx.db.execute(text("UPDATE ark_order_portal_revisions SET product_amount=1"))
    elif target == "line":
        ctx.db.execute(text("UPDATE ark_order_portal_request_lines SET unit_price=1"))
    else:
        ctx.db.execute(text("DELETE FROM ark_order_portal_request_lines"))
    ctx.db.commit()
    ctx.db.expire_all()
    with pytest.raises(PortalError) as caught:
        service.by_key(ctx.db, ctx.session_token, key)
    assert caught.value.code == "ORDER_UNAVAILABLE"
