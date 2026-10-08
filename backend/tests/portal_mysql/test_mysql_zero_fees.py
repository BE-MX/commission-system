"""Pending fees never become zero; explicit zero survives real PI creation."""
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import Invoice
from app.portal import approval_service, proposal_service, proposal_decisions, pi_service, order_queries
from app.portal.errors import PortalError
from app.portal.models import OrderRequest, Revision, Publication, Conversion
from app.portal.schemas import ProposalInput, AcceptInput, ApproveInput
from test_mysql_services import submit, count


def test_unknown_fees_require_explicit_zero_and_customer_acceptance(trade):
    ctx = trade
    with Session(ctx.engine) as db:
        submitted = submit(ctx, db); db.commit()
        request_id = submitted['request_id']
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        initial = db.get(Revision, order.active_revision_id)
        initial_id, initial_public_id = initial.id, initial.public_id
        assert initial.fees_status == 'pending'
        assert initial.total_amount is None and initial.shipping_amount is None
        view = order_queries.customer_detail(db, ctx.token, request_id)
        assert view['total_amount'] is None
        with pytest.raises(PortalError) as error:
            approval_service.approve(db, ctx.actor, request_id, 1, ApproveInput(accepted_revision_id=initial_public_id))
        assert error.value.code == 'CUSTOMER_ACCEPTANCE_REQUIRED'
        db.rollback()
        assert count(db, Invoice, Invoice.source_order_id == request_id) == 0
        assert count(db, Publication, Publication.request_id == order.id) == 0
        assert count(db, Conversion, Conversion.request_id == order.id) == 0
        base = {**ctx.quote_body.model_dump(mode='json'), 'payment_terms':'prepaid',
            'valid_for_hours':24, 'reason':'Explicitly confirmed free shipping'}
        for fees in ({'shipping_amount':None, 'packaging_amount':'0.00', 'surcharge_amount':'0.00'},
                     {'packaging_amount':'0.00', 'surcharge_amount':'0.00'}):
            with pytest.raises(ValidationError):
                ProposalInput.model_validate({**base, 'fees':fees})
        proposal = ProposalInput.model_validate({**base, 'fees':{
            'shipping_amount':'0.00', 'packaging_amount':'0.00', 'surcharge_amount':'0.00'}})
        created = proposal_service.create(db, ctx.actor, request_id, 1, proposal); db.commit()
        receipt = created['original_receipt']
        with pytest.raises(PortalError) as error:
            approval_service.approve(db, ctx.actor, request_id, 2, ApproveInput(accepted_revision_id=receipt['revision_id']))
        assert error.value.code == 'CUSTOMER_ACCEPTANCE_REQUIRED'
        db.rollback()
        assert count(db, Invoice, Invoice.source_order_id == request_id) == 0
        proposal_decisions.decide(db, ctx.token, ctx.csrf, request_id, receipt['revision_id'], 2,
            AcceptInput(proposal_hash=receipt['content_hash']), accept=True)
        db.commit()
        approval_service.approve(db, ctx.actor, request_id, 3, ApproveInput(accepted_revision_id=receipt['revision_id']))
        db.commit()
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        revision = db.get(Revision, order.accepted_revision_id)
        invoice = db.get(Invoice, order.invoice_id)
        assert revision.fees_status == 'confirmed' and revision.customer_accepted_by == ctx.account_id
        assert revision.shipping_amount == revision.packaging_amount == revision.surcharge_amount == Decimal('0.00')
        assert invoice.shipping_fee == invoice.internal_accessory == invoice.surcharge_amount == Decimal('0.00')
        assert invoice.total_amount == invoice.product_amount == revision.total_amount == Decimal('81.00')
        assert count(db, Invoice, Invoice.source_order_id == request_id) == 1
        _, _, snapshot = pi_service.capture(db, ctx.token, request_id)
        assert snapshot['total_amount'] == snapshot['product_amount'] == '81.00'
        assert snapshot['fees']['shipping_amount'] == '0.00'
        initial = db.get(Revision, initial_id)
        assert initial.shipping_amount is None and initial.total_amount is None and initial.fees_status == 'pending'