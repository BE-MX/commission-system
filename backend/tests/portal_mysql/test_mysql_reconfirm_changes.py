"""Changed commercial terms create a new immutable revision requiring acceptance."""
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import Invoice, InvoiceItem, CustomerPriceRule
from app.portal import approval_service, proposal_service, proposal_decisions, pi_service
from app.portal.errors import PortalError
from app.portal.models import OrderRequest, Revision, RequestLine, CustomerAccess
from app.portal.schemas import ProposalInput, ApproveInput, AcceptInput
from test_mysql_services import accepted_request, count


@pytest.mark.parametrize('change', ['price', 'address', 'quantity'])
def test_accepted_terms_change_requires_new_customer_confirmation(trade, change):
    ctx = trade
    request_id, old_approval = accepted_request(ctx)
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        old_id = order.accepted_revision_id
        old_revision = db.get(Revision, old_id)
        old_hash = old_revision.content_hash
        old_snapshot = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == old_id)).one())
        old_lines = tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id == old_id).order_by(RequestLine.id)).all())
        body = {**ctx.quote_body.model_dump(mode='json'),
            'fees':{'shipping_amount':'45.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
            'payment_terms':'prepaid','valid_for_hours':24,'reason':'Customer requested updated commercial terms'}
        if change == 'price':
            access = db.get(CustomerAccess, ctx.access_id)
            rule = db.scalar(select(CustomerPriceRule).where(CustomerPriceRule.customer_id == access.okki_company_id))
            rule.adjust_value = Decimal('0')
            db.commit()
        elif change == 'address':
            body['delivery']['address_line1'] = '99 New Delivery Street'
        else:
            body['items'][0]['quantity'] = 4
        proposed = proposal_service.create(db, ctx.actor, request_id, 3, ProposalInput.model_validate(body))
        db.commit()
        new = proposed['original_receipt']
        assert new['revision_id'] != str(old_approval.accepted_revision_id)
        assert new['content_hash'] != old_hash
        db.refresh(order)
        assert order.status == 'awaiting_customer' and order.row_version == 4 and order.accepted_revision_id is None
        # Replaying a genuine old acceptance returns its receipt, not a new approval.
        replay = proposal_decisions.decide(db, ctx.token, ctx.csrf, request_id, old_approval.accepted_revision_id,
            2, AcceptInput(proposal_hash=old_hash), accept=True)
        db.commit()
        assert replay['replayed'] and replay['current_state'] == 'awaiting_customer'
        assert order.accepted_revision_id is None
        for revision_id in (old_approval.accepted_revision_id, new['revision_id']):
            with pytest.raises(PortalError) as error:
                approval_service.approve(db, ctx.actor, request_id, 4, ApproveInput(accepted_revision_id=revision_id))
            assert error.value.code == 'CUSTOMER_ACCEPTANCE_REQUIRED'
            db.rollback()
        assert count(db, Invoice, Invoice.source_order_id == request_id) == 0
        proposal_decisions.decide(db, ctx.token, ctx.csrf, request_id, new['revision_id'], 4,
            AcceptInput(proposal_hash=new['content_hash']), accept=True)
        db.commit()
        approval_service.approve(db, ctx.actor, request_id, 5, ApproveInput(accepted_revision_id=new['revision_id']))
        db.commit()
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        revision = db.get(Revision, order.accepted_revision_id)
        invoice = db.get(Invoice, order.invoice_id)
        item = db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id))
        assert order.status == 'invoice_created' and revision.public_id == new['revision_id']
        assert revision.customer_accepted_by == ctx.account_id
        assert invoice.total_amount == Decimal({'price':'137.00','address':'128.00','quantity':'155.00'}[change])
        assert item.quantity == (4 if change == 'quantity' else 3)
        assert item.price_per_piece == Decimal('30.0000' if change == 'price' else '27.0000')
        assert ('99 New Delivery Street' in invoice.delivery_address) is (change == 'address')
        assert count(db, Invoice, Invoice.source_order_id == request_id) == 1
        _, _, snapshot = pi_service.capture(db, ctx.token, request_id)
        assert snapshot['total_amount'] == format(invoice.total_amount, '.2f')
        assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id == old_id)).one()) == old_snapshot
        assert tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id == old_id).order_by(RequestLine.id)).all()) == old_lines