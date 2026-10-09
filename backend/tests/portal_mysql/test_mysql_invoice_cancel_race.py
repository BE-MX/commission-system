"""Real existing cancellation commits revoke portal PI visibility atomically."""
from uuid import uuid4
import pytest
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session
from app.invoice import cancellation_service as cancellation, linked_sync_service as linked, service as invoices
from app.invoice.models import Invoice, InvoiceSyncLog, OkkiOutboundTask
from app.receipt.models import Receipt
from app.shipping_inspection.models import ShippingOperationEvent
from app.portal import approval_service, pi_service
from app.portal.errors import PortalError
from app.portal.models import OrderRequest, Publication, PiAmendment, Conversion
from test_mysql_services import accepted_request, compete, count


@pytest.mark.parametrize('cancel_first', [True, False])
def test_existing_cancellation_and_pi_capture_serialize(trade, cancel_first):
    ctx = trade
    metadata = MetaData()
    for model in (Receipt, ShippingOperationEvent, OkkiOutboundTask, InvoiceSyncLog):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
            nullable=c.nullable, default=c.default, server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine)
    request_id, accepted = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db, ctx.actor, request_id, 3, accepted)
        db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice_id = order.invoice_id
        invoice = invoices.get_invoice(db, invoice_id, for_update=True)
        invoice.xiaoman_order_id = 'isolated-' + uuid4().hex
        invoice.sync_status = 'synced'
        db.commit()
        before = invoice.portal_document_version
        expected_hash = linked.edit_version(invoice)
        with pytest.raises(ValueError, match='刷新'):
            cancellation.begin(db, invoice, 'Test cancellation rationale', ctx.actor, '0' * 64)
        db.rollback()
        assert invoice.cancellation is None
        assert invoice.portal_document_version == before
        assert count(db, InvoiceSyncLog, InvoiceSyncLog.invoice_id == invoice_id) == 0
    def lock_invoice(db):
        invoices.get_invoice(db, invoice_id, for_update=True)
        return {'locked': True}
    def cancel(db):
        invoice = invoices.get_invoice(db, invoice_id, for_update=True)
        result = cancellation.begin(db, invoice, 'Test cancellation rationale', ctx.actor, expected_hash)
        assert result['status'] == 'pending'
        return {'cancelled': True}
    def capture(db):
        _, ticket, _ = pi_service.capture(db, ctx.token, request_id)
        return {'version': ticket['invoice_document_version']}
    if cancel_first:
        # begin owns commit; acquire its router's invoice lock first, then let the
        # real service commit only once the competing capture is proven waiting.
        first, second = compete(ctx, lock_invoice, capture, finalize=cancel)
        assert first == {'locked': True}
        assert second == {'error': 'PI_REVISION_PENDING', 'status': 409}
    else:
        first, second = compete(ctx, capture, cancel)
        assert first == {'version': before}
        assert second == {'cancelled': True}
    with Session(ctx.engine) as db:
        invoice = invoices.get_invoice(db, invoice_id)
        assert invoice.status == 'cancel_pending'
        assert invoice.portal_document_version == before + 1
        assert invoice.cancellation['created_by'] == ctx.actor
        assert db.scalar(select(Publication).where(Publication.invoice_id == invoice_id)).status == 'withdrawn'
        amendment = db.scalar(select(PiAmendment).where(PiAmendment.invoice_id == invoice_id))
        assert amendment.status == 'withdrawn' and amendment.accepted_revision_id is None
        assert db.scalar(select(Conversion).where(Conversion.invoice_id == invoice_id)).status == 'created'
        logs = db.scalars(select(InvoiceSyncLog).where(InvoiceSyncLog.invoice_id == invoice_id)).all()
        assert len(logs) == 1 and logs[0].action == 'cancel_step' and logs[0].operator_id == ctx.actor
        with pytest.raises(PortalError) as error:
            pi_service.capture(db, ctx.token, request_id)
        assert error.value.code == 'PI_REVISION_PENDING'