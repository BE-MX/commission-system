from decimal import Decimal
import pytest
from sqlalchemy import Column, Integer, Table, select, func

from test_portal_invoice_lifecycle import published, approving, accepted, proposing, submitted, submission, quoting, priced_catalog, catalog, managed, auth_context
from test_approval_service import portal_metadata as approval_metadata
from app.core.time import beijing_now
from app.invoice.models import Invoice, InvoiceSyncLog, OkkiOutboundTask
from app.receipt.models import Receipt, ReceiptIntent
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection.models import ShippingOperationEvent
from app.portal import pi_void_service as service, pi_service, order_queries, approval_service, order_rejection_service
from app.portal.errors import PortalError
from app.portal.models import Conversion, Publication, PiAmendment, OrderRequest, CommandReceipt, Revision, AuditEvent, OutboxEvent
from app.portal.schemas import VoidPiInput, ReasonInput, ApproveInput


@pytest.fixture
def portal_metadata(portal_metadata):
    portal_metadata = approval_metadata.__wrapped__(portal_metadata)
    for model in (Receipt, InvoiceAllocation, InvoiceSyncLog, OkkiOutboundTask, ShippingOperationEvent):
        if model.__tablename__ not in portal_metadata.tables:
            Table(model.__tablename__,portal_metadata,*(Column(column.name,Integer() if column.primary_key and column.type.python_type is int else column.type,
                primary_key=column.primary_key,nullable=not column.primary_key) for column in model.__table__.columns))
    return portal_metadata


def body(invoice):
    return VoidPiInput(invoice_document_version=invoice.portal_document_version,reason="Customer cancelled before fulfillment")


def test_void_retains_invoice_lineage_drafts_and_revokes_download(published,monkeypatch):
    ctx,invoice = published
    monkeypatch.setattr(order_queries,"get_settings",lambda:ctx.settings)
    order = ctx.db.scalar(select(OrderRequest))
    # Portal PIs no longer receive an automatic intent; create the draft the way
    # the existing Ark invoice-edit entry would, then verify void disarms it.
    intent = ReceiptIntent(invoice_id=invoice.id, eligible=1, created_by=1,
                           attachment_ids=["retained-proof"], status="draft")
    ctx.db.add(intent)
    ctx.db.commit()
    original,expected = body(invoice),order.row_version
    result = service.void(ctx.db,1,order.public_id,expected,original)
    ctx.db.commit()
    assert invoice.status == "cancelled" and invoice.cancellation["mode"] == "local_void"
    assert ctx.db.scalar(select(Conversion)).status == "tombstoned"
    assert intent.status == "draft" and intent.eligible == 0 and intent.attachment_ids == ["retained-proof"]
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 1
    assert ctx.db.scalar(select(Publication)).status == "withdrawn"
    assert ctx.db.scalar(select(PiAmendment)).active_revision_id is None
    assert order.status == "invoice_created" and invoice.portal_document_version == 2
    detail = order_queries.customer_detail(ctx.db,ctx.session_token,order.public_id)
    assert detail["pi_amendment"]["status"] == "voided" and "download_pi" not in detail["available_actions"]
    with pytest.raises(PortalError):
        pi_service.capture(ctx.db,ctx.session_token,order.public_id)
    ctx.db.rollback()
    ctx.observations = {}
    assert service.void(ctx.db,1,order.public_id,expected,original)["original_receipt"] == result["original_receipt"]
    assert ctx.db.scalar(select(func.count()).select_from(InvoiceSyncLog)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action=="pi_voided")) == 1
    with pytest.raises(PortalError) as error:
        service.void(ctx.db,1,order.public_id,expected,original.model_copy(update={"reason":"Different request"}))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("blocker",["remote","synced","uncertain","status","cancellation","attempt","linked","receipt","intent","intent_token","allocation","outbound","shipping"])
def test_void_fails_closed_with_live_or_uncertain_business(published,portal_metadata,blocker):
    ctx,invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    if blocker == "remote": invoice.xiaoman_order_id = "100"
    elif blocker == "synced": invoice.synced_at = beijing_now()
    elif blocker == "uncertain": invoice.sync_status = "sync_uncertain"
    elif blocker == "status": invoice.status = "sync_uncertain"
    elif blocker == "cancellation": invoice.cancellation = {"status":"pending"}
    elif blocker == "attempt": invoice.sync_attempt = {"token":"old-attempt"}
    elif blocker == "linked": invoice.linked_sync_id = "pending"
    elif blocker == "receipt":
        ctx.db.execute(portal_metadata.tables[Receipt.__tablename__].insert(),{"id":1,"invoice_id":invoice.id,"status":"active","sync_status":"pending"})
    elif blocker in {"intent", "intent_token"}:
        intent = ReceiptIntent(invoice_id=invoice.id, eligible=1, created_by=1, attachment_ids=[], status="draft")
        if blocker == "intent": intent.status = "armed"
        else: intent.attempt_token = "pending"
        ctx.db.add(intent)
    elif blocker == "allocation":
        ctx.db.add(InvoiceAllocation(invoice_id=invoice.id,material_id=1,status="allocated",allocated_qty_grams=Decimal("1"),pending_delta_grams=0))
    elif blocker == "outbound":
        ctx.db.execute(portal_metadata.tables[OkkiOutboundTask.__tablename__].insert(),{"id":1,"invoice_id":invoice.id,"status":"pending"})
    else:
        ctx.db.execute(portal_metadata.tables[ShippingOperationEvent.__tablename__].insert(),{
            "id":1,"scope":"outbound-invoice-sync","action":"sync_pending","payload":{"invoice_id":invoice.id}})
    ctx.db.commit()
    version = invoice.portal_document_version
    with pytest.raises(PortalError) as error:
        service.void(ctx.db,1,order.public_id,order.row_version,body(invoice))
    assert error.value.code == "PI_VOID_REQUIRES_REVIEW"
    ctx.db.rollback()
    assert ctx.db.scalar(select(Conversion)).status == "created"
    assert invoice.portal_document_version == version and invoice.status != "cancelled"


def test_void_rollback_restores_publication_and_financial_draft(published):
    ctx,invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    version = order.row_version
    ctx.db.add(ReceiptIntent(invoice_id=invoice.id, eligible=1, created_by=1, attachment_ids=[], status="draft"))
    ctx.db.commit()
    eligible = ctx.db.scalar(select(ReceiptIntent)).eligible
    service.void(ctx.db,1,order.public_id,version,body(invoice))
    ctx.db.rollback()
    assert invoice.status != "cancelled" and invoice.portal_document_version == 1
    assert order.row_version == version
    assert ctx.db.scalar(select(Conversion)).status == "created"
    assert ctx.db.scalar(select(Publication)).status == "published"
    assert ctx.db.scalar(select(ReceiptIntent)).eligible == eligible
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action=="pi_voided")) == 0


def test_void_cannot_reactivate_or_rebuild_pi(published):
    ctx,invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    service.void(ctx.db,1,order.public_id,order.row_version,body(invoice))
    ctx.db.commit()
    invoice.status = "ready"
    with pytest.raises(ValueError,match="reactivated"):
        ctx.db.flush()
    ctx.db.rollback()
    old_revision = ctx.db.get(Revision,order.accepted_revision_id)
    replay = approval_service.approve(ctx.db,1,order.public_id,3,ApproveInput(accepted_revision_id=old_revision.public_id))
    assert replay["replayed"]
    assert invoice.status == "cancelled" and ctx.db.scalar(select(Conversion)).status == "tombstoned"
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 1


def test_reactivation_guard_uses_current_locked_lineage_read(published):
    from sqlalchemy import event
    from sqlalchemy.dialects import mysql
    ctx,invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    service.void(ctx.db,1,order.public_id,order.row_version,body(invoice))
    ctx.db.commit()
    statements = []
    def capture(execution):
        if execution.is_select:
            statements.append(str(execution.statement.compile(dialect=mysql.dialect())))
    event.listen(ctx.db,"do_orm_execute",capture)
    try:
        invoice.status = "synced"
        with pytest.raises(ValueError,match="reactivated"):
            ctx.db.flush()
    finally:
        event.remove(ctx.db,"do_orm_execute",capture)
        ctx.db.rollback()
    locked = [sql for sql in statements if "SELECT ark_order_portal_conversions.status" in sql]
    assert locked and all("FOR UPDATE" in sql for sql in locked)
    assert all("status =" not in sql for sql in locked)


def test_void_scope_versions_and_current_replay_permission(published,monkeypatch):
    ctx,invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    command,expected = body(invoice),order.row_version
    with pytest.raises(PortalError) as error:
        service.void(ctx.db,2,order.public_id,expected,command)
    assert error.value.status == 404
    ctx.db.rollback()
    with pytest.raises(PortalError) as error:
        service.void(ctx.db,1,order.public_id,expected+1,command)
    assert error.value.code == "VERSION_CONFLICT"
    ctx.db.rollback()
    service.void(ctx.db,1,order.public_id,expected,command)
    ctx.db.commit()
    from app.portal import admin_service
    def revoked(*args): raise PortalError("ACTION_FORBIDDEN","Revoked",403)
    monkeypatch.setattr(admin_service,"employee_principal",revoked)
    with pytest.raises(PortalError) as error:
        service.void(ctx.db,1,order.public_id,expected,command)
    assert error.value.status == 403


def test_employee_reject_preserves_acceptance_and_replays_original_command(accepted):
    ctx,order,revision,records = accepted
    expected = order.row_version
    accepted_at = revision.customer_accepted_at
    command = ReasonInput(reason="Unable to fulfill this request")
    result = order_rejection_service.reject_request(ctx.db,1,order.public_id,expected,command)
    ctx.db.commit()
    assert order.status == "rejected" and order.accepted_revision_id is None
    assert revision.customer_accepted_at == accepted_at
    assert order_rejection_service.reject_request(ctx.db,1,order.public_id,expected,command)["original_receipt"] == result["original_receipt"]
    with pytest.raises(PortalError) as error:
        order_rejection_service.reject_request(ctx.db,1,order.public_id,expected,ReasonInput(reason="Different reason"))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_employee_reject_cannot_target_an_existing_pi(published):
    ctx,invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    with pytest.raises(PortalError) as error:
        order_rejection_service.reject_request(ctx.db,1,order.public_id,order.row_version,ReasonInput(reason="Wrong workflow"))
    assert error.value.code == "INVOICE_ALREADY_CREATED"
    ctx.db.rollback()
    assert ctx.db.scalar(select(Conversion)).status == "created"


def test_rejection_scope_and_transaction_rollback(accepted):
    ctx,order,revision,records = accepted
    expected = order.row_version
    command = ReasonInput(reason="Cannot supply")
    with pytest.raises(PortalError) as error:
        order_rejection_service.reject_request(ctx.db,2,order.public_id,expected,command)
    assert error.value.status == 404
    ctx.db.rollback()
    order_rejection_service.reject_request(ctx.db,1,order.public_id,expected,command)
    ctx.db.rollback()
    assert order.status == "ready_for_review" and order.accepted_revision_id == revision.id
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt).where(CommandReceipt.action=="reject")) == 0


def test_void_http_requires_version_and_returns_same_receipt(published):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal import admin_router
    ctx,invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    app = FastAPI()
    app.include_router(admin_router.router,prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda:ctx.db
    app.dependency_overrides[get_current_user] = lambda:{"sub":"1"}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://ark.example.com") as client:
            path = "/api/portal/admin/v1/orders/"+order.public_id+"/void-pi"
            command = body(invoice).model_dump(mode="json")
            assert (await client.post(path,json=command)).status_code == 428
            version = f'"{order.row_version}"'
            first = await client.post(path,json=command,headers={"If-Match":version})
            assert first.status_code == 200 and first.json()["data"]["invoice_status"] == "cancelled"
            replay = await client.post(path,json=command,headers={"If-Match":version})
            assert replay.status_code == 200 and replay.json()["data"]["replayed"]
            assert replay.json()["data"]["original_receipt"] == first.json()["data"]["original_receipt"]
    asyncio.run(scenario())
