"""Real MySQL 1062 errors exercise bounded, constraint-specific PI retries."""
from uuid import uuid4
import pytest
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.invoice.models import Invoice
from app.portal import approval_service, invoice_adapter
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, Conversion, OrderRequest, OutboxEvent, Publication
from test_mysql_services import accepted_request, assert_one_pi, count


@pytest.mark.parametrize('scenario', ['retry_success', 'exhausted', 'other_unique'])
def test_real_mysql_invoice_conflict_retries_only_number(trade, monkeypatch, scenario):
    ctx = trade
    # Restore the existing upstream unique constraint omitted by the thin fixture.
    with ctx.engine.begin() as connection:
        unique = inspect(connection).get_unique_constraints('ark_invoices')
        if not any(row['column_names'] == ['invoice_no'] for row in unique):
            connection.execute(text('ALTER TABLE ark_invoices ADD UNIQUE KEY invoice_no (invoice_no)'))
    request_id, accepted = accepted_request(ctx)
    attempts, conflicts = [], []
    def allocate(db, user_id, order_type):
        attempts.append(db.get_transaction())
        if scenario == 'exhausted' or scenario == 'retry_success' and len(attempts) < 3:
            return 'PI-LEGACY'
        return 'PI-CONFLICT-' + uuid4().hex
    monkeypatch.setattr(invoice_adapter.invoices, 'suggest_invoice_no', allocate)
    def record(context):
        if isinstance(context.original_exception, Exception):
            conflicts.append(context.original_exception.args)
    def primary_collision(mapper, connection, invoice):
        if scenario == 'other_unique' and invoice.source_order_id == request_id:
            invoice.id = 7
    event.listen(ctx.engine, 'handle_error', record)
    event.listen(Invoice, 'before_insert', primary_collision)
    try:
        with Session(ctx.engine) as db:
            if scenario == 'retry_success':
                result = approval_service.execute(db, ctx.actor, request_id, 3, accepted)
                assert result['current_state'] == 'invoice_created'
            elif scenario == 'exhausted':
                with pytest.raises(PortalError) as error:
                    approval_service.execute(db, ctx.actor, request_id, 3, accepted)
                assert error.value.code == 'INVOICE_NUMBER_CONFLICT' and error.value.status == 409
            else:
                with pytest.raises(IntegrityError) as error:
                    approval_service.execute(db, ctx.actor, request_id, 3, accepted)
                assert error.value.orig.args[0] == 1062
                assert 'PRIMARY' in error.value.orig.args[1]
    finally:
        event.remove(ctx.engine, 'handle_error', record)
        event.remove(Invoice, 'before_insert', primary_collision)
    assert len(attempts) == (1 if scenario == 'other_unique' else 3)
    assert len({id(transaction) for transaction in attempts}) == len(attempts)
    assert len(conflicts) == {'retry_success':2, 'exhausted':3, 'other_unique':1}[scenario]
    assert all(error[0] == 1062 for error in conflicts)
    if scenario != 'other_unique':
        assert all('invoice_no' in error[1] for error in conflicts)
    if scenario == 'retry_success':
        assert_one_pi(ctx, request_id)
    with Session(ctx.engine) as db:
        assert db.get(Invoice, 7).invoice_no == 'PI-LEGACY'
        failures = db.scalars(select(AuditEvent).where(AuditEvent.object_public_id == request_id,
            AuditEvent.action == 'order.approval_failed')).all()
        assert len(failures) == int(scenario == 'exhausted')
        if failures:
            assert failures[0].reason == 'INVOICE_NUMBER_CONFLICT'
        if scenario != 'retry_success':
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            assert order.status == 'ready_for_review' and order.row_version == 3 and order.invoice_id is None
            assert count(db, Invoice, Invoice.source_order_id == request_id) == 0
            assert count(db, Conversion, Conversion.request_id == order.id) == 0
            assert count(db, Publication, Publication.request_id == order.id) == 0
            assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == request_id)
                & (OutboxEvent.event_type == 'order_invoice_created')) == 0