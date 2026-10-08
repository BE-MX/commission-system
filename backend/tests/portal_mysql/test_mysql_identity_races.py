"""Real strong-identity arbitration and review revocation race with PI approval."""
import pytest
from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.orm import Session

from app.customer import identity_service
from app.customer.models import CustomerAccount, CustomerExternalIdentity, CustomerResolutionKey
from app.invoice.models import Invoice
from app.portal import approval_service
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, Conversion, CustomerAccess, OrderRequest, PortalSession
from test_mysql_services import accepted_request, assert_one_pi, compete, count


@pytest.mark.parametrize('identity_first', [True, False])
def test_identity_conflict_and_approval_obey_commit_order(trade, identity_first):
    ctx = trade
    # Thin upstream fixture retains the arbitration unique key; no arbiter mock.
    metadata = MetaData()
    Table(CustomerResolutionKey.__tablename__, metadata, *(Column(column.name, column.type,
        primary_key=column.primary_key, nullable=column.nullable, unique=column.unique,
        default=column.default, server_default=column.server_default)
        for column in CustomerResolutionKey.__table__.columns))
    metadata.create_all(ctx.engine)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        customer_id, identity_id, version = access.customer_id, access.external_identity_id, access.auth_version
        db.get(CustomerAccount, customer_id).profile_input_seq = 0
        other = CustomerAccount(display_name='Conflicting company', canonical_company_name='Conflicting company',
            record_status='active', identity_status='verified', profile_input_seq=0)
        db.add(other)
        db.flush()
        original = db.get(CustomerExternalIdentity, identity_id)
        duplicate = CustomerExternalIdentity(customer_id=other.id, source_system=original.source_system,
            source_account_key=original.source_account_key, identifier_type=original.identifier_type,
            raw_value=original.raw_value, normalized_value=original.normalized_value,
            identity_strength='strong', cardinality='one_to_one', verification_status='verified', status='active')
        db.add(duplicate)
        db.flush()
        duplicate_id, other_id = duplicate.id, other.id
        db.commit()
    request_id, body = accepted_request(ctx)
    approve = lambda db: approval_service.approve(db, ctx.actor, request_id, 3, body)
    def conflict(db):
        result = identity_service.confirm_identity(db, identity_id, verified_by=ctx.admin)
        assert result.conflict and result.conflicting_identity_ids == (duplicate_id,)
        return {'conflict': True}
    first, second = compete(ctx, conflict if identity_first else approve, approve if identity_first else conflict)
    if identity_first:
        assert first == {'conflict': True}
        assert second == {'error': 'IDENTITY_REVIEW_REQUIRED', 'status': 409}
    else:
        assert first['current_state'] == 'invoice_created' and second == {'conflict': True}
        assert_one_pi(ctx, request_id)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        assert access.status == 'review_required' and access.auth_version == version + 1
        assert access.customer_id == customer_id and access.external_identity_id == identity_id
        for identifier in (identity_id, duplicate_id):
            row = db.get(CustomerExternalIdentity, identifier)
            assert row.status == row.verification_status == 'disputed'
        for identifier in (customer_id, other_id):
            row = db.get(CustomerAccount, identifier)
            assert row.identity_status == 'disputed' and row.profile_input_seq == 1
        resolutions = db.scalars(select(CustomerResolutionKey).where(CustomerResolutionKey.customer_id == customer_id)).all()
        assert len(resolutions) == 1 and resolutions[0].status == 'conflict'
        assert db.get(PortalSession, ctx.session_id).revoked_at is not None
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.status == ('ready_for_review' if identity_first else 'invoice_created')
        assert count(db, Invoice, Invoice.source_order_id == request_id) == int(not identity_first)
        assert count(db, Conversion, Conversion.request_id == order.id) == int(not identity_first)
        assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id)
            & (AuditEvent.action == 'order.invoice_created')) == int(not identity_first)
        db.rollback()
        with pytest.raises(PortalError) as caught:
            approve(db)
        assert caught.value.code == 'IDENTITY_REVIEW_REQUIRED'
        db.rollback()

@pytest.mark.parametrize('operation', ['attach', 'resolve', 'okki_customer', 'okki_contact', 'alibaba', 'agent_ingest'])
def test_identity_write_entry_locks_before_first_business_query(trade, operation):
    from sqlalchemy import event
    from app.customer import projection_okki, projection_alibaba
    from app.sales_automation import service as automation
    from app.portal.models import AuthorityBarrier
    class FirstStatementObserved(Exception):
        pass
    statements, preparation = [], []
    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement == 'SELECT @@SESSION.innodb_lock_wait_timeout':
            assert preparation == []
            preparation.append(statement)
            return
        if statement == 'SET SESSION innodb_lock_wait_timeout = %s':
            assert preparation == ['SELECT @@SESSION.innodb_lock_wait_timeout']
            from app.portal import authority
            assert parameters == (authority.get_settings().PORTAL_LOCK_WAIT_SECONDS,)
            preparation.append(statement)
            return
        statements.append(statement)
        raise FirstStatementObserved()
    with Session(trade.engine) as db:
        access = db.get(CustomerAccess, trade.access_id)
        customer_id = access.customer_id
        db.rollback()
        event.listen(trade.engine, 'after_cursor_execute', capture)
        try:
            with pytest.raises(FirstStatementObserved):
                if operation == 'attach':
                    identity_service.attach_identity_candidate(db, customer_id=customer_id,
                        source_system='okki', source_account_key='okki:test',
                        identifier_type='company_id', raw_value=str(customer_id))
                elif operation == 'resolve':
                    identity_service.resolve_business_context(db, source_system='okki',
                        source_account_key='okki:test', source_entity_type='company',
                        external_context_id=str(customer_id))
                elif operation == 'agent_ingest':
                    automation.ingest_candidates(db, 999, [], 'first-query', trade.actor, 'test-agent', 'test-lease')
                else:
                    entry = {'okki_customer': projection_okki.project_okki_customer,
                        'okki_contact': projection_okki.project_okki_contact,
                        'alibaba': projection_alibaba.project_alibaba_inquiry}[operation]
                    entry(db, source_account_key='isolated-source', payload={})
        finally:
            event.remove(trade.engine, 'after_cursor_execute', capture)
            db.rollback()
    assert preparation == ['SELECT @@SESSION.innodb_lock_wait_timeout', 'SET SESSION innodb_lock_wait_timeout = %s']
    assert len(statements) == 1
    assert AuthorityBarrier.__tablename__ in statements[0] and 'FOR UPDATE' in statements[0].upper()
