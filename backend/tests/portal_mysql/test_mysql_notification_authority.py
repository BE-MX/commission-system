"""T36/T61: actual worker/SMTP code releases locks at the final authorization boundary."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import queue
from threading import Event

import pytest
from sqlalchemy import Column, MetaData, Table, select, text
from sqlalchemy.orm import Session
from app.core import time as platform_time
from app.auth import admin_router as employee_admin
from app.auth.admin_schemas import UserUpdateRequest
from app.auth.models import ArkUser, ArkUserRole
from app.customer import workflow_service
from app.customer.models import CustomerAccount, CustomerAction, CustomerOpportunity, CustomerEvent
from app.portal import (auth_service as auth, admin_service, mail_worker, notification_worker,
    binding_review_service, ownership_service)
from app.portal.authority import lock_authority
from app.portal.models import Account, Invitation, OutboxEvent, CustomerAccess, OrderRequest, Revision, RequestLine, PortalSession, HistoryGrant
from app.portal.schemas import AccountUpdate, TransferInput, CustomerUpdate
from uuid import uuid4
from test_mysql_concurrency import wait_for_lock
from test_mysql_notification_process import notification_case, target, business_snapshot
from test_mysql_decision_recovery import snapshot


def setup_delivery(ctx, monkeypatch, kind):
    settings = auth.get_settings()
    settings.PORTAL_MAIL_ENABLED = settings.PORTAL_NOTIFICATION_ENABLED = True
    settings.PORTAL_EMPLOYEE_ORIGIN = 'https://ark.example.test'
    settings.PORTAL_MAIL_SENDER = 'portal@example.test'
    settings.PORTAL_SMTP_HOST = 'smtp-owned.invalid'
    settings.PORTAL_SMTP_PORT = 465
    settings.PORTAL_SMTP_USERNAME = 'owned-test-login'
    settings.PORTAL_SMTP_PASSWORD = 'synthetic-no-network-value'
    for module in (mail_worker, notification_worker):
        monkeypatch.setattr(module, 'get_settings', lambda:settings)
    issued = platform_time.beijing_now().replace(microsecond=0)+timedelta(minutes=2)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = issued.replace(tzinfo=platform_time.BEIJING_TIMEZONE)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
    monkeypatch.setattr(platform_time, 'datetime', Clock)
    identifier = target(ctx, 'order' if kind == 'transfer' else kind, settings)
    account_id = ctx.account_id
    if kind == 'invitation':
        with Session(ctx.engine) as db:
            row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
            account_id = db.scalar(select(Invitation.account_id).where(Invitation.public_id == row.aggregate_public_id))
    return settings, identifier, account_id


@pytest.mark.parametrize('kind', ['invitation', 'auth_code', 'order', 'transfer'])
@pytest.mark.parametrize('prepare_first', [False, True])
def test_final_prepare_and_revocation_have_real_commit_order(notification_case, monkeypatch, kind, prepare_first):
    ctx = notification_case
    settings, identifier, account_id = setup_delivery(ctx, monkeypatch, kind)
    worker = notification_worker if kind in {'order','transfer'} else mail_worker
    transfer = prepare_transfer(ctx) if kind == 'transfer' else None
    # Keep both actual run_once and smtp_sender: only the external transport is replaced.
    monkeypatch.setattr(worker, 'smtp_sender', mail_worker.smtp_sender)
    claim_committed, allow_prepare = Event(), Event()
    prepare_ready, allow_prepare_commit = Event(), Event()
    smtp_entered, allow_smtp = Event(), Event()
    connections = queue.Queue(); revoked_connection = queue.Queue()
    sessions, smtp_calls = [], []

    class WorkerSession(Session):
        def __init__(self, phase):
            super().__init__(bind=ctx.engine)
            self.phase = phase
        def commit(self):
            if self.phase == 2:
                prepare_ready.set()
                if prepare_first:
                    assert allow_prepare_commit.wait(8), 'Prepare commit gate was not released'
            super().commit()
            if self.phase == 1:
                claim_committed.set()
                assert allow_prepare.wait(8), 'Post-claim gate was not released'

    def factory():
        db = WorkerSession(len(sessions)+1); sessions.append(db)
        if db.phase == 2:
            connections.put(db.scalar(text('SELECT CONNECTION_ID()')))
        return db

    def no_worker_transaction():
        assert len(sessions) == 2
        assert all(not db.in_transaction() for db in sessions)

    class SMTP:
        def __init__(self, host, port, **kwargs):
            assert prepare_first, 'Revocation-first must never enter SMTP'
            assert host == settings.PORTAL_SMTP_HOST and port == 465 and kwargs['timeout'] == 15
            no_worker_transaction(); smtp_calls.append('connect'); smtp_entered.set()
            assert allow_smtp.wait(8), 'SMTP gate was not released'
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def login(self, username, password):
            no_worker_transaction()
            assert username == settings.PORTAL_SMTP_USERNAME and password == settings.PORTAL_SMTP_PASSWORD
            smtp_calls.append('login')
        def send_message(self, message):
            no_worker_transaction()
            assert message['Message-ID'] == '<portal-'+identifier+'@leshine.invalid>'
            if kind in {'order','transfer'}:
                assert message['To'] == 'representative@example.test'
                assert all(value not in message.get_content() for value in ('81.00', '27.0000', '10 Test Street', 'token='))
            smtp_calls.append('send')
            return {}
    monkeypatch.setattr(mail_worker.smtplib, 'SMTP_SSL', SMTP)

    def revoke(db):
        if kind == 'transfer':
            workflow_service.transfer_primary_owner(db, customer_id=transfer['customer_id'],
                new_user_id=transfer['new_owner'], operated_by=ctx.admin, change_reason='Controlled notification ownership race')
        elif kind == 'order':
            result = employee_admin.update_user(ctx.actor, UserUpdateRequest(is_active=False), db, {'sub':str(ctx.admin)})
            assert result.code == 200
        else:
            account = db.get(Account, account_id)
            result = admin_service.update_account(db, ctx.admin, account.public_id, account.row_version,
                AccountUpdate(status='disabled', reason='Controlled notification authorization race'))
            assert result['status'] == 'disabled'
        db.commit()

    def revoke_in_thread():
        with Session(ctx.engine) as db:
            revoked_connection.put(db.scalar(text('SELECT CONNECTION_ID()')))
            revoke(db)
        return 'revoked'

    baseline_orders = snapshot(ctx)
    # Intentional revocation writes audit rows, so compare all immutable business tables separately below.
    original_financial = baseline_orders[:10]
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(worker.run_once, factory)
        revoking = None
        try:
            assert claim_committed.wait(8)
            with Session(ctx.engine) as db:
                row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
                assert row.status == 'sending' and row.attempt_count == 1 and row.lease_token
            if prepare_first:
                allow_prepare.set(); assert prepare_ready.wait(8)
                revoking = executor.submit(revoke_in_thread)
                wait_for_lock(ctx.engine, revoked_connection.get(timeout=3))
                assert not revoking.done() and not future.done()
                allow_prepare_commit.set(); assert smtp_entered.wait(8)
                assert revoking.result(timeout=6) == 'revoked'
                # The external transport is still blocked; the genuine revocation has committed.
                assert not future.done()
                after_revocation = business_snapshot(ctx)
                allow_smtp.set()
            else:
                with Session(ctx.engine) as db:
                    lock_authority(db, force=True)
                    if kind not in {'order','transfer'}:
                        account = db.get(Account, account_id)
                        admin_service.update_account(db, ctx.admin, account.public_id, account.row_version,
                            AccountUpdate(status='disabled', reason='Revoke before final mail preparation'))
                    allow_prepare.set()
                    wait_for_lock(ctx.engine, connections.get(timeout=3))
                    assert not future.done()
                    # Employee endpoint owns its commit; invoke it only after observing prepare's wait.
                    if kind in {'order','transfer'}: revoke(db)
                    else: db.commit()
                after_revocation = business_snapshot(ctx)
            result = future.result(timeout=8)
            assert result == ('sent' if prepare_first else 'cancelled')
        finally:
            allow_prepare.set(); allow_prepare_commit.set(); allow_smtp.set()
    assert smtp_calls == (['connect','login','send'] if prepare_first else [])
    assert business_snapshot(ctx) == after_revocation
    with Session(ctx.engine) as db:
        row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
        assert row.status == ('sent' if prepare_first else 'cancelled') and row.attempt_count == 1
        assert row.secret_envelope is None and row.secret_key_version is None
        assert row.lease_token is None and row.lease_until is None
        if not prepare_first: assert row.last_error_code == 'AUTHORIZATION_CHANGED'
        if kind == 'transfer': assert db.get(CustomerAccess, ctx.access_id).status == 'review_required'
        elif kind == 'order': assert db.get(ArkUser, ctx.actor).is_active is False
        else: assert db.get(Account, account_id).status == 'disabled'
    current = snapshot(ctx)
    assert current[:10] == original_financial
    assert worker.run_once(factory) == 'idle'
    assert business_snapshot(ctx) == after_revocation


def prepare_transfer(ctx):
    metadata = MetaData()
    for model in (CustomerAction, CustomerOpportunity, CustomerEvent):
        Table(model.__tablename__, metadata, *(Column(c.name,c.type,primary_key=c.primary_key,
            nullable=c.nullable,default=c.default,server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(ctx.engine, checkfirst=True)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        db.get(CustomerAccount, access.customer_id).profile_input_seq = 0
        new = ArkUser(username='notification-owner-'+uuid4().hex[:16], password_hash='not-a-login',
            real_name='New notification owner', email='new-representative@example.test', is_active=True)
        db.add(new); db.flush()
        for role_id in db.scalars(select(ArkUserRole.role_id).where(ArkUserRole.user_id == ctx.actor)).all():
            db.add(ArkUserRole(user_id=new.id, role_id=role_id))
        result = {'new_owner':new.id, 'customer_id':access.customer_id, 'access_id':access.public_id}
        db.commit()
        return result


def test_reviewed_reenabled_transfer_resolves_pending_mail_to_new_owner(notification_case, monkeypatch):
    ctx = notification_case
    _, identifier, _ = setup_delivery(ctx, monkeypatch, 'order')
    transfer = prepare_transfer(ctx)
    with Session(ctx.engine) as db:
        child = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
        request_id = child.aggregate_public_id
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        original_order = {column.name:getattr(order,column.name) for column in OrderRequest.__table__.columns}
        revision_evidence = tuple(db.execute(select(*Revision.__table__.columns).where(Revision.request_id == order.id)).all())
        line_evidence = tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id == order.active_revision_id)).all())
        assigned = workflow_service.transfer_primary_owner(db, customer_id=transfer['customer_id'],
            new_user_id=transfer['new_owner'], operated_by=ctx.admin, change_reason='Reviewed notification ownership handoff')
        assignment_id = assigned.id; db.commit()
        access = db.get(CustomerAccess, ctx.access_id)
        assert access.status == 'review_required' and db.get(PortalSession, ctx.session_id).revoked_at is not None
        review = binding_review_service.context(db, ctx.admin, transfer['access_id'])
        handed = ownership_service.transfer_customer(db, ctx.admin, transfer['access_id'], review['row_version'],
            TransferInput(review_fingerprint=review['review_fingerprint'], assignment_id=str(assignment_id),
                pending_request_ids=[request_id], history_policy='remove', reason='Confirm notification recipient handoff'))
        db.commit()
        assert handed['status'] == 'suspended' and handed['reassigned_request_ids'] == [request_id]
        admin_service.update_customer(db, ctx.admin, transfer['access_id'], handed['row_version'],
            CustomerUpdate(status='enabled', capabilities={'can_order':True,'can_view_price':True},reason='Reopen reviewed customer'))
        db.commit()
        access = db.get(CustomerAccess, ctx.access_id)
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        assert access.sales_user_id == order.servicing_user_id == transfer['new_owner']
        assert order.sales_user_id_snapshot == ctx.actor and order.status == 'submitted' and order.invoice_id is None
        allowed_changes = {'servicing_user_id','status','accepted_revision_id','row_version'}
        assert {column.name:getattr(order,column.name) for column in OrderRequest.__table__.columns if column.name not in allowed_changes} == {
            name:value for name,value in original_order.items() if name not in allowed_changes}
        assert tuple(db.execute(select(*Revision.__table__.columns).where(Revision.request_id == order.id)).all()) == revision_evidence
        assert tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id == order.active_revision_id)).all()) == line_evidence
        assert db.get(PortalSession,ctx.session_id).revoked_at is not None
        assert db.scalar(select(OutboxEvent.status).where(OutboxEvent.public_id == identifier)) == 'pending'
    baseline = business_snapshot(ctx); business = snapshot(ctx)
    with Session(ctx.engine) as db:
        grants = db.execute(select(*HistoryGrant.__table__.columns).order_by(HistoryGrant.id)).all()
    sessions, phases = [], []
    def factory():
        db = Session(ctx.engine); sessions.append(db); return db
    def no_transaction():
        assert len(sessions) == 2 and all(not db.in_transaction() for db in sessions)
    class SMTP:
        def __init__(self,*args,**kwargs): no_transaction(); phases.append('connect')
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def login(self,*args): no_transaction(); phases.append('login')
        def send_message(self,message):
            no_transaction(); phases.append('send')
            assert message['To'] == 'new-representative@example.test'
            assert message['Message-ID'] == '<portal-'+identifier+'@leshine.invalid>'
            assert all(value not in message.get_content() for value in ('81.00','27.0000','10 Test Street','token='))
            return {}
    monkeypatch.setattr(mail_worker.smtplib, 'SMTP_SSL', SMTP)
    monkeypatch.setattr(notification_worker, 'smtp_sender', mail_worker.smtp_sender)
    assert notification_worker.run_once(factory) == 'sent'
    assert phases == ['connect','login','send']
    assert business_snapshot(ctx) == baseline and snapshot(ctx)[:11] == business[:11]
    with Session(ctx.engine) as db:
        assert db.execute(select(*HistoryGrant.__table__.columns).order_by(HistoryGrant.id)).all() == grants
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == identifier))
        assert event.status == 'sent' and event.attempt_count == 1 and event.lease_token is None
        assert 'new-representative' not in str(event.payload_json)
