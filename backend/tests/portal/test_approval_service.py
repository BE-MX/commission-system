from decimal import Decimal
import pytest
from sqlalchemy import Column, Integer, Table, UniqueConstraint, func, select
from test_invoice_adapter import accepted, proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import ReceiptIntent
from app.portal import approval_service as service, invoice_adapter, admin_service
from app.portal.errors import PortalError
from app.portal.models import Conversion, Publication, PiAmendment, OrderRequest, CommandReceipt, OutboxEvent
from app.portal.schemas import ApproveInput


@pytest.fixture
def portal_metadata(portal_metadata):
    from test_admin_service import portal_metadata as admin_metadata
    portal_metadata = admin_metadata.__wrapped__(portal_metadata)
    for model in (Invoice, InvoiceItem, ReceiptIntent):
        table = portal_metadata.tables.get(model.__tablename__)
        if table is None:
            table = Table(model.__tablename__, portal_metadata)
        for column in model.__table__.columns:
            if column.name not in table.c:
                table.append_column(Column(column.name, Integer() if column.primary_key else column.type,
                    primary_key=column.primary_key, nullable=column.nullable))
        if model is Invoice:
            table.append_constraint(UniqueConstraint("invoice_no"))
    return portal_metadata


@pytest.fixture
def approving(accepted, monkeypatch):
    ctx, order, revision, records = accepted
    ctx.settings.PORTAL_INVOICE_ENABLED = True
    invoices = invoice_adapter.invoices
    monkeypatch.setattr(invoices, "resolve_okki_flags", lambda *args: {"okki_new_deal":1, "okki_free_shipping":0, "okki_first_return":0})
    monkeypatch.setattr(invoices, "get_customer_grade", lambda *args: None)
    monkeypatch.setattr(invoices, "suggest_invoice_no", lambda *args: "PI-PORTAL-TEST")
    monkeypatch.setattr(invoices.product_service, "valid_okki_product_skus", lambda db, pairs: pairs)
    return ctx, order, revision, records


def approve(ctx, order, revision, expected=3):
    result = service.approve(ctx.db, 1, order.public_id, expected, ApproveInput(accepted_revision_id=revision.public_id))
    ctx.db.commit()
    return result


def test_atomic_real_invoice_receipt_and_permanent_lineage(approving):
    ctx, order, revision, records = approving
    result = approve(ctx, order, revision)
    assert order.status == "invoice_created" and order.row_version == 4
    invoice = ctx.db.get(Invoice, order.invoice_id)
    assert invoice.total_amount == Decimal("128") and invoice.source_type == "portal"
    # Portal PIs carry no receipt intent draft; collection uses existing Ark entries.
    assert ctx.db.scalar(select(func.count()).select_from(ReceiptIntent)) == 0
    assert ctx.db.scalar(select(Conversion)).status == "created"
    assert ctx.db.scalar(select(PiAmendment)).status == "current"
    publication = ctx.db.scalar(select(Publication))
    assert publication.invoice_document_version == invoice.portal_document_version
    assert publication.customer_snapshot_json["line_bindings"][0]["line_key"] == records[0].line_key
    assert publication.customer_snapshot_json["line_bindings"][0]["invoice_item_id_at_publication"] == invoice.items[0].id
    ctx.observations = {}
    replay = approve(ctx, order, revision)
    assert replay["replayed"] and replay["original_receipt"] == result["original_receipt"]
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action == "approve")) == 1


def test_post_invoice_failure_rolls_back_every_artifact_and_can_retry(approving, monkeypatch):
    ctx, order, revision, records = approving
    real_create = invoice_adapter.create
    def fail_after_create(*args, **kwargs):
        real_create(*args, **kwargs)
        raise RuntimeError("injected after invoice flush")
    monkeypatch.setattr(invoice_adapter, "create", fail_after_create)
    with pytest.raises(RuntimeError):
        approve(ctx, order, revision)
    ctx.db.rollback()
    assert order.status == "ready_for_review" and order.invoice_id is None
    for model in (Invoice, InvoiceItem, ReceiptIntent, Conversion, Publication, PiAmendment):
        assert ctx.db.scalar(select(func.count()).select_from(model)) == 0
    monkeypatch.setattr(invoice_adapter, "create", real_create)
    assert approve(ctx, order, revision)["current_state"] == "invoice_created"


@pytest.mark.parametrize("change", ["expiry", "inventory", "version", "acceptance"])
def test_approval_rejects_stale_transaction_evidence(approving, monkeypatch, change):
    from app.portal import proposal_decisions
    ctx, order, revision, records = approving
    expected = 3
    if change == "expiry":
        monkeypatch.setattr(proposal_decisions, "beijing_now", lambda: revision.expires_at)
    elif change == "inventory":
        ctx.observations = {}
    elif change == "version":
        expected = 2
    else:
        order.accepted_revision_id = None
        ctx.db.commit()
    with pytest.raises(PortalError):
        approve(ctx, order, revision, expected=expected)
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 0
    assert ctx.db.scalar(select(func.count()).select_from(Conversion)) == 0


def test_invoice_permission_rechecked_even_on_success_replay(approving, monkeypatch):
    ctx, order, revision, records = approving
    approve(ctx, order, revision)
    current = admin_service.employee_principal
    def permission(db, actor, requested):
        if requested == "invoice:write":
            raise PortalError("ACTION_FORBIDDEN", "Denied", 403)
        return current(db, actor, requested)
    monkeypatch.setattr(admin_service, "employee_principal", permission)
    with pytest.raises(PortalError) as caught:
        approve(ctx, order, revision)
    assert caught.value.status == 403




def test_http_approval_and_failed_attempt_audit(approving):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    from app.portal.models import AuditEvent
    ctx, order, revision, records = approving
    app = FastAPI()
    app.include_router(router, prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    app.dependency_overrides[get_current_user] = lambda: {"sub":"1"}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = "/api/portal/admin/v1/orders/"+order.public_id+"/approve"
            body = {"accepted_revision_id":revision.public_id}
            assert (await client.post(path, json=body)).status_code == 428
            response = await client.post(path, json=body, headers={"If-Match":'"2"'})
            assert response.status_code == 409
            assert ctx.db.scalar(select(func.count()).select_from(Conversion)) == 0
            assert ctx.db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "order.approval_failed")) == 1
            response = await client.post(path, json=body, headers={"If-Match":'"3"'})
            assert response.status_code == 200 and response.json()["data"]["current_state"] == "invoice_created"
            replay = await client.post(path, json=body, headers={"If-Match":'"3"'})
            assert replay.json()["data"]["replayed"]
    asyncio.run(scenario())


@pytest.mark.parametrize("known", [True, False])
def test_only_known_number_conflict_retries_whole_transaction(approving, monkeypatch, known):
    import sqlite3
    from sqlalchemy.exc import IntegrityError
    ctx, order, revision, records = approving
    real = invoice_adapter.create
    calls = []
    def injected(*args, **kwargs):
        invoice = real(*args, **kwargs)
        calls.append(invoice.id)
        if len(calls) == 1:
            raise IntegrityError("private SQL", {}, sqlite3.IntegrityError(
                "UNIQUE constraint failed: ark_invoices.invoice_no" if known else "NOT NULL constraint failed: private"))
        return invoice
    monkeypatch.setattr(invoice_adapter, "create", injected)
    body = ApproveInput(accepted_revision_id=revision.public_id)
    if known:
        result = service.execute(ctx.db, 1, order.public_id, 3, body)
        assert result["current_state"] == "invoice_created" and len(calls) == 2
        assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 1
        assert ctx.db.scalar(select(func.count()).select_from(ReceiptIntent)) == 0
    else:
        with pytest.raises(IntegrityError):
            service.execute(ctx.db, 1, order.public_id, 3, body)
        assert len(calls) == 1
        assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 0
        assert ctx.db.scalar(select(func.count()).select_from(Conversion)) == 0


def test_number_conflict_retry_is_bounded(approving, monkeypatch):
    import sqlite3
    from sqlalchemy.exc import IntegrityError
    ctx, order, revision, records = approving
    calls = []
    def collision(*args, **kwargs):
        calls.append(1)
        raise IntegrityError("", {}, sqlite3.IntegrityError("UNIQUE constraint failed: ark_invoices.invoice_no"))
    monkeypatch.setattr(invoice_adapter, "create", collision)
    with pytest.raises(PortalError) as caught:
        service.execute(ctx.db, 1, order.public_id, 3, ApproveInput(accepted_revision_id=revision.public_id))
    assert caught.value.code == "INVOICE_NUMBER_CONFLICT" and len(calls) == 3
    assert ctx.db.scalar(select(func.count()).select_from(Conversion)) == 0
    from app.portal.models import AuditEvent
    assert ctx.db.scalar(select(AuditEvent).where(AuditEvent.action == "order.approval_failed")).reason == "INVOICE_NUMBER_CONFLICT"


def test_proposal_expiring_during_invoice_creation_rolls_back(approving, monkeypatch):
    from app.portal import proposal_decisions
    ctx, order, revision, records = approving
    real = invoice_adapter.create
    def crosses_deadline(*args, **kwargs):
        invoice = real(*args, **kwargs)
        monkeypatch.setattr(proposal_decisions, "beijing_now", lambda: revision.expires_at)
        return invoice
    monkeypatch.setattr(invoice_adapter, "create", crosses_deadline)
    with pytest.raises(PortalError):
        service.execute(ctx.db, 1, order.public_id, 3, ApproveInput(accepted_revision_id=revision.public_id))
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 0
    assert ctx.db.scalar(select(func.count()).select_from(Conversion)) == 0
    assert order.status == "ready_for_review"


def test_committed_response_loss_recovers_before_inventory_lookup(approving, monkeypatch):
    ctx, order, revision, records = approving
    body = ApproveInput(accepted_revision_id=revision.public_id)
    real_commit = ctx.db.commit
    def lost_response():
        real_commit()
        raise RuntimeError("response lost after commit")
    monkeypatch.setattr(ctx.db, "commit", lost_response)
    with pytest.raises(RuntimeError):
        service.execute(ctx.db, 1, order.public_id, 3, body)
    monkeypatch.setattr(ctx.db, "commit", real_commit)
    ctx.observations = {}
    result = service.execute(ctx.db, 1, order.public_id, 3, body)
    assert result["replayed"] and result["current_state"] == "invoice_created"
    assert ctx.db.scalar(select(func.count()).select_from(ReceiptIntent)) == 0
    for model in (Invoice, Conversion, Publication, PiAmendment):
        assert ctx.db.scalar(select(func.count()).select_from(model)) == 1


def test_invoice_switch_blocks_new_approval_but_not_completed_receipt(approving):
    ctx, order, revision, records = approving
    ctx.settings.PORTAL_INVOICE_ENABLED = False
    with pytest.raises(PortalError) as caught:
        approve(ctx, order, revision)
    assert caught.value.code == "SERVICE_UNAVAILABLE"
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 0
    assert ctx.db.scalar(select(func.count()).select_from(Conversion)) == 0
    ctx.settings.PORTAL_INVOICE_ENABLED = True
    result = approve(ctx, order, revision)
    ctx.settings.PORTAL_INVOICE_ENABLED = False
    ctx.observations = {}
    replay = approve(ctx, order, revision)
    assert replay["replayed"] and replay["original_receipt"] == result["original_receipt"]
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 1
