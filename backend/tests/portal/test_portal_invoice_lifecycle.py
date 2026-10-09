import pytest
from sqlalchemy import func, select, update
from test_approval_service import approving, accepted, proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, approve
from app.invoice.models import Invoice, InvoiceItem
from app.portal.models import Publication, PiAmendment, Conversion, AuditEvent


@pytest.fixture
def published(approving):
    ctx, order, revision, records = approving
    approve(ctx, order, revision)
    return ctx, ctx.db.get(Invoice, order.invoice_id)


@pytest.mark.parametrize("mutation", ["header", "line", "cancel", "remove_line"])
def test_customer_visible_change_withdraws_same_transaction(published, mutation):
    ctx, invoice = published
    before = invoice.portal_document_version
    if mutation == "header":
        invoice.remark = "Changed delivery instructions"
    elif mutation == "line":
        invoice.items[0].color = "Changed standard color"
    elif mutation == "cancel":
        invoice.status = "cancel_pending"
    else:
        invoice.items.pop()
    ctx.db.flush()
    assert invoice.portal_document_version == before + 1
    assert ctx.db.scalar(select(Publication)).status == "withdrawn"
    amendment = ctx.db.scalar(select(PiAmendment))
    assert amendment.status == "withdrawn" and amendment.accepted_revision_id is None
    assert amendment.active_revision_id is None
    assert ctx.db.scalar(select(Conversion)).status == "created"
    ctx.db.rollback()
    assert invoice.portal_document_version == before
    assert ctx.db.scalar(select(Publication)).status == "published"
    assert ctx.db.scalar(select(PiAmendment)).accepted_revision_id is not None


def test_sync_metadata_does_not_revoke_customer_document(published):
    ctx, invoice = published
    before = invoice.portal_document_version
    invoice.xiaoman_order_id = "remote-order-1"
    invoice.sync_status = "synced"
    invoice.status = "synced"
    invoice.items[0].xiaoman_unique_id = "remote-line-1"
    ctx.db.commit()
    assert invoice.portal_document_version == before
    assert ctx.db.scalar(select(Publication)).status == "published"


@pytest.mark.parametrize("operation", ["source", "delete", "version"])
def test_direct_orm_cannot_retag_delete_or_forge_portal_version(published, operation):
    ctx, invoice = published
    if operation == "source":
        invoice.source_type = "manual"
    elif operation == "delete":
        ctx.db.delete(invoice)
    else:
        invoice.portal_document_version += 1
    with pytest.raises(ValueError):
        ctx.db.flush()
    ctx.db.rollback()
    assert ctx.db.scalar(select(Publication)).status == "published"


def test_stale_entity_cannot_overwrite_new_document_version(published):
    ctx, invoice = published
    before = invoice.portal_document_version
    ctx.db.execute(update(Invoice).where(Invoice.id == invoice.id).values(
        portal_document_version=before+1).execution_options(synchronize_session=False))
    invoice.remark = "Stale edit"
    with pytest.raises(ValueError, match="concurrently"):
        ctx.db.flush()
    ctx.db.rollback()
    assert invoice.portal_document_version == before


def test_existing_portal_line_cannot_be_moved_to_other_invoice(published):
    from copy import copy
    ctx, invoice = published
    other = Invoice(invoice_no="OTHER", customer_id="1", customer_name="Other", invoice_date=invoice.invoice_date,
        order_type="stock", currency="USD", source_type="manual")
    ctx.db.add(other)
    ctx.db.commit()
    invoice.items[0].invoice = other
    with pytest.raises(ValueError, match="reassigned"):
        ctx.db.flush()
    ctx.db.rollback()
    assert len(invoice.items) == 1 and ctx.db.scalar(select(Publication)).status == "published"


def test_expired_source_attribute_cannot_hide_portal_origin(published):
    ctx, invoice = published
    ctx.db.expire(invoice, ["source_type"])
    invoice.source_type = "manual"
    with pytest.raises(ValueError, match="source identity"):
        ctx.db.flush()
    ctx.db.rollback()
    assert invoice.source_type == "portal"


def test_expired_line_parent_cannot_hide_portal_origin(published):
    ctx, invoice = published
    other = Invoice(invoice_no="OTHER-FK", customer_id="1", customer_name="Other", invoice_date=invoice.invoice_date,
        order_type="stock", currency="USD", source_type="manual")
    ctx.db.add(other)
    ctx.db.commit()
    item = invoice.items[0]
    other_id = other.id
    ctx.db.expire(item, ["invoice_id", "invoice"])
    item.invoice_id = other_id
    with pytest.raises(ValueError, match="reassigned"):
        ctx.db.flush()
    ctx.db.rollback()
    assert item.invoice_id == invoice.id and ctx.db.scalar(select(Publication)).status == "published"


def test_initial_approval_starts_at_version_one_without_withdrawal(published):
    ctx, invoice = published
    assert invoice.portal_document_version == 1
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "invoice.portal_withdrawn")) == 0
