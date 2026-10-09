"""Customer acceptance and cancellation races use real authorization and PI services."""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.invoice.models import Invoice
from app.portal import auth_service as auth, order_commands, proposal_service, proposal_decisions, approval_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, CommandReceipt, Conversion, CustomerAccess, OrderRequest, OutboxEvent, Revision
from app.portal.schemas import AcceptInput, ProposalInput, ReasonInput, VerifyInput
from test_mysql_invitation_race import invite, challenge
from test_mysql_services import accepted_request, assert_one_pi, compete, count, submit


@pytest.mark.parametrize('new_member_first', [False, True])
def test_two_members_accept_once_and_preserve_first_actor(trade, new_member_first):
    ctx = trade
    with Session(ctx.engine) as db:
        invited = invite(ctx, db)
        attempt = challenge(db, invited)
        principal, session, second_token = auth.verify(db,
            auth.require_preauth(db, attempt.token, attempt.csrf),
            VerifyInput(challenge_id=attempt.public_id, code=attempt.code), '127.0.0.1')
        second_csrf = auth._csrf(session)
        assert principal.access.id == ctx.access_id and principal.account.id != ctx.account_id
        db.commit()
        submitted = submit(ctx, db)
        db.commit()
        body = ProposalInput.model_validate({**ctx.quote_body.model_dump(mode='json'),
            'fees': {'shipping_amount': '45.00', 'packaging_amount': '2.00', 'surcharge_amount': '0.00'},
            'payment_terms': 'prepaid', 'valid_for_hours': 24, 'reason': 'Confirmed freight'})
        proposal = proposal_service.create(db, ctx.actor, submitted['request_id'], 1, body)
        db.commit()
        receipt = proposal['original_receipt']
    request_id = submitted['request_id']
    members = [(ctx.token, ctx.csrf, ctx.account_id), (second_token, second_csrf, invited.account_id)]
    if new_member_first:
        members.reverse()
    def accept(db, member):
        return proposal_decisions.decide(db, member[0], member[1], request_id, receipt['revision_id'],
            2, AcceptInput(proposal_hash=receipt['content_hash']), accept=True)
    first, second = compete(ctx, lambda db: accept(db, members[0]), lambda db: accept(db, members[1]))
    assert first['replayed'] is False and second['replayed'] is True
    assert first['original_receipt'] == second['original_receipt']
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        revision = db.get(Revision, order.accepted_revision_id)
        assert order.status == 'ready_for_review' and order.row_version == 3
        assert revision.public_id == receipt['revision_id']
        assert revision.customer_accepted_by == members[0][2]
        commands = db.scalars(select(CommandReceipt).where(
            CommandReceipt.object_public_id == request_id, CommandReceipt.action == 'accept')).all()
        assert len(commands) == 1 and commands[0].first_actor_id == members[0][2]
        assert commands[0].completed_at == revision.customer_accepted_at
        assert revision.customer_accepted_at.isoformat() == first['original_receipt']['completed_at']
        audits = db.scalars(select(AuditEvent).where(
            AuditEvent.object_public_id == request_id, AuditEvent.action == 'order.accepted')).all()
        assert len(audits) == 1 and audits[0].actor_id == members[0][2]
        assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == request_id)
            & (OutboxEvent.event_type == 'order_accepted')) == 1
        assert count(db, Invoice, Invoice.source_order_id == request_id) == 0


@pytest.mark.parametrize('cancel_first', [True, False])
def test_cancel_and_approve_have_one_legal_successor(trade, cancel_first):
    ctx = trade
    request_id, approval = accepted_request(ctx)
    reason = ReasonInput(reason='Customer changed purchase plan')
    cancel = lambda db: order_commands.cancel(db, ctx.token, ctx.csrf, request_id, 3, reason)
    approve = lambda db: approval_service.approve(db, ctx.actor, request_id, 3, approval)
    first, second = compete(ctx, cancel if cancel_first else approve, approve if cancel_first else cancel)
    assert first['current_state'] == ('cancelled' if cancel_first else 'invoice_created')
    assert second == {'error': 'VERSION_CONFLICT', 'status': 409}
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.row_version == 4
        assert order.status == ('cancelled' if cancel_first else 'invoice_created')
        assert (order.invoice_id is None) is cancel_first
        assert count(db, Invoice, Invoice.source_order_id == request_id) == int(not cancel_first)
        assert count(db, Conversion, Conversion.request_id == order.id) == int(not cancel_first)
        assert count(db, CommandReceipt, (CommandReceipt.object_public_id == request_id)
            & (CommandReceipt.action == 'cancel')) == int(cancel_first)
        assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == request_id)
            & (OutboxEvent.event_type == 'order_cancelled')) == int(cancel_first)
        assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id)
            & (AuditEvent.action == 'order.cancelled')) == int(cancel_first)
        db.rollback()
        if cancel_first:
            for version in (3, 4):
                replay = order_commands.cancel(db, ctx.token, ctx.csrf, request_id, version, reason)
                db.commit()
                assert replay['replayed'] is True
                assert replay['original_receipt'] == first['original_receipt']
                with pytest.raises(PortalError) as caught:
                    order_commands.cancel(db, ctx.token, ctx.csrf, request_id, version, ReasonInput(reason='Different reason'))
                assert caught.value.code == 'IDEMPOTENCY_CONFLICT'
                db.rollback()
            assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id)
                & (AuditEvent.action == 'order.cancelled')) == 1
            assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == request_id)
                & (OutboxEvent.event_type == 'order_cancelled')) == 1
            access = db.get(CustomerAccess, ctx.access_id)
            access.can_order = False
            db.commit()
            with pytest.raises(PortalError) as caught:
                cancel(db)
            assert caught.value.status == 403
            db.rollback()
    if not cancel_first:
        assert_one_pi(ctx, request_id)
