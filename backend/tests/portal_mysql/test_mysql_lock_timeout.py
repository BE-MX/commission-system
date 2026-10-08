"""T64 real MySQL waits, full rollback, pool hygiene and original command recovery."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from threading import Event

import httpx
import pytest
from fastapi import FastAPI
import queue
import time

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.portal import authority, auth_service as auth, router
from app.portal import lock_timeout
from app.portal.errors import PortalError
from app.portal.models import Account, AuditEvent, OrderRequest, OutboxEvent, Quote, RequestLine, Revision
from test_mysql_concurrency import wait_for_lock


def test_barrier_timeout_is_bounded_safe_and_requires_full_rollback(trade):
    ctx = trade
    authority.get_settings().PORTAL_LOCK_WAIT_SECONDS = 1
    started = queue.Queue()
    with Session(ctx.engine) as db:
        before = db.get(Account, ctx.account_id).contact_name
    def competing():
        # Keep the same physical connection across rollback; Session(engine) may
        # otherwise check out a different pool entry and cannot prove restoration.
        with ctx.engine.connect() as connection, Session(connection) as db:
            # Deliberately stage an unrelated write before taking the barrier to
            # prove a statement-only timeout cannot be accidentally committed.
            db.execute(text('SET SESSION innodb_lock_wait_timeout = 3'))
            row = db.get(Account, ctx.account_id)
            row.contact_name = 'Must roll back'
            db.flush()
            started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            began = time.perf_counter()
            try:
                authority.lock_authority(db)
                return {'outcome':'acquired'}
            except PortalError as error:
                elapsed = time.perf_counter() - began
                try:
                    db.commit()
                    commit = 'committed'
                except PortalError as commit_error:
                    commit = commit_error.code
                db.rollback()
                assert db.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == 3
                assert db.get(Account, ctx.account_id, populate_existing=True).contact_name == before
                return {'outcome':error.code, 'status':error.status, 'elapsed':elapsed, 'commit':commit}
            except OperationalError as error:
                db.rollback()
                return {'outcome':'raw_mysql_error', 'mysql_code':error.orig.args[0],
                    'elapsed':time.perf_counter()-began}
            finally:
                db.rollback()
    with Session(ctx.engine) as first, ThreadPoolExecutor(max_workers=1) as executor:
        authority.lock_authority(first)
        future = executor.submit(competing)
        try:
            wait_for_lock(ctx.engine, started.get(timeout=3))
            result = future.result(timeout=5)
            assert result['outcome'] == 'TRANSACTION_BUSY', result
            assert result['status'] == 503 and result['commit'] == 'TRANSACTION_BUSY', result
            assert .8 <= result['elapsed'] < 2.8, result
        finally:
            first.rollback()
    with Session(ctx.engine) as db:
        assert db.get(Account, ctx.account_id).contact_name == before


@pytest.mark.parametrize('finish', ['commit','rollback','close','savepoint_commit','savepoint_rollback',
    'external_savepoint_commit','external_savepoint_rollback'])
def test_timeout_policy_restores_same_connection_and_survives_savepoints(migrated, monkeypatch, finish):
    monkeypatch.setattr(authority, 'get_settings', lambda: SimpleNamespace(PORTAL_ENABLED=True, PORTAL_LOCK_WAIT_SECONDS=1))
    with migrated.connect() as connection:
        original = connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout'))
        identifier = connection.scalar(text('SELECT CONNECTION_ID()'))
        connection.exec_driver_sql('SET SESSION innodb_lock_wait_timeout = 17'); connection.commit()
        external = connection.begin() if finish.startswith('external_') else None
        try:
            with Session(connection, join_transaction_mode='create_savepoint') as db:
                authority.lock_authority(db)
                assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == 1
                if finish.startswith('savepoint_'):
                    nested = db.begin_nested()
                    authority.lock_authority(db)
                    if finish.endswith('commit'): nested.commit()
                    else: nested.rollback()
                    assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == 1
                    authority.lock_authority(db)  # Outer scope is still valid.
                if finish in {'rollback','external_savepoint_rollback'}: db.rollback()
                elif finish != 'close': db.commit()
            if external is not None:
                assert connection.in_transaction()
                assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == 1
                external.rollback()
            assert connection.scalar(text('SELECT CONNECTION_ID()')) == identifier
            assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == 17
            assert lock_timeout._STATE not in connection.info
        finally:
            connection.rollback()
            connection.exec_driver_sql('SET SESSION innodb_lock_wait_timeout = %s', (original,))
            connection.commit()


def test_unrelated_mysql_error_and_installed_off_authority_preserve_transaction_contract(migrated, monkeypatch):
    settings = SimpleNamespace(PORTAL_ENABLED=False, PORTAL_LOCK_WAIT_SECONDS=1)
    monkeypatch.setattr(authority, 'get_settings', lambda: settings)
    with migrated.connect() as connection, Session(connection) as db:
        original = connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout'))
        row = authority.lock_authority(db)
        assert row is not None
        assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == 1
        assert lock_timeout._STATE in connection.info
        settings.PORTAL_ENABLED = True
        assert authority.lock_authority(db) is row
        with pytest.raises(OperationalError) as failure:
            db.execute(text('SELECT portal_test_column_that_does_not_exist'))
        assert failure.value.orig.args[0] == 1054
        assert not connection.info[lock_timeout._STATE]['timed_out']
        db.rollback()
        connection.rollback()
        assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == original


def test_nonparticipating_mysql_lock_timeout_remains_operational_error(trade):
    ctx = trade; started = queue.Queue()
    def competing():
        with ctx.engine.connect() as connection, Session(connection) as db:
            original = connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout'))
            try:
                db.execute(text('SET SESSION innodb_lock_wait_timeout = 1'))
                started.put(db.scalar(text('SELECT CONNECTION_ID()')))
                with pytest.raises(OperationalError) as failure:
                    db.scalar(select(Account).where(Account.id == ctx.account_id).with_for_update())
                assert failure.value.orig.args[0] == 1205
                assert lock_timeout._STATE not in connection.info
                db.rollback()
            finally:
                connection.rollback()
                connection.exec_driver_sql('SET SESSION innodb_lock_wait_timeout = %s', (original,)); connection.commit()
    with Session(ctx.engine) as first, ThreadPoolExecutor(max_workers=1) as executor:
        first.scalar(select(Account).where(Account.id == ctx.account_id).with_for_update())
        future = executor.submit(competing)
        try:
            wait_for_lock(ctx.engine, started.get(timeout=3)); future.result(timeout=3)
        finally: first.rollback()


def test_row_wait_after_authority_uses_same_bound_and_full_rollback(trade):
    ctx = trade; started = queue.Queue(); authority.get_settings().PORTAL_LOCK_WAIT_SECONDS = 1
    def competing():
        with ctx.engine.connect() as connection, Session(connection) as db:
            original = connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout'))
            authority.lock_authority(db)
            started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            with pytest.raises(PortalError) as failure:
                db.scalar(select(Account).where(Account.id == ctx.account_id).with_for_update())
            assert failure.value.code == 'TRANSACTION_BUSY' and failure.value.status == 503
            db.rollback(); connection.rollback()
            assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == original
    # Deliberate legacy row lock without authority proves downstream waits are bounded.
    with Session(ctx.engine) as first, ThreadPoolExecutor(max_workers=1) as executor:
        first.scalar(select(Account).where(Account.id == ctx.account_id).with_for_update())
        future = executor.submit(competing)
        try:
            wait_for_lock(ctx.engine, started.get(timeout=3)); future.result(timeout=3)
        finally: first.rollback()


def test_pool_reset_restores_marked_dbapi_connection(migrated):
    # A single-entry pool proves the actual reset event and physical reuse;
    # raw DBAPI checkout/return never calls Engine.rollback.
    from sqlalchemy import create_engine
    engine = create_engine(migrated.url, pool_size=1, max_overflow=0, hide_parameters=True)
    try:
        raw = engine.raw_connection(); info = raw.info
        with raw.cursor() as cursor:
            cursor.execute('SELECT CONNECTION_ID(), @@SESSION.innodb_lock_wait_timeout')
            identifier, original = cursor.fetchone()
            cursor.execute('SET SESSION innodb_lock_wait_timeout = 1')
        info[lock_timeout._STATE] = {'original':original, 'seconds':1, 'timed_out':False}
        raw.close()
        assert lock_timeout._STATE not in info
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT CONNECTION_ID()')) == identifier
            assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')) == original
    finally: engine.dispose()


def test_closed_dbapi_connection_is_invalidated_on_restore(trade):
    ctx = trade
    with Session(ctx.engine) as db:
        before = db.get(Account, ctx.account_id).contact_name
    with ctx.engine.connect() as connection, Session(connection) as db:
        authority.lock_authority(db)
        db.get(Account, ctx.account_id).contact_name = 'Must not survive connection loss'; db.flush()
        connection.connection.dbapi_connection.close()
        with pytest.raises(Exception): db.commit()
        assert connection.invalidated
        db.rollback()
    with Session(ctx.engine) as db:
        assert db.get(Account, ctx.account_id).contact_name == before


def test_http_timeout_returns_safe_503_and_recovers_original_key(trade, monkeypatch):
    ctx = trade; settings = auth.get_settings(); settings.PORTAL_LOCK_WAIT_SECONDS = 1
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    app = FastAPI(); app.include_router(router.router, prefix='/api/portal/v1')
    started = queue.Queue()
    def database():
        with Session(ctx.engine) as db:
            started.put(db.scalar(text('SELECT CONNECTION_ID()')))
            yield db
    app.dependency_overrides[get_db] = database
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (OrderRequest, Revision, RequestLine, Quote, AuditEvent, OutboxEvent))
    headers = {'X-Real-IP':'127.0.0.1','Origin':settings.PORTAL_ORIGIN,'X-Portal-CSRF':ctx.csrf,
        'Idempotency-Key':str(ctx.key),'Cookie':router.cookie_name('session')+'='+ctx.token}
    async def request(method, path):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1',51000)),
            base_url=settings.PORTAL_ORIGIN, headers=headers) as client:
            return await client.request(method, '/api/portal/v1'+path,
                json=ctx.body.model_dump(mode='json') if method=='POST' else None)
    baseline = snapshot()
    with Session(ctx.engine) as first, ThreadPoolExecutor(max_workers=1) as executor:
        authority.lock_authority(first)
        future = executor.submit(asyncio.run, request('POST','/orders'))
        try:
            wait_for_lock(ctx.engine, started.get(timeout=3)); response = future.result(timeout=4)
            assert response.status_code == 503 and response.json()['code'] == 503
            assert response.json()['data']['error_code'] == 'TRANSACTION_BUSY'
            assert response.json()['data']['retryable'] is True and 'no-store' in response.headers['cache-control']
            assert all(secret not in response.text for secret in ('1205','ark_order_portal','SELECT','Must roll back'))
        finally: first.rollback()
    assert snapshot() == baseline
    assert asyncio.run(request('GET','/orders/by-key/'+str(ctx.key))).status_code == 404
    original = asyncio.run(request('POST','/orders'))
    replay = asyncio.run(request('POST','/orders'))
    assert original.status_code == 201 and replay.status_code == 200
    assert replay.json()['data'] == {**original.json()['data'],'replayed':True}
    with Session(ctx.engine) as db:
        assert len(db.scalars(select(OrderRequest).where(OrderRequest.access_id==ctx.access_id)).all()) == 1


@pytest.mark.parametrize('registered',[False,True])
def test_upstream_user_write_row_timeout_uses_shared_safe_handler(trade, monkeypatch, registered):
    from app.auth import admin_router as employee_admin
    from app.auth.dependencies import get_current_user
    from app.auth.models import ArkUser
    from app.portal.errors import register_portal_error_handler
    from app.portal.models import AuthorityBarrier
    ctx = trade; authority.get_settings().PORTAL_LOCK_WAIT_SECONDS = 1
    app = FastAPI(); app.include_router(employee_admin.router, prefix='/api/admin')
    if registered: register_portal_error_handler(app)
    # JWT parsing is synthetic here; begin_employee_authority_write still reads
    # the actual current employee, role and permissions from isolated MySQL.
    app.dependency_overrides[get_current_user] = lambda: {'sub':str(ctx.admin),'roles':['super_admin']}
    started = queue.Queue()
    def database():
        with Session(ctx.engine) as db:
            started.put(db.scalar(text('SELECT CONNECTION_ID()'))); yield db
    app.dependency_overrides[get_db] = database
    with Session(ctx.engine) as db:
        original_name = db.get(ArkUser,ctx.actor).real_name
        original_version = db.scalar(select(AuthorityBarrier.version).where(AuthorityBarrier.code=='authority'))
    async def update():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),
            base_url='https://ark.example.test') as client:
            return await client.put('/api/admin/users/'+str(ctx.actor),json={'is_active':False,'real_name':'Never commit'})
    # Legacy profile/password writes do not take authority; exercise precisely
    # the downstream user row wait after the administrator has acquired it.
    with Session(ctx.engine) as first, ThreadPoolExecutor(max_workers=1) as executor:
        first.scalar(select(ArkUser).where(ArkUser.id==ctx.actor).with_for_update())
        future = executor.submit(asyncio.run,update())
        try:
            wait_for_lock(ctx.engine,started.get(timeout=3)); response = future.result(timeout=4)
            assert response.status_code == (503 if registered else 500)
            if registered:
                assert response.json()['data']['error_code']=='TRANSACTION_BUSY'
                assert response.json()['data']['retryable'] is True
                assert 'no-store' in response.headers['cache-control']
                assert '交易服务繁忙' in response.json()['message']
                assert all(secret not in response.text for secret in ('1205','UPDATE','ark_users','Never commit'))
        finally: first.rollback()
    with Session(ctx.engine) as db:
        user = db.get(ArkUser,ctx.actor)
        assert user.is_active and user.real_name==original_name
        assert db.scalar(select(AuthorityBarrier.version).where(AuthorityBarrier.code=='authority'))==original_version


def test_timed_out_external_savepoint_cannot_commit_outer_writes(trade):
    ctx=trade; authority.get_settings().PORTAL_LOCK_WAIT_SECONDS=1; started=queue.Queue()
    with Session(ctx.engine) as db: original_name=db.get(Account,ctx.account_id).contact_name
    def competing():
        with ctx.engine.connect() as connection:
            original=connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout')); connection.commit()
            outer=connection.begin()
            connection.execute(Account.__table__.update().where(Account.id==ctx.account_id).values(contact_name='Outer must roll back'))
            with Session(connection,join_transaction_mode='create_savepoint') as db:
                started.put(db.scalar(text('SELECT CONNECTION_ID()')))
                with pytest.raises(PortalError) as failure: authority.lock_authority(db)
                assert failure.value.code=='TRANSACTION_BUSY'
                db.rollback()  # Only the savepoint is closed; root stays rollback-only.
            assert connection.in_transaction() and connection.info[lock_timeout._STATE]['timed_out']
            with pytest.raises(PortalError) as failure: outer.commit()
            assert failure.value.code=='TRANSACTION_BUSY'
            connection.rollback()
            assert connection.scalar(text('SELECT @@SESSION.innodb_lock_wait_timeout'))==original
            assert connection.scalar(select(Account.contact_name).where(Account.id==ctx.account_id))==original_name
    with Session(ctx.engine) as first,ThreadPoolExecutor(max_workers=1) as executor:
        authority.lock_authority(first); future=executor.submit(competing)
        try:
            wait_for_lock(ctx.engine,started.get(timeout=3)); future.result(timeout=4)
        finally: first.rollback()
    with Session(ctx.engine) as db: assert db.get(Account,ctx.account_id).contact_name==original_name


@pytest.mark.parametrize('kind',['invitation','auth_code','order','mapping'])
def test_mail_prepare_timeout_preserves_event_and_retries_without_new_business(trade, monkeypatch, kind):
    from datetime import datetime,timedelta
    from app.core import time as platform_time
    from app.portal import mail_worker,notification_worker
    from test_mysql_notification_authority import setup_delivery
    from test_mysql_notification_process import business_snapshot
    ctx=trade; settings,identifier,_=setup_delivery(ctx,monkeypatch,kind)
    settings.PORTAL_LOCK_WAIT_SECONDS=1
    worker=notification_worker if kind in {'order','mapping'} else mail_worker
    baseline=business_snapshot(ctx); started=queue.Queue(); sessions=[]; calls=[]
    with Session(ctx.engine) as db:
        row=db.scalar(select(OutboxEvent).where(OutboxEvent.public_id==identifier))
        original_secret=(row.secret_envelope,row.secret_key_version,row.secret_expires_at)
    claim_committed=Event(); allow_prepare=Event(); prepare_failed=Event(); allow_finish=Event()
    class WorkerSession(Session):
        def commit(self):
            super().commit()
            if self.phase==1:
                claim_committed.set()
                assert allow_prepare.wait(5)
    def factory():
        phase=len(sessions)+1
        if phase==3:
            prepare_failed.set()
            assert allow_finish.wait(5)
        db=WorkerSession(ctx.engine); db.phase=phase; sessions.append(db)
        if phase==2: started.put(db.scalar(text('SELECT CONNECTION_ID()')))
        return db
    def sender(mail):
        assert all(not db.in_transaction() for db in sessions)
        calls.append(mail.message_id)
        return True
    with Session(ctx.engine) as first,ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(worker.run_once,factory,sender)
        try:
            assert claim_committed.wait(5)
            with Session(ctx.engine) as db:
                claimed=db.scalar(select(OutboxEvent).where(OutboxEvent.public_id==identifier))
                assert claimed.status=='sending' and claimed.attempt_count==1
            authority.lock_authority(first); allow_prepare.set()
            wait_for_lock(ctx.engine,started.get(timeout=3))
            assert prepare_failed.wait(4)
            first.rollback(); allow_finish.set()
            assert future.result(timeout=4)=='pending'
        finally:
            first.rollback(); allow_prepare.set(); allow_finish.set()
    assert not calls and business_snapshot(ctx)==baseline
    with Session(ctx.engine) as db:
        row=db.scalar(select(OutboxEvent).where(OutboxEvent.public_id==identifier))
        assert row.attempt_count==1 and row.last_error_code=='AUTHORITY_UNAVAILABLE'
        assert row.lease_until is None and row.lease_token is None
        assert (row.secret_envelope,row.secret_key_version,row.secret_expires_at)==original_secret
        next_instant=row.next_attempt_at+timedelta(seconds=1)
    class RetryClock(datetime):
        @classmethod
        def now(cls,tz=None):
            value=next_instant.replace(tzinfo=platform_time.BEIJING_TIMEZONE)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
    monkeypatch.setattr(platform_time,'datetime',RetryClock)
    assert worker.run_once(factory,sender)=='sent'
    assert calls==['<portal-'+identifier+'@leshine.invalid>'] and business_snapshot(ctx)==baseline
    with Session(ctx.engine) as db:
        row=db.scalar(select(OutboxEvent).where(OutboxEvent.public_id==identifier))
        assert row.status=='sent' and row.attempt_count==2
        assert row.secret_envelope is None and row.secret_key_version is None
