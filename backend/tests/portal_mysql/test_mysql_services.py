"""Actual portal/auth/invoice services on independently connected MySQL transactions."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import queue

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from test_mysql_concurrency import wait_for_lock
from app.auth import admin_router as employee_admin
from app.auth.admin_schemas import UserUpdateRequest
from app.auth.models import ArkUser
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import ReceiptIntent
from app.portal import admin_service, order_service, proposal_service, proposal_decisions, approval_service
from app.portal.authority import lock_authority
from app.portal.errors import PortalError
from app.portal.models import Account, CommandReceipt, Conversion, OrderRequest, OutboxEvent, PortalSession, Publication
from app.portal.schemas import AccountUpdate, AcceptInput, ApproveInput, ProposalInput


def compete(ctx, first_action, second_action, *, finalize=None):
    started = queue.Queue()
    def second():
        with Session(ctx.engine) as db:
            started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            try:
                result = second_action(db)
                db.commit()
                return result
            except PortalError as error:
                db.rollback()
                return {'error': error.code, 'status': error.status}
    with Session(ctx.engine) as first, ThreadPoolExecutor(max_workers=1) as executor:
        result = first_action(first)
        future = executor.submit(second)
        try:
            wait_for_lock(ctx.engine, started.get(timeout=3))
            assert not future.done()
            if finalize: finalize(first)
            else: first.commit()
        finally:
            first.rollback()
        return result, future.result(timeout=6)


def submit(ctx, db):
    return order_service.submit(db, ctx.token, ctx.csrf, ctx.key, ctx.body)


def disable_account(ctx, db):
    return admin_service.update_account(db, ctx.admin, ctx.account_public_id, ctx.account_version,
        AccountUpdate(status='disabled', reason='Concurrent access revocation test'))


def disable_employee(ctx, db):
    result = employee_admin.update_user(ctx.actor, UserUpdateRequest(is_active=False), db, {'sub':str(ctx.admin)})
    assert result.code == 200
    return {'disabled':True}


def count(db, model, predicate):
    return db.scalar(select(func.count()).select_from(model).where(predicate))


@pytest.mark.parametrize('commit_first', [True, False])
def test_actual_duplicate_submit_waits_and_replays_or_retries(trade, commit_first):
    ctx = trade
    first, second = compete(ctx, lambda db: submit(ctx, db), lambda db: submit(ctx, db),
        finalize=lambda db: db.commit() if commit_first else db.rollback())
    assert second['status'] == 'submitted' and second['replayed'] is commit_first
    if commit_first: assert first['request_id'] == second['request_id']
    with Session(ctx.engine) as db:
        assert count(db, OrderRequest, OrderRequest.access_id == ctx.access_id) == 1
        assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == second['request_id']) & (OutboxEvent.event_type == 'order_submitted')) == 1
        order = db.scalar(select(OrderRequest).where(OrderRequest.access_id == ctx.access_id))
        assert order.invoice_id is None


@pytest.mark.parametrize('revoke_first', [True, False])
def test_account_revocation_and_submission_obey_commit_order(trade, revoke_first):
    ctx = trade
    if revoke_first:
        _, result = compete(ctx, lambda db: disable_account(ctx, db), lambda db: submit(ctx, db))
        assert result['status'] == 401
    else:
        result, disabled = compete(ctx, lambda db: submit(ctx, db), lambda db: disable_account(ctx, db))
        assert result['status'] == 'submitted' and disabled['status'] == 'disabled'
    with Session(ctx.engine) as db:
        assert count(db, OrderRequest, OrderRequest.access_id == ctx.access_id) == (0 if revoke_first else 1)
        assert db.get(Account, ctx.account_id).status == 'disabled'
        assert db.get(PortalSession, ctx.session_id).revoked_at is not None
        with pytest.raises(PortalError) as caught:
            submit(ctx, db)
        assert caught.value.status == 401
        db.rollback()


def accepted_request(ctx):
    with Session(ctx.engine) as db:
        submitted = submit(ctx, db); db.commit()
        body = ProposalInput.model_validate({**ctx.quote_body.model_dump(mode='json'),
            'fees':{'shipping_amount':'45.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
            'payment_terms':'prepaid','valid_for_hours':24,'reason':'Confirmed freight'})
        proposal = proposal_service.create(db, ctx.actor, submitted['request_id'], 1, body); db.commit()
        revision = proposal['original_receipt']
        proposal_decisions.decide(db, ctx.token, ctx.csrf, submitted['request_id'], revision['revision_id'], 2,
            AcceptInput(proposal_hash=revision['content_hash']), accept=True)
        db.commit()
        return submitted['request_id'], ApproveInput(accepted_revision_id=revision['revision_id'])


def assert_one_pi(ctx, request_id):
    with Session(ctx.engine) as db:
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert order.status == 'invoice_created' and order.row_version == 4
        assert count(db, Invoice, Invoice.source_order_id == request_id) == 1
        invoice = db.get(Invoice, order.invoice_id)
        assert invoice.total_amount == Decimal('128.00') and invoice.sales_user_id == ctx.actor
        assert count(db, InvoiceItem, InvoiceItem.invoice_id == invoice.id) == 1
        # Portal PIs skip the creation-time receipt intent draft; Ark receipt
        # entries (manual receipt or invoice edit) handle collection later.
        assert count(db, ReceiptIntent, ReceiptIntent.invoice_id == invoice.id) == 0
        assert count(db, Conversion, Conversion.request_id == order.id) == 1
        assert count(db, Publication, Publication.request_id == order.id) == 1
        assert count(db, CommandReceipt, (CommandReceipt.object_public_id == request_id) & (CommandReceipt.action == 'approve')) == 1
        assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == request_id) & (OutboxEvent.event_type == 'order_invoice_created')) == 1


@pytest.mark.parametrize('commit_first', [True, False])
def test_actual_duplicate_approval_has_one_pi_and_atomic_retry(trade, commit_first):
    ctx = trade
    request_id, body = accepted_request(ctx)
    action = lambda db: approval_service.approve(db, ctx.actor, request_id, 3, body)
    first, second = compete(ctx, action, action, finalize=lambda db: db.commit() if commit_first else db.rollback())
    assert second['current_state'] == 'invoice_created' and second['replayed'] is commit_first
    if commit_first: assert first['original_receipt'] == second['original_receipt']
    assert_one_pi(ctx, request_id)


@pytest.mark.parametrize('revoke_first', [True, False])
def test_real_employee_disable_races_with_approval(trade, revoke_first):
    ctx = trade
    request_id, body = accepted_request(ctx)
    approve = lambda db: approval_service.approve(db, ctx.actor, request_id, 3, body)
    if revoke_first:
        # Hold the real upstream barrier until the waiting approval is observed,
        # then invoke the existing employee endpoint, which owns its commit.
        _, result = compete(ctx, lambda db: lock_authority(db, force=True), approve,
            finalize=lambda db: disable_employee(ctx, db))
        assert result['status'] == 403
        with Session(ctx.engine) as db:
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            assert order.status == 'ready_for_review' and order.invoice_id is None
            assert count(db, Invoice, Invoice.source_order_id == request_id) == 0
            assert count(db, Conversion, Conversion.request_id == order.id) == 0
    else:
        result, disabled = compete(ctx, approve, lambda db: disable_employee(ctx, db))
        assert result['current_state'] == 'invoice_created' and disabled['disabled']
        assert_one_pi(ctx, request_id)
    with Session(ctx.engine) as db:
        assert not db.get(ArkUser, ctx.actor).is_active
        db.rollback()  # Start authorization in a new transaction, as the HTTP boundary does.
        with pytest.raises(PortalError) as caught: approve(db)
        assert caught.value.status == 403
        db.rollback()
