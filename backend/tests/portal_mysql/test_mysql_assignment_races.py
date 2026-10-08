"""Real upstream owner transfer races with portal PI creation, including event writes."""
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.customer import workflow_service
from app.customer.models import CustomerAccount, CustomerAction, CustomerAssignment, CustomerEvent, CustomerOpportunity
from app.invoice.models import Invoice
from app.portal import approval_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, Conversion, CustomerAccess, OrderRequest, PortalSession
from test_mysql_services import accepted_request, assert_one_pi, compete, count


@pytest.mark.parametrize('transfer_first', [True, False])
def test_real_customer_transfer_and_approval_obey_commit_order(trade, transfer_first):
    ctx = trade
    # Upstream tables are fixture scaffolding; portal tables use the real migrations.
    metadata = MetaData()
    for model in (CustomerAction, CustomerOpportunity, CustomerEvent):
        Table(model.__tablename__, metadata, *(Column(column.name, column.type,
            primary_key=column.primary_key, nullable=column.nullable,
            default=column.default, server_default=column.server_default)
            for column in model.__table__.columns))
    metadata.create_all(ctx.engine)
    with Session(ctx.engine) as db:
        user = ArkUser(username='new-owner-' + uuid4().hex[:12], password_hash='test-only-not-a-login',
            real_name='New customer owner', is_active=True)
        db.add(user)
        db.flush()
        new_owner = user.id
        access = db.get(CustomerAccess, ctx.access_id)
        customer_id, old_assignment, version = access.customer_id, access.assignment_id, access.auth_version
        db.get(CustomerAccount, customer_id).profile_input_seq = 0
        db.commit()
    request_id, body = accepted_request(ctx)
    approve = lambda db: approval_service.approve(db, ctx.actor, request_id, 3, body)
    def transfer(db):
        row = workflow_service.transfer_primary_owner(db, customer_id=customer_id,
            new_user_id=new_owner, operated_by=ctx.admin, change_reason='Isolated handoff concurrency check')
        return {'new_owner': row.user_id}
    first, second = compete(ctx, transfer if transfer_first else approve, approve if transfer_first else transfer)
    if transfer_first:
        assert first == {'new_owner': new_owner}
        assert second['status'] in (403, 409)
    else:
        assert first['current_state'] == 'invoice_created' and second == {'new_owner': new_owner}
        assert_one_pi(ctx, request_id)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        assert access.status == 'review_required' and access.auth_version == version + 1
        assert access.sales_user_id == ctx.actor and access.assignment_id == old_assignment
        assert db.get(CustomerAssignment, old_assignment).assignment_status == 'ended'
        current = db.scalars(select(CustomerAssignment).where(CustomerAssignment.customer_id == customer_id,
            CustomerAssignment.assignment_role == 'primary', CustomerAssignment.assignment_status == 'active')).all()
        assert len(current) == 1 and current[0].user_id == new_owner
        assert db.get(PortalSession, ctx.session_id).revoked_at is not None
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.status == ('ready_for_review' if transfer_first else 'invoice_created')
        assert order.servicing_user_id == ctx.actor
        assert count(db, Invoice, Invoice.source_order_id == request_id) == int(not transfer_first)
        assert count(db, Conversion, Conversion.request_id == order.id) == int(not transfer_first)
        assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id)
            & (AuditEvent.action == 'order.invoice_created')) == int(not transfer_first)
        events = db.scalars(select(CustomerEvent).where(CustomerEvent.customer_id == customer_id,
            CustomerEvent.event_type == 'assignment.changed')).all()
        assert len(events) == 2 and {event.actor_user_id for event in events} == {ctx.admin}
        db.rollback()
        with pytest.raises(PortalError):
            approve(db)
        db.rollback()
