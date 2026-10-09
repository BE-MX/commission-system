from types import SimpleNamespace
from decimal import Decimal
import pytest
from sqlalchemy import select
from test_proposal_decisions import proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, propose, decision
from app.portal import invoice_adapter as adapter
from app.portal.models import OrderRequest, Revision, RequestLine
from app.portal.errors import PortalError
from app.invoice import service as invoices


@pytest.fixture
def accepted(proposing):
    ctx, result = proposing
    proposal = propose(ctx, result)
    decision(ctx, result, proposal)
    order = ctx.db.scalar(select(OrderRequest))
    revision = ctx.db.get(Revision, order.accepted_revision_id)
    records = ctx.db.scalars(select(RequestLine).where(RequestLine.revision_id == revision.id).order_by(RequestLine.id)).all()
    return ctx, order, revision, records


def test_payload_uses_bound_customer_standard_sku_and_full_fees(accepted):
    ctx, order, revision, records = accepted
    body = adapter.payload(order, ctx.access, revision, records, customer_name="Confirmed Company")
    assert body.source_type == "portal" and body.source_order_id == order.public_id
    assert body.customer_id == ctx.access.okki_company_id and body.sales_user_id == order.servicing_user_id
    assert body.items[0].model == records[0].standard_json["model"]
    assert body.items[0].color == records[0].standard_json["color"]
    assert body.shipping_fee == Decimal("45") and body.internal_accessory == Decimal("2")
    assert body.packaging_quantity == 0 and body.internal_received is None
    assert body.payment_term == revision.payment_terms_snapshot["display_text"]
    assert "\n" in body.delivery_address


def test_invoice_owner_is_accepted_proposal_not_original_submission(accepted):
    ctx, order, revision, records = accepted
    from app.portal.models import CustomerAccess
    order = SimpleNamespace(**{column.name:getattr(order, column.name) for column in OrderRequest.__table__.columns})
    access = SimpleNamespace(**{column.name:getattr(ctx.access, column.name) for column in CustomerAccess.__table__.columns})
    assert revision.authority_versions_json["sales_user_id"] == 1
    order.sales_user_id_snapshot = 999  # Historical attribution must not drive conversion.
    body = adapter.payload(order, access, revision, records, customer_name="Company")
    assert body.sales_user_id == 1
    order.servicing_user_id = access.sales_user_id = 2
    with pytest.raises(PortalError) as caught:
        adapter.payload(order, access, revision, records, customer_name="Company")
    assert caught.value.code == "CUSTOMER_BINDING_CHANGED"


@pytest.mark.parametrize("change", ["acceptance", "identity", "owner"])
def test_payload_rejects_unaccepted_or_rebound_request(accepted, change):
    ctx, order, revision, records = accepted
    if change == "acceptance":
        order.accepted_revision_id = None
    elif change == "identity":
        ctx.access.okki_company_id = "987654321"
    else:
        order.servicing_user_id = 2
    with pytest.raises(PortalError):
        adapter.payload(order, ctx.access, revision, records, customer_name="Company")


@pytest.mark.parametrize("drift", ["amount", "standard", "sku"])
def test_existing_invoice_money_algorithm_matches_snapshot(accepted, monkeypatch, drift):
    from app.invoice.models import Invoice
    ctx, order, revision, records = accepted
    body = adapter.payload(order, ctx.access, revision, records, customer_name="Company")
    invoice = Invoice(sync_status="not_synced", **{field:getattr(body, field) for field in invoices._HEADER_FIELDS},
                      **{field:getattr(body, field) for field in invoices._SOURCE_FIELDS},
                      sales_user_id=body.sales_user_id, currency=body.currency, order_type=body.order_type)
    monkeypatch.setattr(invoices.product_service, "valid_okki_product_skus", lambda db, pairs: pairs)
    monkeypatch.setattr(invoices.price_service, "resolve_price", lambda *args, **kwargs: {"standard_price": Decimal("27"), "customer_price": Decimal("27"), "currency": "USD"})
    invoices._replace_items(ctx.db, invoice, body)
    invoices._refresh_invoice_totals(invoice)
    adapter.verify_invoice(invoice, body, revision, records)
    if drift == "amount":
        invoice.total_amount += Decimal("0.01")
    elif drift == "standard":
        invoice.items[0].color = "Another standard color"
    else:
        invoice.items[0].sku_id += 1
    with pytest.raises(PortalError) as caught:
        adapter.verify_invoice(invoice, body, revision, records)
    assert caught.value.code == ("INVOICE_AMOUNT_MISMATCH" if drift == "amount" else "INVOICE_SNAPSHOT_MISMATCH")


def test_generic_create_cannot_forge_portal_source(accepted):
    ctx, order, revision, records = accepted
    body = adapter.payload(order, ctx.access, revision, records, customer_name="Company")
    with pytest.raises(ValueError, match="门户来源"):
        invoices.create_invoice(None, body, 1)
    with pytest.raises(ValueError, match="授权冲突"):
        invoices.create_invoice(None, body, 1, allow_portal_source=True, allow_external_source=True)
    with pytest.raises(ValueError, match="不允许删除"):
        invoices.delete_invoice(None, SimpleNamespace(source_type="portal"))
    invoices._validate_screenshot_source(None, SimpleNamespace(**body.model_dump()))
    body.source_order_id = "invalid"
    with pytest.raises(ValueError, match="有效订单"):
        invoices._validate_screenshot_source(None, SimpleNamespace(**body.model_dump()))




def test_accessory_slash_name_survives_existing_invoice_projection(accepted, monkeypatch):
    from copy import deepcopy
    from app.invoice.models import Invoice
    from app.portal import revision_evidence
    ctx, order, revision, records = accepted
    revision = SimpleNamespace(**{column.name: deepcopy(getattr(revision, column.name)) for column in Revision.__table__.columns})
    records = [SimpleNamespace(**{column.name: deepcopy(getattr(row, column.name)) for column in RequestLine.__table__.columns}) for row in records]
    record = records[0]
    record.product_kind = "accessory"
    record.standard_json.update(product_name="Tape / replacement", product_display="Tape / replacement", model="Tape", color="Clear", length="", weight="")
    revision.content_hash = revision_evidence.digest(revision, records)
    body = adapter.payload(order, ctx.access, revision, records, customer_name="Company")
    invoice = Invoice(sync_status="not_synced", **{field:getattr(body, field) for field in invoices._HEADER_FIELDS},
                      **{field:getattr(body, field) for field in invoices._SOURCE_FIELDS},
                      sales_user_id=body.sales_user_id, currency=body.currency, order_type=body.order_type)
    monkeypatch.setattr(invoices.product_service, "valid_okki_product_skus", lambda db, pairs: pairs)
    monkeypatch.setattr(invoices.accessory_price_service, "resolve_configured_price", lambda *args, **kwargs: {
        "standard_price": record.unit_price, "customer_price": record.unit_price, "currency": "USD",
        "accessory_name": "Tape / replacement", "accessory_model": "Tape", "accessory_color": "Clear"})
    invoices._replace_items(ctx.db, invoice, body)
    invoices._refresh_invoice_totals(invoice)
    adapter.verify_invoice(invoice, body, revision, records)
