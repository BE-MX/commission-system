"""Owner/delegate approval and upstream delegation revocation compete on MySQL."""
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkUserRole
from app.invoice import delegation_service
from app.invoice.models import Invoice, InvoiceDelegateGrant
from app.portal import approval_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, CommandReceipt, Conversion, OrderRequest
from test_mysql_services import accepted_request, assert_one_pi, compete, count


def delegate(ctx):
    with Session(ctx.engine) as db:
        role_id = db.scalar(select(ArkUserRole.role_id).where(ArkUserRole.user_id == ctx.actor))
        user = ArkUser(username='delegate-' + uuid4().hex[:12], password_hash='test-only-not-a-login',
            real_name='Authorized delegate', is_active=True)
        db.add(user)
        db.flush()
        identifier = user.id
        db.add(ArkUserRole(user_id=identifier, role_id=role_id))
        delegation_service.replace_grants(db, identifier, [ctx.actor], operator_id=ctx.admin)
        db.commit()
        return identifier


@pytest.mark.parametrize('delegate_first', [True, False])
def test_two_authorized_employees_create_one_pi(trade, delegate_first):
    ctx = trade
    identifier = delegate(ctx)
    request_id, body = accepted_request(ctx)
    actors = [identifier, ctx.actor] if delegate_first else [ctx.actor, identifier]
    first, second = compete(ctx,
        lambda db: approval_service.approve(db, actors[0], request_id, 3, body),
        lambda db: approval_service.approve(db, actors[1], request_id, 3, body))
    assert first['replayed'] is False and second['replayed'] is True
    assert first['original_receipt'] == second['original_receipt']
    assert_one_pi(ctx, request_id)
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice = db.get(Invoice, order.invoice_id)
        assert invoice.sales_user_id == ctx.actor and invoice.created_by == actors[0]
        command = db.scalar(select(CommandReceipt).where(
            CommandReceipt.object_public_id == request_id, CommandReceipt.action == 'approve'))
        assert command.first_actor_id == actors[0]
        assert db.scalar(select(Conversion).where(Conversion.request_id == order.id)).created_by == actors[0]
        audits = db.scalars(select(AuditEvent).where(
            AuditEvent.object_public_id == request_id, AuditEvent.action == 'order.invoice_created')).all()
        assert len(audits) == 1 and audits[0].actor_id == actors[0]


@pytest.mark.parametrize('revoke_first', [True, False])
def test_real_delegate_revocation_and_approval_obey_commit_order(trade, revoke_first):
    ctx = trade
    identifier = delegate(ctx)
    request_id, body = accepted_request(ctx)
    approve = lambda db: approval_service.approve(db, identifier, request_id, 3, body)
    def revoke(db):
        delegation_service.replace_grants(db, identifier, [], operator_id=ctx.admin)
        db.flush()
        return {'revoked': True}
    first, second = compete(ctx, revoke if revoke_first else approve, approve if revoke_first else revoke)
    if revoke_first:
        assert first == {'revoked': True}
        assert second == {'error': 'RESOURCE_NOT_FOUND', 'status': 404}
    else:
        assert first['current_state'] == 'invoice_created'
        assert second == {'revoked': True}
        assert_one_pi(ctx, request_id)
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.status == ('ready_for_review' if revoke_first else 'invoice_created')
        assert count(db, Invoice, Invoice.source_order_id == request_id) == int(not revoke_first)
        assert count(db, Conversion, Conversion.request_id == order.id) == int(not revoke_first)
        assert count(db, InvoiceDelegateGrant, InvoiceDelegateGrant.delegate_user_id == identifier) == 0
        assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id)
            & (AuditEvent.action == 'order.invoice_created')) == int(not revoke_first)
        db.rollback()
        with pytest.raises(PortalError) as caught:
            approve(db)
        assert caught.value.status == 404
        db.rollback()
