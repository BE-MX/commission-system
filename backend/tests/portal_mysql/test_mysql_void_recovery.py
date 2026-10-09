"""Local PI tombstones and receipts survive response loss without duplicate effects."""
import pytest
from sqlalchemy import Column, MetaData, Table, select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth import admin_router as employee_admin
from app.auth.admin_schemas import UserUpdateRequest
from app.invoice.models import Invoice, InvoiceSyncLog, OkkiOutboundTask
from app.receipt.models import Receipt, ReceiptIntent
from app.semifinished.models import InvoiceAllocation
from app.shipping_inspection.models import ShippingOperationEvent
from app.portal import approval_service, pi_void_service, pi_service
from app.portal.errors import PortalError
from app.portal.models import OrderRequest, Revision, Conversion, Publication, PiAmendment, CommandReceipt, AuditEvent, OutboxEvent
from app.portal.schemas import VoidPiInput, ApproveInput
from test_mysql_services import accepted_request, count


def test_void_commit_loss_replay_conflict_and_revocation(trade):
    ctx = trade
    metadata = MetaData()
    for model in (Receipt, InvoiceAllocation, ShippingOperationEvent, OkkiOutboundTask, InvoiceSyncLog):
        Table(model.__tablename__, metadata, *(Column(c.name, c.type, primary_key=c.primary_key,
            nullable=c.nullable, default=c.default, server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine)
    request_id, accepted = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.execute(db, ctx.actor, request_id, 3, accepted)
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice_id = order.invoice_id
        command = VoidPiInput(invoice_document_version=1, reason='Customer cancelled before fulfillment')
        with pytest.raises(ConnectionError, match='lost after commit'):
            original = pi_void_service.void(db, ctx.actor, request_id, 4, command)
            db.commit()
            raise ConnectionError('Test response lost after commit')
    models = (Invoice, InvoiceSyncLog, ReceiptIntent, OrderRequest, Revision, Conversion, Publication,
        PiAmendment, CommandReceipt, AuditEvent, OutboxEvent)
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all()) for model in models)
    baseline = snapshot()
    with Session(ctx.engine) as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice.status == 'cancelled' and invoice.portal_document_version == 2
        conversion = db.scalar(select(Conversion).where(Conversion.invoice_id == invoice_id))
        assert conversion.status == 'tombstoned'
        assert db.scalar(select(Publication).where(Publication.invoice_id == invoice_id)).status == 'withdrawn'
        assert count(db, CommandReceipt, (CommandReceipt.object_public_id == request_id) & (CommandReceipt.action == 'pi_voided')) == 1
        assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id) & (AuditEvent.action == 'order.pi_voided')) == 1
        assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == request_id) & (OutboxEvent.event_type == 'order_pi_voided')) == 1
        for expected in (4, 5):
            replay = pi_void_service.void(db, ctx.actor, request_id, expected, command)
            db.commit()
            assert replay == {**original, 'replayed':True}
        for changed in (command.model_copy(update={'reason':'Different cancellation rationale'}),
                        command.model_copy(update={'invoice_document_version':2})):
            with pytest.raises(PortalError) as error:
                pi_void_service.void(db, ctx.actor, request_id, 5, changed)
            assert error.value.code == 'IDEMPOTENCY_CONFLICT' and error.value.status == 409
            db.rollback()
        with pytest.raises(ValueError, match='lineage'):
            db.delete(db.get(Invoice, invoice_id)); db.flush()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(delete(Conversion).where(Conversion.invoice_id == invoice_id)); db.commit()
        db.rollback()
        prior_approval = approval_service.approve(db, ctx.actor, request_id, 5, accepted)
        assert prior_approval['replayed'] and prior_approval['original_receipt']['invoice_id'] == invoice_id
        initial = db.scalar(select(Revision).join(OrderRequest, Revision.request_id == OrderRequest.id)
            .where(OrderRequest.public_id == request_id, Revision.kind == 'submitted'))
        with pytest.raises(PortalError) as error:
            approval_service.approve(db, ctx.actor, request_id, 5, ApproveInput(accepted_revision_id=initial.public_id))
        assert error.value.code == 'INVOICE_ALREADY_CREATED'
        db.rollback()
        with pytest.raises(PortalError):
            pi_service.capture(db, ctx.token, request_id)
        db.rollback()
    assert snapshot() == baseline
    with Session(ctx.engine) as db:
        employee_admin.update_user(ctx.actor, UserUpdateRequest(is_active=False), db, {'sub':str(ctx.admin)})
    after_revocation = snapshot()
    with Session(ctx.engine) as db:
        with pytest.raises(PortalError) as error:
            pi_void_service.void(db, ctx.actor, request_id, 4, command)
        assert error.value.status == 403
        db.rollback()
    assert snapshot() == after_revocation