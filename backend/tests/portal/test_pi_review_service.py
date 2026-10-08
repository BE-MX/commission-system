import pytest
from sqlalchemy import select, func, update
from app.invoice.models import Invoice
from app.portal import pi_review_service as service
from app.portal.errors import PortalError
from app.portal.models import OrderRequest, Revision
from test_pi_void import published, approving, accepted, proposing, submitted, submission, quoting, priced_catalog, catalog, managed, auth_context, portal_metadata, body
from test_pi_amendments import edited, propose, accept


def test_review_current_pi_has_both_identity_and_complete_live_document(published):
    ctx, invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    result = service.context(ctx.db, 1, order.public_id)
    assert result['available_actions'] == ['void_pi']
    assert result['customer']['company_name'] == 'Buyer Company'
    assert result['customer']['invoice_sales_user_id'] == str(invoice.sales_user_id)
    assert result['current_invoice']['commercial_header']['invoice_no'] == invoice.invoice_no
    assert result['current_invoice']['delivery']['formatted_address'] == invoice.delivery_address
    assert result['current_invoice']['items'][0]['sku_id'] is not None


def test_edited_live_pi_never_presented_as_last_published(edited):
    ctx, invoice, order = edited
    result = service.context(ctx.db, 1, order.public_id)
    assert result['amendment_status'] == 'withdrawn'
    assert set(result['available_actions']) == {'propose_pi','void_pi'}
    assert result['current_invoice']['total_amount'] == '133.00'
    assert result['last_published']['total_amount'] == '128.00'
    assert result['invoice_document_version'] == 2
    assert result['last_published']['invoice_document_version'] == 1
    assert ctx.db.scalar(select(func.count()).select_from(Invoice)) == 1


def test_only_unexpired_customer_accepted_pi_proposal_can_be_published(edited, monkeypatch):
    ctx, invoice, order = edited
    _, proposal = propose(ctx, invoice, order)
    assert service.context(ctx.db, 1, order.public_id)['available_actions'] == ['void_pi']
    accept(ctx, order, proposal)
    result = service.context(ctx.db, 1, order.public_id)
    assert 'publish_pi' in result['available_actions']
    assert result['proposal']['revision_id'] == proposal['original_receipt']['revision_id']
    revision = ctx.db.scalar(select(Revision).where(Revision.public_id == result['proposal']['revision_id']))
    monkeypatch.setattr(service, 'beijing_now', lambda: revision.expires_at)
    actions = service.context(ctx.db, 1, order.public_id)['available_actions']
    assert 'publish_pi' not in actions and 'propose_pi' in actions


def test_remote_fulfillment_blocks_void_hint_with_reason(published):
    ctx, invoice = published
    invoice.xiaoman_order_id = 'remote-1'
    ctx.db.commit()
    result = service.context(ctx.db, 1, ctx.db.scalar(select(OrderRequest)).public_id)
    assert 'void_pi' not in result['available_actions']
    assert result['blocked_reasons'][0]['code'] == 'PI_VOID_REQUIRES_REVIEW'


def test_other_salesperson_cannot_get_pi_review(published):
    ctx, invoice = published
    with pytest.raises(PortalError) as caught:
        service.context(ctx.db, 2, ctx.db.scalar(select(OrderRequest)).public_id)
    assert caught.value.status == 404


def test_read_context_works_without_inventory_and_writes_disabled(edited):
    ctx, invoice, order = edited
    ctx.observations = {}
    ctx.settings.PORTAL_WRITES_ENABLED = False
    result = service.context(ctx.db, 1, order.public_id)
    assert result['available_actions'] == []
    assert result['current_invoice']['total_amount'] == '133.00'


def test_current_header_changes_do_not_rewrite_published_header(edited):
    ctx, invoice, order = edited
    original_name = invoice.customer_name
    invoice.customer_name = "Updated PI buyer name"
    ctx.db.commit()
    result = service.context(ctx.db, 1, order.public_id)
    assert result['current_invoice']['commercial_header']['customer_name'] == 'Updated PI buyer name'
    assert result['last_published']['commercial_header']['customer_name'] == original_name


def test_published_header_integrity_is_checked(published):
    from app.portal.models import Publication
    ctx, invoice = published
    publication = ctx.db.scalar(select(Publication))
    corrupted = {**publication.customer_snapshot_json, 'commercial_header': {'customer_name': 'Tampered'}}
    # Simulate storage corruption beneath the ORM immutability guard in isolated SQLite.
    ctx.db.execute(update(Publication.__table__).where(Publication.id == publication.id).values(customer_snapshot_json=corrupted))
    ctx.db.commit()
    ctx.db.expire_all()
    with pytest.raises(PortalError) as caught:
        service.context(ctx.db, 1, ctx.db.scalar(select(OrderRequest)).public_id)
    assert caught.value.code == 'PI_REVISION_PENDING'
