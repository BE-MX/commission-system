"""A real invoice validation failure rolls back lineage and permits revised approval."""
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import ReceiptIntent
from app.portal import approval_service, invoice_adapter, proposal_service, proposal_decisions, pi_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, Conversion, OrderRequest, Publication, PiAmendment, OutboxEvent, CommandReceipt
from app.portal.schemas import ProposalInput, ApproveInput, AcceptInput
from test_mysql_services import accepted_request, count


def test_failed_invoice_validation_can_repair_reconfirm_and_create_once(trade, monkeypatch):
    ctx = trade
    request_id, accepted = accepted_request(ctx)
    models = (Invoice, InvoiceItem, ReceiptIntent, Conversion, Publication, PiAmendment, OutboxEvent, CommandReceipt)
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all()) for model in models)
    baseline = snapshot()
    with Session(ctx.engine) as db:
        audit_before = tuple(db.execute(select(*AuditEvent.__table__.columns).order_by(AuditEvent.id)).all())
    real_validate = invoice_adapter.invoices.validate_invoice
    attempted, validation_calls = [], []
    def missing_length(invoice):
        validation_calls.append(invoice.id)
        if len(validation_calls) == 1:
            return real_validate(invoice)  # Existing create_invoice readiness validation.
        # Fault injection at the domain validation boundary, after real creation
        # has flushed. The production validator itself is still executed.
        assert invoice.id is not None and invoice.items
        invoice.items[0].length = None
        issues = real_validate(invoice)
        assert any(issue['field'].endswith('.length') for issue in issues)
        attempted.append(invoice.id)
        return issues
    monkeypatch.setattr(invoice_adapter.invoices, 'validate_invoice', missing_length)
    with Session(ctx.engine) as db:
        with pytest.raises(PortalError) as error:
            approval_service.execute(db, ctx.actor, request_id, 3, accepted)
        assert error.value.code == 'INVOICE_VALIDATION_FAILED'
    assert len(validation_calls) == 2 and len(attempted) == 1 and snapshot() == baseline
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.status == 'ready_for_review' and order.invoice_id is None and order.row_version == 3
        assert db.get(Invoice, attempted[0]) is None
        failures = db.scalars(select(AuditEvent).where(AuditEvent.object_public_id == request_id,
            AuditEvent.action == 'order.approval_failed')).all()
        assert len(failures) == 1 and failures[0].reason == 'INVOICE_VALIDATION_FAILED'
        audit_after = tuple(db.execute(select(*AuditEvent.__table__.columns).order_by(AuditEvent.id)).all())
        assert audit_after[:-1] == audit_before
        assert audit_after[-1]._mapping['id'] == failures[0].id
    monkeypatch.setattr(invoice_adapter.invoices, 'validate_invoice', real_validate)
    with Session(ctx.engine) as db:
        updated = ProposalInput.model_validate({**ctx.quote_body.model_dump(mode='json'),
            'fees':{'shipping_amount':'25.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
            'payment_terms':'prepaid','valid_for_hours':24,'reason':'Corrected invoice data and freight'})
        result = proposal_service.create(db, ctx.actor, request_id, 3, updated)
        db.commit()
        revision = result['original_receipt']
        with pytest.raises(PortalError) as error:
            approval_service.approve(db, ctx.actor, request_id, 4, ApproveInput(accepted_revision_id=revision['revision_id']))
        assert error.value.code == 'CUSTOMER_ACCEPTANCE_REQUIRED'
        db.rollback()
        proposal_decisions.decide(db, ctx.token, ctx.csrf, request_id, revision['revision_id'], 4,
            AcceptInput(proposal_hash=revision['content_hash']), accept=True)
        db.commit()
        command = ApproveInput(accepted_revision_id=revision['revision_id'])
        result = approval_service.execute(db, ctx.actor, request_id, 5, command)
        replay = approval_service.execute(db, ctx.actor, request_id, 5, command)
        assert result['replayed'] is False and replay['replayed'] is True
        assert result['original_receipt'] == replay['original_receipt']
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = db.get(Invoice, order.invoice_id)
        assert invoice.total_amount == Decimal('108.00') and invoice.shipping_fee == Decimal('25.00')
        assert real_validate(invoice) == []
        assert count(db, Invoice, Invoice.source_order_id == request_id) == 1
        assert count(db, Conversion, Conversion.request_id == order.id) == 1
        assert count(db, Publication, Publication.request_id == order.id) == 1
        # Portal PIs skip the creation-time receipt intent draft.
        assert count(db, ReceiptIntent, ReceiptIntent.invoice_id == invoice.id) == 0
        assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == request_id)
            & (OutboxEvent.event_type == 'order_invoice_created')) == 1
        _, _, published = pi_service.capture(db, ctx.token, request_id)
        assert published['total_amount'] == '108.00'