from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from test_portal_invoice_lifecycle import published, approving, accepted, proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context
from app.invoice.models import Invoice, InvoiceItem, CustomerPriceRule
from app.portal import pi_amendment_service as service, pi_revision_source, pi_service, order_queries, proposal_decisions
from app.portal.errors import PortalError
from app.portal.models import OrderRequest, Revision, Publication, Conversion, PiAmendment
from app.portal.schemas import AcceptInput, PiProposalInput, PublishPiInput, ReasonInput


@pytest.fixture
def edited(published, monkeypatch):
    ctx, invoice = published
    monkeypatch.setattr(pi_revision_source,"get_settings",lambda:ctx.settings)
    monkeypatch.setattr(order_queries,"get_settings",lambda:ctx.settings)
    invoice.shipping_fee += Decimal("5.00")
    invoice.total_amount += Decimal("5.00")
    ctx.db.commit()
    return ctx, invoice, ctx.db.scalar(select(OrderRequest))


def propose(ctx, invoice, order, **values):
    body = PiProposalInput(invoice_document_version=invoice.portal_document_version,reason="Updated freight",**values)
    result = service.create(ctx.db,1,order.public_id,order.row_version,body)
    ctx.db.commit()
    return body,result


def accept(ctx,order,result):
    receipt = result["original_receipt"]
    body = AcceptInput(proposal_hash=receipt["content_hash"])
    response = proposal_decisions.decide(ctx.db,ctx.session_token,ctx.session_csrf,order.public_id,
        receipt["revision_id"],order.row_version,body,accept=True)
    ctx.db.commit()
    return response


def publish(ctx,invoice,order,result):
    body = PublishPiInput(invoice_document_version=invoice.portal_document_version,
        accepted_revision_id=result["original_receipt"]["revision_id"])
    response = service.publish(ctx.db,1,order.public_id,order.row_version,body)
    ctx.db.commit()
    return body,response


def test_pi_edit_confirm_publish_is_same_invoice_and_idempotent(edited):
    ctx,invoice,order = edited
    original_version = order.row_version
    body,proposal = propose(ctx,invoice,order)
    detail = order_queries.customer_detail(ctx.db,ctx.session_token,order.public_id)
    pi = detail["pi_amendment"]
    assert order.status == "invoice_created" and pi["status"] == "pending_customer"
    assert "accept_pi" in detail["available_actions"]
    assert pi["proposal"]["shipping_amount"] == "50.00"
    assert pi["proposal"]["changes"]["fields"][0]["field"] == "shipping_amount"
    with pytest.raises(PortalError):
        pi_service.capture(ctx.db,ctx.session_token,order.public_id)
    ctx.db.rollback()
    replay = service.create(ctx.db,1,order.public_id,original_version,body)
    assert replay["replayed"] and replay["original_receipt"] == proposal["original_receipt"]
    accept(ctx,order,proposal)
    accepted_version = order.row_version
    pub_body,result = publish(ctx,invoice,order,proposal)
    assert result["amendment_state"] == "current"
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(Conversion)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(Publication)) == 2
    _,ticket,snapshot = pi_service.capture(ctx.db,ctx.session_token,order.public_id)
    assert ticket["invoice_document_version"] == 2 and snapshot["total_amount"] == "133.00"
    assert snapshot["fees"]["shipping_amount"] == "50.00"
    detail = order_queries.customer_detail(ctx.db,ctx.session_token,order.public_id)
    assert detail["total_amount"] == "133.00" and "download_pi" in detail["available_actions"]
    assert service.publish(ctx.db,1,order.public_id,accepted_version,pub_body)["replayed"]


@pytest.mark.parametrize("failure",["payment","inventory","sku","amount","cancelled","unaccepted"])
def test_invalid_pi_never_becomes_publishable(edited,failure):
    ctx,invoice,order = edited
    if failure == "payment":
        invoice.payment_term = "Unknown unconfigured credit promise"
    elif failure == "inventory":
        ctx.observations = {}
    elif failure == "sku":
        invoice.items[0].color = "wrong color for SKU"
    elif failure == "amount":
        invoice.total_amount += 1
    elif failure == "cancelled":
        invoice.status = "cancelled"
    ctx.db.commit()
    if failure == "unaccepted":
        _,proposal = propose(ctx,invoice,order)
        with pytest.raises(PortalError) as caught:
            publish(ctx,invoice,order,proposal)
        assert caught.value.code == "CUSTOMER_ACCEPTANCE_REQUIRED"
    else:
        with pytest.raises(PortalError):
            propose(ctx,invoice,order)
    ctx.db.rollback()
    assert ctx.db.scalar(select(func.count()).select_from(Publication)) == 1


def test_actual_invoice_price_and_address_are_preserved_not_requoted(edited,monkeypatch):
    ctx,invoice,order = edited
    invoice.items[0].price_per_piece = Decimal("25.1234")
    invoice.items[0].discount_amount = Decimal("-1")
    invoice.items[0].total_price = Decimal("74.37")
    invoice.product_amount = Decimal("74.37")
    invoice.total_amount = Decimal("126.37")
    invoice.delivery_address = "Floor 7 / Updated Road\nNew destination"
    ctx.db.get(CustomerPriceRule,1).adjust_value = 20
    ctx.db.commit()
    _,proposal = propose(ctx,invoice,order)
    revision = ctx.db.scalar(select(Revision).where(Revision.public_id==proposal["original_receipt"]["revision_id"]))
    assert revision.delivery_json["formatted_address"] == invoice.delivery_address
    accept(ctx,order,proposal)
    publish(ctx,invoice,order,proposal)
    _,_,snapshot = pi_service.capture(ctx.db,ctx.session_token,order.public_id)
    assert snapshot["items"][0]["unit_price"] == "25.1234"
    assert snapshot["items"][0]["discount_amount"] == "-1.00"
    assert snapshot["total_amount"] == "126.37"
    from io import BytesIO
    from pathlib import Path
    from types import SimpleNamespace
    import reportlab
    from pypdf import PdfReader
    from app.portal import pi_pdf
    monkeypatch.setattr(pi_pdf,"get_settings",lambda:SimpleNamespace(
        PDF_CJK_FONT_PATH=str(Path(reportlab.__file__).parent/"fonts"/"Vera.ttf")))
    rendered = " ".join(page.extract_text() for page in PdfReader(BytesIO(pi_pdf.render(snapshot))).pages)
    assert "Floor 7 / Updated Road" in rendered and "New destination" in rendered


@pytest.mark.parametrize("moment",["before_accept","before_publish"])
def test_bulk_drift_rejects_stale_acceptance(edited,moment):
    ctx,invoice,order = edited
    _,proposal = propose(ctx,invoice,order)
    if moment == "before_publish":
        accept(ctx,order,proposal)
    ctx.db.execute(update(Invoice).where(Invoice.id==invoice.id).values(remark="Unversioned edit"))
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        accept(ctx,order,proposal) if moment == "before_accept" else publish(ctx,invoice,order,proposal)
    assert caught.value.code == "PROPOSAL_CHANGED"
    ctx.db.rollback()
    assert order_queries.customer_detail(ctx.db,ctx.session_token,order.public_id)["pi_amendment"]["status"] == "withdrawn"


def test_old_success_replay_never_republishes_after_later_edit(edited):
    ctx,invoice,order = edited
    _,proposal = propose(ctx,invoice,order)
    accept(ctx,order,proposal)
    expected = order.row_version
    body,_ = publish(ctx,invoice,order,proposal)
    invoice.remark = "Another revision"
    ctx.db.commit()
    ctx.observations = {}
    replay = service.publish(ctx.db,1,order.public_id,expected,body)
    assert replay["replayed"] and replay["amendment_state"] == "withdrawn"
    assert ctx.db.scalar(select(func.count()).select_from(Publication).where(Publication.status=="published")) == 0


def test_customer_scope_capability_and_employee_scope(edited):
    ctx,invoice,order = edited
    _,proposal = propose(ctx,invoice,order)
    with pytest.raises(PortalError) as caught:
        service.create(ctx.db,2,order.public_id,order.row_version,PiProposalInput(invoice_document_version=2,reason="Wrong employee"))
    assert caught.value.status == 404
    ctx.db.rollback()
    ctx.access.can_order = False
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        accept(ctx,order,proposal)
    assert caught.value.status == 403


def test_reject_and_reproposal_preserve_invoice_and_old_evidence(edited):
    ctx,invoice,order = edited
    _,proposal = propose(ctx,invoice,order)
    revision_id = proposal["original_receipt"]["revision_id"]
    response = service.decide(ctx.db,ctx.session_token,ctx.session_csrf,order.public_id,revision_id,
        order.row_version,ReasonInput(reason="Please revise"),accept=False)
    ctx.db.commit()
    assert response["amendment_state"] == "withdrawn"
    _,second = propose(ctx,invoice,order)
    assert second["original_receipt"]["revision_id"] != revision_id
    assert order.status == "invoice_created"


def test_proposal_and_publication_rollback_leave_no_partial_state(edited):
    ctx,invoice,order = edited
    count = ctx.db.scalar(select(func.count()).select_from(Revision))
    version = order.row_version
    body = PiProposalInput(invoice_document_version=invoice.portal_document_version,reason="Review")
    service.create(ctx.db,1,order.public_id,version,body)
    ctx.db.rollback()
    assert order.row_version == version
    assert ctx.db.scalar(select(func.count()).select_from(Revision)) == count
    assert ctx.db.scalar(select(PiAmendment)).status == "withdrawn"
    _,proposal = propose(ctx,invoice,order)
    accept(ctx,order,proposal)
    version = order.row_version
    body = PublishPiInput(invoice_document_version=invoice.portal_document_version,accepted_revision_id=proposal["original_receipt"]["revision_id"])
    service.publish(ctx.db,1,order.public_id,version,body)
    ctx.db.rollback()
    assert order.row_version == version
    assert ctx.db.scalar(select(PiAmendment)).status == "accepted"
    assert ctx.db.scalar(select(func.count()).select_from(Publication)) == 1


@pytest.mark.parametrize("already_accepted",[False,True])
def test_expired_pi_proposal_must_be_replaced_not_extended(edited,monkeypatch,already_accepted):
    ctx,invoice,order = edited
    _,proposal = propose(ctx,invoice,order)
    if already_accepted:
        accept(ctx,order,proposal)
    revision = ctx.db.scalar(select(Revision).where(Revision.public_id==proposal["original_receipt"]["revision_id"]))
    expiry = revision.expires_at
    monkeypatch.setattr(service,"beijing_now",lambda:expiry)
    monkeypatch.setattr(pi_revision_source,"beijing_now",lambda:expiry)
    with pytest.raises(PortalError):
        publish(ctx,invoice,order,proposal) if already_accepted else accept(ctx,order,proposal)
    ctx.db.rollback()
    from app.portal.inventory import InventoryObservation
    ctx.observations = {key:InventoryObservation(value.quantity,value.unit,expiry,value.source) for key,value in ctx.observations.items()}
    _,new = propose(ctx,invoice,order)
    assert new["original_receipt"]["revision_id"] != revision.public_id
    assert revision.expires_at == expiry
    assert ctx.db.scalar(select(PiAmendment)).accepted_revision_id is None


def test_customer_without_price_sees_no_pi_amendment_money(edited):
    ctx,invoice,order = edited
    propose(ctx,invoice,order)
    ctx.access.can_view_price = ctx.access.can_order = False
    ctx.db.commit()
    detail = order_queries.customer_detail(ctx.db,ctx.session_token,order.public_id)
    assert "pi_amendment" not in detail and "total_amount" not in detail
    assert "unit_price" not in detail["items"][0]


@pytest.mark.parametrize("source",["customer","catalog","configuration"])
def test_pi_source_namespace_mismatch_rejected_before_inventory_reads(edited,monkeypatch,source):
    ctx,invoice,order = edited
    if source == "customer":
        ctx.access.okki_namespace = "okki:other"
    elif source == "catalog":
        ctx.items[0].source_namespace = "okki:other"
    else:
        ctx.settings.PORTAL_OKKI_NAMESPACE = "okki:other"
    ctx.db.commit()
    from app.portal import catalog_service
    def unexpected(*args):
        raise AssertionError("Inventory must not be read across namespaces")
    monkeypatch.setattr(catalog_service,"load_observations",unexpected)
    with pytest.raises(PortalError) as caught:
        pi_revision_source.build(ctx.db,ctx.access,ctx.site,order,invoice,invoice.items,actor_id=1,valid_for_hours=24)
    assert caught.value.code == "SKU_UNAVAILABLE"


def test_http_pi_proposal_accept_and_publish(edited,monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal import router as customer_http, admin_router
    ctx,invoice,order = edited
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(customer_http,"get_settings",lambda:ctx.settings)
    app = FastAPI()
    app.include_router(customer_http.router,prefix="/api/portal/v1")
    app.include_router(admin_router.router,prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda:ctx.db
    app.dependency_overrides[get_current_user] = lambda:{"sub":"1"}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ctx.settings.PORTAL_ORIGIN,
                headers={"X-Real-IP":"203.0.113.1","Origin":ctx.settings.PORTAL_ORIGIN,"X-Portal-CSRF":ctx.session_csrf}) as client:
            admin = "/api/portal/admin/v1/orders/"+order.public_id
            body = {"invoice_document_version":invoice.portal_document_version,"reason":"Updated freight"}
            assert (await client.post(admin+"/pi-proposals",json=body)).status_code == 428
            response = await client.post(admin+"/pi-proposals",json=body,headers={"If-Match":f'"{order.row_version}"'})
            assert response.status_code == 200
            receipt = response.json()["data"]["original_receipt"]
            client.cookies.set("__Host-portal_session",ctx.session_token)
            response = await client.post("/api/portal/v1/orders/"+order.public_id+"/proposals/"+receipt["revision_id"]+"/accept",
                json={"proposal_hash":receipt["content_hash"]},headers={"If-Match":f'"{order.row_version}"'})
            assert response.status_code == 200 and response.json()["data"]["amendment_state"] == "accepted"
            response = await client.post(admin+"/publish-pi",json={"invoice_document_version":invoice.portal_document_version,
                "accepted_revision_id":receipt["revision_id"]},headers={"If-Match":f'"{order.row_version}"'})
            assert response.status_code == 200 and response.json()["data"]["amendment_state"] == "current"
    asyncio.run(scenario())


def test_commercial_header_change_is_visible_hashed_and_published_from_acceptance(edited):
    from datetime import timedelta
    ctx,invoice,order = edited
    baseline = ctx.db.scalar(select(Publication)).customer_snapshot_json["commercial_header"]
    invoice.customer_name = "Updated Buyer Company"
    invoice.invoice_no = "PI-REVISED-HEADER"
    invoice.invoice_date += timedelta(days=1)
    invoice.express_channel = "DHL Express"
    invoice.contact_email = "buyer@example.com"
    invoice.sales_user_name = "April"
    invoice.sales_phone = "+44 12345"
    invoice.sales_email = "april@example.com"
    invoice.packaging_quantity = 2
    ctx.db.commit()
    _,proposal = propose(ctx,invoice,order)
    detail = order_queries.customer_detail(ctx.db,ctx.session_token,order.public_id)["pi_amendment"]["proposal"]
    header = detail["commercial_header"]
    assert header["customer_name"] == "Updated Buyer Company"
    assert header["invoice_no"] == "PI-REVISED-HEADER" and header["express_channel"] == "DHL Express"
    changes = {row["field"]:row for row in detail["changes"]["fields"]}
    assert changes["commercial_header"]["before"] == baseline
    assert changes["commercial_header"]["after"] == header
    accept(ctx,order,proposal)
    publish(ctx,invoice,order,proposal)
    _,_,snapshot = pi_service.capture(ctx.db,ctx.session_token,order.public_id)
    assert snapshot["commercial_header"] == header
    assert snapshot["invoice_no"] == header["invoice_no"]
    revision = ctx.db.scalar(select(Revision).where(Revision.public_id==proposal["original_receipt"]["revision_id"]))
    revision.invoice_presentation_json = {**header,"customer_name":"Tampered"}
    with pytest.raises(ValueError,match="immutable"):
        ctx.db.flush()
    ctx.db.rollback()


def test_unversioned_commercial_header_evidence_tampering_rejected(edited):
    ctx,invoice,order = edited
    _,proposal = propose(ctx,invoice,order)
    ctx.db.execute(update(Revision).where(Revision.public_id==proposal["original_receipt"]["revision_id"])
        .values(invoice_presentation_json={"customer_name":"Another company"}))
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        accept(ctx,order,proposal)
    assert caught.value.code == "ORDER_UNAVAILABLE"
