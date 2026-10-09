"""The existing invoice editor participates in portal publication invalidation."""
from uuid import uuid4
import pytest
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session

from app.invoice import service as invoices
from app.invoice.models import Invoice, OkkiOutboundTask, InvoiceLinkedSync
from app.invoice import linked_sync_service as linked
from app.invoice.router import LinkedSavePayload
from app.receipt import remote
from app.invoice.schemas import InvoiceUpdate, InvoiceItemPayload
from app.shipping_inspection.models import ShippingOperationEvent
from app.receipt.models import Receipt
from app.semifinished.models import InvoiceAllocation
from app.portal import approval_service, pi_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, OrderRequest, Publication
from test_mysql_services import accepted_request, compete, count


@pytest.mark.parametrize('entry', ['normal', 'linked'])
@pytest.mark.parametrize('edit_first', [True, False])
def test_existing_invoice_editor_and_pi_capture_serialize(trade, monkeypatch, edit_first, entry):
    ctx = trade
    metadata = MetaData()
    for model in (Receipt, InvoiceAllocation, ShippingOperationEvent, OkkiOutboundTask, InvoiceLinkedSync):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
            nullable=c.nullable, default=c.default, server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine)
    request_id, accepted = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db, ctx.actor, request_id, 3, accepted)
        db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice_id = order.invoice_id
        invoice = invoices.get_invoice(db, invoice_id)
        values = {key: getattr(invoice, key) for key in InvoiceUpdate.model_fields if hasattr(invoice, key) and key != 'items'}
        values['items'] = [{key: getattr(item, key) for key in InvoiceItemPayload.model_fields if hasattr(item, key)}
            for item in invoice.items]
        for item in values['items']:
            item['semifinished_plan'] = item.get('semifinished_plan') or []
        values['remark'] = 'Edited through existing invoice service'
        body = InvoiceUpdate.model_validate(values)
        before = invoice.portal_document_version
        if entry == 'linked':
            # Only the external mirror boundary is synthetic; no remote writes run.
            monkeypatch.setattr(remote, 'order_receipts', lambda *args: [])
            invoice.xiaoman_order_id = 'isolated-' + uuid4().hex
            invoice.sync_status = 'synced'
            db.commit()
        expected_hash = linked.edit_version(invoice)
        assert len(expected_hash) == 64 and int(expected_hash, 16) >= 0
        assert linked.snapshot(invoice)['edit_version'] == expected_hash
    def edit(db):
        invoice = invoices.get_invoice(db, invoice_id, for_update=True)
        if entry == 'linked':
            command = LinkedSavePayload(invoice=body, request_key=uuid4().hex, expected_version='0' * 64)
            with pytest.raises(ValueError, match='刷新'):
                linked.create(db, invoice, command, ctx.actor)
            assert invoice.portal_document_version == before
            command.expected_version = expected_hash
            operation = linked.create(db, invoice, command, ctx.actor)
            assert operation.before['edit_version'] == expected_hash
            assert operation.after['edit_version'] == linked.edit_version(invoice)
            assert operation.after['edit_version'] != expected_hash
        else:
            invoices.update_invoice(db, invoice, body, user_id=ctx.actor)
        return {'edited': True}
    def capture(db):
        _, ticket, snapshot = pi_service.capture(db, ctx.token, request_id)
        return {'version': ticket['invoice_document_version'], 'remark': snapshot['remark']}
    first, second = compete(ctx, edit if edit_first else capture, capture if edit_first else edit)
    if edit_first:
        assert first == {'edited': True}
        assert second == {'error': 'PI_REVISION_PENDING', 'status': 409}
    else:
        assert first['version'] == before and first['remark'] != body.remark
        assert second == {'edited': True}
    with Session(ctx.engine) as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice.remark == body.remark
        assert linked.edit_version(invoice) != expected_hash
        if entry == 'linked':
            operation = db.get(InvoiceLinkedSync, invoice.linked_sync_id)
            assert operation.status == 'pending'
            assert operation.after['edit_version'] == linked.edit_version(invoice)
            assert all(step['status'] == 'pending' for step in operation.steps.values())
        assert invoice.portal_document_version > before
        publication = db.scalar(select(Publication).where(Publication.invoice_id == invoice_id))
        assert publication.status == 'withdrawn'
        assert count(db, AuditEvent, (AuditEvent.action == 'order.pi_downloaded') & (AuditEvent.object_public_id == request_id)) == 0

    if entry == 'linked':
        # Exercise the real runner and coordinator preflight without payment
        # evidence: no external order is sent and the changed PI stays withdrawn.
        with Session(ctx.engine) as db:
            invoice = invoices.get_invoice(db, invoice_id)
            operation_id = invoice.linked_sync_id
            edited_version = invoice.portal_document_version
            result = linked.run(db, operation_id, ctx.actor)
            assert result.status == 'failed'
            assert result.steps['order']['status'] == 'failed'
            assert '回款截图' in result.steps['order']['message']
            assert result.steps['outbound']['status'] == 'pending'
            assert result.steps['receipt']['status'] == 'pending'
            assert invoice.portal_document_version == edited_version
            assert db.scalar(select(Publication).where(Publication.invoice_id == invoice_id)).status == 'withdrawn'
        # Inject an uncertain coordinator result to test the runner's durable
        # recovery policy only; this is not evidence of a real external write.
        from app.invoice import sync_coordinator
        sends = []
        def uncertain(db, invoice, actor, *, linked_id, linked_token):
            linked.ensure_running(db, invoice, linked_id, linked_token)
            sends.append(linked_id)
            return {'ok': False, 'okki_accepted': True, 'message': 'Synthetic remote outcome uncertain'}
        monkeypatch.setattr(sync_coordinator, 'synchronize', uncertain)
        with Session(ctx.engine) as db:
            assert linked.run(db, operation_id, ctx.actor).status == 'uncertain'
        with Session(ctx.engine) as db:
            assert linked.run(db, operation_id, ctx.actor).status == 'uncertain'
            assert sends == [operation_id]
            with pytest.raises(ValueError, match='禁止'):
                linked.close_failed(db, operation_id)
            db.rollback()
            invoice = invoices.get_invoice(db, invoice_id)
            assert invoice.linked_sync_id == operation_id
            assert invoice.portal_document_version == edited_version
            assert db.scalar(select(Publication).where(Publication.invoice_id == invoice_id)).status == 'withdrawn'
            with pytest.raises(PortalError) as error:
                pi_service.capture(db, ctx.token, request_id)
            assert error.value.code == 'PI_REVISION_PENDING'