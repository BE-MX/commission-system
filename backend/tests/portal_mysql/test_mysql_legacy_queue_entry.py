"""Actual legacy queue body/owned MySQL, no supplier or application startup."""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select, text, event, update, Column, MetaData, Table
from sqlalchemy.orm import Session, sessionmaker

from app.invoice import outbound_mode as mode, outbound_task_service as tasks
from app.invoice.models import Invoice, InvoiceSyncLog, OkkiOutboundTask
from test_mysql_outbound_mode import boot, install_record, owner, lock_owner  # noqa: F401


@pytest.fixture
def queue(boot, service_schema):
    metadata=MetaData()
    for model in (InvoiceSyncLog, OkkiOutboundTask):
        Table(model.__tablename__,metadata,*(Column(c.name,c.type,primary_key=c.primary_key,
            nullable=c.nullable,default=c.default,server_default=c.server_default) for c in model.__table__.columns))
    metadata.create_all(boot.engine)
    boot.settings.PORTAL_ENABLED = False
    with boot.factory() as db:
        db.execute(update(Invoice).values(outbound_auto_requested=0))
        invoice = Invoice(invoice_no='LEGACY-' + uuid4().hex[:20], order_type='production',
            customer_id='owned-customer', customer_name='Owned Customer', sales_user_id=1,
            sales_user_name='Owned Sales', invoice_date=date(2026,10,6), currency='USD',
            xiaoman_order_id=str(int(uuid4().hex[:12],16)), sync_status='synced',
            status='draft', outbound_auto_requested=1)
        db.add(invoice); db.flush()
        db.add(InvoiceSyncLog(invoice_id=invoice.id, action='create', success=1))
        db.commit()
        identity, order = invoice.id, invoice.xiaoman_order_id
    yield identity, order
    with boot.factory() as db:
        db.execute(text('DELETE FROM ark_okki_outbound_tasks WHERE invoice_id=:id'), {'id':identity})
        db.execute(text('DELETE FROM ark_invoice_sync_logs WHERE invoice_id=:id'), {'id':identity})
        db.execute(text('DELETE FROM ark_invoices WHERE id=:id'), {'id':identity})
        db.commit()


def queued(boot, identity):
    with boot.factory() as db:
        return [(row.invoice_id,row.order_id,row.status) for row in db.scalars(
            select(OkkiOutboundTask).where(OkkiOutboundTask.invoice_id==identity))]


def test_caller_session_cannot_bypass_persistent_mode(boot,queue):
    install_record(boot)
    before = boot.snapshot()
    with boot.factory() as db:
        try:
            with pytest.raises(RuntimeError,match='owned session factory'):
                tasks.reconcile_missing_outbound_tasks(db)
        finally:
            db.rollback()
    assert boot.snapshot()==before and queued(boot,queue[0])==[]


def test_public_entry_queues_actual_task_once_under_fence_until_commit(boot,queue):
    observed=[]
    def before_commit(db):
        if db.get_bind() is not boot.engine or db.in_nested_transaction(): return
        observed.append(lock_owner(boot))
        assert observed[-1] is not None
        boot.settings.PORTAL_ENABLED=True
        try:
            with pytest.raises(RuntimeError,match='bootstrap is unavailable'):
                boot.initialize()
        finally: boot.settings.PORTAL_ENABLED=False
    event.listen(boot.factory.class_, 'before_commit', before_commit)
    try:
        result=tasks.reconcile_missing_outbound_tasks(boot.factory)
    finally: event.remove(boot.factory.class_, 'before_commit', before_commit)
    assert result=={'scanned':1,'enqueued':1,'skipped':0}
    assert len(observed)==1 and lock_owner(boot) is None and boot.value() is None
    assert queued(boot,queue[0])==[(queue[0],queue[1],'pending')]
    before=boot.snapshot()
    assert tasks.reconcile_missing_outbound_tasks(boot.factory)=={'scanned':0,'enqueued':0,'skipped':0}
    assert boot.snapshot()==before


@pytest.mark.parametrize('enabled',[True,False])
def test_actual_body_is_not_entered_after_persistent_mode_even_if_feature_off(boot,queue,enabled):
    install_record(boot);boot.settings.PORTAL_ENABLED=enabled
    before=boot.snapshot()
    assert tasks.reconcile_missing_outbound_tasks(boot.factory)=={'status':'disabled','enqueued':0}
    assert queued(boot,queue[0])==[] and boot.snapshot()==before and lock_owner(boot) is None


def test_other_actual_owner_keeps_public_queue_busy_without_writes(boot,queue):
    before=boot.snapshot()
    with owner(boot.engine) as connection:
        expected=connection.scalar(text('SELECT CONNECTION_ID()'));connection.rollback()
        assert tasks.reconcile_missing_outbound_tasks(boot.factory)=={'status':'busy','enqueued':0}
        assert lock_owner(boot)==expected and boot.snapshot()==before
    assert lock_owner(boot) is None


def test_stale_factory_session_is_rejected_without_committing_caller_changes(boot,queue):
    before=boot.snapshot()
    with boot.factory() as db:
        assert mode.read_mode(db)=='legacy'
        db.get(Invoice,queue[0]).remark='Caller-owned dirty change'
        with pytest.raises(RuntimeError,match='fresh owned session'):
            tasks.reconcile_missing_outbound_tasks(lambda:db)
    assert boot.snapshot()==before and queued(boot,queue[0])==[]


@pytest.mark.parametrize('state',[('cancelled','production'),('cancel_pending','production'),('draft','presale')])
def test_real_selection_does_not_queue_cancelled_or_presale(boot,queue,state):
    with boot.factory() as db:
        row=db.get(Invoice,queue[0]);row.status,row.order_type=state;db.commit()
    before=boot.snapshot()
    assert tasks.reconcile_missing_outbound_tasks(boot.factory)=={'scanned':0,'enqueued':0,'skipped':0}
    assert boot.snapshot()==before and queued(boot,queue[0])==[]


@pytest.mark.parametrize('kind',[RuntimeError,KeyboardInterrupt,SystemExit])
def test_real_queue_flush_is_rolled_back_before_fence_release_on_failure(boot,queue,kind):
    before=boot.snapshot();observed=[]
    def fail(db):
        if db.get_bind() is not boot.engine or db.in_nested_transaction(): return
        db.flush()
        assert db.scalar(select(OkkiOutboundTask.id).where(OkkiOutboundTask.invoice_id==queue[0])) is not None
        raise kind('Owned interrupt before commit')
    def rolled_back(db):
        if db.get_bind() is not boot.engine or db.in_nested_transaction():return
        observed.append(lock_owner(boot))
    event.listen(boot.factory.class_,'before_commit',fail)
    event.listen(boot.factory.class_,'after_rollback',rolled_back)
    try:
        with pytest.raises(kind,match='Owned interrupt before commit'):
            tasks.reconcile_missing_outbound_tasks(boot.factory)
    finally:
        event.remove(boot.factory.class_,'before_commit',fail)
        event.remove(boot.factory.class_,'after_rollback',rolled_back)
    assert len(observed)==1 and observed[0] is not None
    assert lock_owner(boot) is None and queued(boot,queue[0])==[] and boot.snapshot()==before


@pytest.mark.parametrize('limit',[0,201,True,'1',None])
def test_bad_limits_are_rejected_before_any_transaction(boot,queue,limit):
    before=boot.snapshot()
    with pytest.raises(ValueError,match='Invalid legacy reconciliation limit'):
        tasks.reconcile_missing_outbound_tasks(boot.factory,limit=limit)
    assert boot.snapshot()==before and lock_owner(boot) is None


@pytest.mark.parametrize('kind',[KeyboardInterrupt,SystemExit])
def test_rollback_interrupt_closes_business_socket_before_releasing_fence(boot,queue,kind):
    before=boot.snapshot();state={'fault':False,'connection':None};observed=[]
    class InterruptedSession(Session):
        def rollback(self):
            if state['fault']:
                state['fault']=False
                raise kind('Owned rollback interruption')
            return super().rollback()
    factory=sessionmaker(bind=boot.engine,class_=InterruptedSession,expire_on_commit=False)
    def before_commit(db):
        if db.in_nested_transaction():return
        db.flush()
        assert db.scalar(select(OkkiOutboundTask.id).where(OkkiOutboundTask.invoice_id==queue[0])) is not None
        state['connection']=db.scalar(text('SELECT CONNECTION_ID()'))
        state['fault']=True
        raise RuntimeError('Owned failed root commit')
    with boot.engine.connect() as observer:
        observer_id=observer.scalar(text('SELECT CONNECTION_ID()'));observer.rollback()
        def before_release(connection,cursor,statement,parameters,context,executemany):
            if not statement.startswith('SELECT RELEASE_LOCK'):return
            assert state['connection'] is not None and state['connection']!=observer_id
            alive=observer.scalar(text('SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID=:id'),{'id':state['connection']})
            count=observer.scalar(text('SELECT COUNT(*) FROM ark_okki_outbound_tasks WHERE invoice_id=:id'),{'id':queue[0]})
            observer.rollback();observed.append((alive,count))
        event.listen(InterruptedSession,'before_commit',before_commit)
        event.listen(boot.engine,'before_cursor_execute',before_release)
        try:
            with pytest.raises(kind,match='Owned rollback interruption'):
                tasks.reconcile_missing_outbound_tasks(factory)
        finally:
            event.remove(InterruptedSession,'before_commit',before_commit)
            event.remove(boot.engine,'before_cursor_execute',before_release)
    assert observed==[(0,0)]
    assert lock_owner(boot) is None and boot.snapshot()==before and queued(boot,queue[0])==[]
    assert tasks.reconcile_missing_outbound_tasks(boot.factory)=={'scanned':1,'enqueued':1,'skipped':0}
    assert queued(boot,queue[0])==[(queue[0],queue[1],'pending')]
