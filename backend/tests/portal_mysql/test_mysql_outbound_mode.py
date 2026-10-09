"""Owned MySQL mode bootstrap; compiled production lifespan body, no full app startup."""
import ast
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import Mock

import pytest
from sqlalchemy import inspect, text, event
from sqlalchemy.orm import Session, sessionmaker

from app.portal import authority

MODE = 'outbound-worker-v1'
LOCK = 'ark-okki-outbound-poller'
TABLE = 'ark_order_portal_auth_barriers'


@pytest.fixture
def boot(migrated, monkeypatch):
    with migrated.begin() as connection:
        connection.execute(text(f"DELETE FROM {TABLE} WHERE code LIKE 'outbound-worker-%' OR code='fixture_legacy_queue'"))
    settings = SimpleNamespace(PORTAL_ENABLED=True, PORTAL_OUTBOUND_WORKER_ENABLED=False,
        SCHEDULER_ENABLED=False, OKKI_OUTBOUND_AUTO_ENABLED=True, PORTAL_LOCK_WAIT_SECONDS=3)
    monkeypatch.setattr(authority, 'get_settings', lambda: settings)
    factory = sessionmaker(bind=migrated, expire_on_commit=False)
    factory_state = {"current":factory}
    def initialize():
        from app.bootstrap import portal_outbound
        monkeypatch.setattr(portal_outbound, 'SessionLocal', factory_state['current'])
        monkeypatch.setattr(portal_outbound, 'get_settings', lambda: settings)
        return portal_outbound.initialize_portal_outbound()
    def value():
        with migrated.connect() as connection:
            return connection.scalar(text(f"SELECT version FROM {TABLE} WHERE code=:code"), {'code':MODE})
    def all_rows():
        result = {}
        with migrated.connect() as connection:
            for name in inspect(connection).get_table_names():
                rows = [dict(row) for row in connection.execute(text('SELECT * FROM `'+name+'`')).mappings()]
                if name == TABLE:
                    rows = [row for row in rows if not row['code'].startswith('outbound-worker-')]
                result[name] = sorted(rows, key=repr)
        return result
    yield SimpleNamespace(engine=migrated, settings=settings, factory=factory, factory_state=factory_state,
                          initialize=initialize, value=value, snapshot=all_rows)
    with migrated.begin() as connection:
        connection.execute(text(f"DELETE FROM {TABLE} WHERE code LIKE 'outbound-worker-%' OR code='fixture_legacy_queue'"))


def lifespan_body(boot, monkeypatch):
    """Run the original lifespan AST with non-mode integrations replaced, not ASGI."""
    source = Path(__file__).resolve().parents[2] / 'app/main.py'
    node = next(node for node in ast.parse(source.read_text(encoding='utf-8')).body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == 'lifespan')
    @asynccontextmanager
    async def mcp():
        yield
    events = []
    pm = ModuleType('app.pm.bootstrap'); pm.init_pm_module = lambda: events.append('pm')
    storage = ModuleType('app.core.storage.worker')
    storage.start_worker = lambda: None
    storage.stop_worker = lambda _: None
    monkeypatch.setitem(sys.modules, 'app.pm.bootstrap', pm)
    monkeypatch.setitem(sys.modules, 'app.core.storage.worker', storage)
    def scheduler(**kwargs):
        events.append(('scheduler', boot.value(), kwargs))
        return None
    def initialize():
        events.append('mode')
        return boot.initialize()
    namespace = {'FastAPI':object, 'asynccontextmanager':asynccontextmanager, 'AsyncExitStack':AsyncExitStack, 'mcp_session_lifespan':mcp,
        'start_scheduler':scheduler, 'shutdown_scheduler':lambda _:None,
        'initialize_portal_outbound':initialize, 'engine':SimpleNamespace(dispose=lambda:None)}
    for name in ('check_pdf_export_resources','check_expo_watermark','check_database_connection',
        'load_business_rules','seed_admin_and_permissions','seed_asset_dimensions','seed_salary_rules',
        'seed_agent_runtime_profiles','seed_whatsapp_translation_glossary','auto_init_ai_presets'):
        namespace[name] = lambda name=name: events.append(name)
    exec(compile(ast.Module(body=[node],type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['lifespan'], events


@pytest.mark.asyncio
@pytest.mark.parametrize('worker,scheduler', [(False,False),(False,True),(True,False),(True,True)])
async def test_production_lifespan_confirms_mode_before_scheduler_with_every_flag_combination(boot, monkeypatch, worker, scheduler):
    boot.settings.PORTAL_OUTBOUND_WORKER_ENABLED = worker
    boot.settings.SCHEDULER_ENABLED = scheduler
    before = boot.snapshot()
    lifespan, events = lifespan_body(boot,monkeypatch)
    async with lifespan(object()):
        assert boot.value() == 1
        called = next(item for item in events if isinstance(item,tuple))
        assert called == ('scheduler',1,{'outbound_mode':MODE})
        assert events.index('mode') < events.index(called)
    assert boot.snapshot() == before


@contextmanager
def owner(engine):
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT GET_LOCK(:name,0)'),{'name':LOCK}) == 1
        connection.rollback()
        try:
            yield connection
        finally:
            assert connection.scalar(text('SELECT RELEASE_LOCK(:name)'),{'name':LOCK}) == 1
            connection.rollback()


def install_record(boot, code=MODE, version=1):
    with boot.engine.begin() as connection:
        connection.execute(text(f'INSERT INTO {TABLE}(code,version) VALUES (:code,:version)'),
                           {'code':code,'version':version})


def lock_owner(boot):
    with boot.engine.connect() as connection:
        return connection.scalar(text('SELECT IS_USED_LOCK(:name)'),{'name':LOCK})


@pytest.mark.asyncio
async def test_first_start_busy_actual_owner_never_reaches_scheduler(boot,monkeypatch):
    before = boot.snapshot()
    lifespan, events = lifespan_body(boot,monkeypatch)
    with owner(boot.engine):
        with pytest.raises(RuntimeError,match='bootstrap is unavailable'):
            async with lifespan(object()):
                pytest.fail('Busy first startup yielded readiness')
        assert boot.value() is None
        assert not any(isinstance(item,tuple) for item in events)
        assert lock_owner(boot) is not None
    assert boot.snapshot() == before


@pytest.mark.parametrize('enabled',[True,False])
def test_existing_mode_read_only_restart_does_not_contend_with_live_worker(boot,enabled):
    install_record(boot)
    boot.settings.PORTAL_ENABLED = enabled
    before = boot.snapshot()
    with owner(boot.engine):
        original_owner = lock_owner(boot)
        assert boot.initialize() == MODE
        assert lock_owner(boot) == original_owner
        assert boot.value() == 1
    assert boot.snapshot() == before


@pytest.mark.parametrize('installed',[True,False])
def test_initial_off_and_persistent_off_are_distinct_and_never_mutate(boot,installed):
    if installed: install_record(boot)
    boot.settings.PORTAL_ENABLED = False
    before = boot.snapshot()
    assert boot.initialize() == (MODE if installed else 'legacy')
    assert boot.value() == (1 if installed else None)
    assert lock_owner(boot) is None
    assert boot.snapshot() == before


@pytest.mark.parametrize('enabled',[True,False])
@pytest.mark.parametrize('records',[
    [(MODE,2)], [('outbound-worker-v2',1)], [(MODE,1),('outbound-worker-v2',1)]])
def test_unknown_version_namespace_or_multiple_modes_refuse_both_on_and_off(boot,enabled,records):
    for code,version in records: install_record(boot,code,version)
    boot.settings.PORTAL_ENABLED=enabled
    before = boot.snapshot()
    with pytest.raises(RuntimeError,match='bootstrap is unavailable'):
        boot.initialize()
    assert boot.snapshot()==before and lock_owner(boot) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('lost_ack',[True,False])
async def test_first_mode_commit_failure_never_starts_scheduler_and_retry_uses_durable_result(boot,monkeypatch,lost_ack):
    state = {'armed':True,'commits':0}
    class FaultSession(Session):
        def commit(self):
            state['commits'] += 1
            if state['armed']:
                state['armed']=False
                if lost_ack: super().commit()
                raise RuntimeError('Mode commit acknowledgement lost')
            return super().commit()
    boot.factory_state['current']=sessionmaker(bind=boot.engine,class_=FaultSession)
    before=boot.snapshot()
    lifespan,events=lifespan_body(boot,monkeypatch)
    with pytest.raises(RuntimeError,match='bootstrap is unavailable'):
        async with lifespan(object()):
            pytest.fail('Unconfirmed mode commit yielded readiness')
    assert not any(isinstance(item,tuple) for item in events)
    assert boot.value()==(1 if lost_ack else None)
    assert boot.snapshot()==before and lock_owner(boot) is None
    assert boot.initialize()==MODE
    assert boot.value()==1 and state['commits']==(1 if lost_ack else 2)
    assert boot.snapshot()==before


def test_mode_read_error_is_not_legacy_and_secret_error_text_is_not_logged(boot,capsys):
    @contextmanager
    def broken():
        raise RuntimeError('password=never-expose-mode-secret')
        yield
    boot.factory_state['current']=broken
    with pytest.raises(RuntimeError,match='bootstrap is unavailable'):
        boot.initialize()
    assert 'never-expose-mode-secret' not in capsys.readouterr().out
    assert boot.value() is None


@pytest.mark.parametrize('enabled',[True,False])
def test_unmigrated_table_is_only_compatible_when_initial_off(boot,enabled):
    # Exact hand-authored 171 head proves only the branch, not historical replay.
    boot.settings.PORTAL_ENABLED=enabled
    with boot.engine.begin() as connection:
        created=not inspect(connection).has_table('alembic_version')
        connection.execute(text('CREATE TABLE IF NOT EXISTS alembic_version(version_num VARCHAR(64) PRIMARY KEY)'))
        original=list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
        connection.execute(text('DELETE FROM alembic_version'))
        connection.execute(text("INSERT INTO alembic_version VALUES ('171_customer_tag_display_value')"))
        connection.execute(text(f'RENAME TABLE {TABLE} TO owned_mode_backup'))
    try:
        if enabled:
            with pytest.raises(RuntimeError,match='bootstrap is unavailable'):
                boot.initialize()
        else:
            assert boot.initialize()=='legacy'
        with boot.engine.connect() as connection:
            assert not inspect(connection).has_table(TABLE)
        assert lock_owner(boot) is None
    finally:
        with boot.engine.begin() as connection:
            connection.execute(text(f'RENAME TABLE owned_mode_backup TO {TABLE}'))
            if created:connection.execute(text('DROP TABLE alembic_version'))
            else:
                connection.execute(text('DELETE FROM alembic_version'))
                for head in original:connection.execute(text('INSERT INTO alembic_version VALUES (:head)'),{'head':head})


def test_second_starter_installs_between_initial_read_and_fence_then_first_rechecks(boot,monkeypatch):
    from app.invoice import outbound_mode as mode
    original=mode.executor_fence
    state={'once':True,'insertions':0}
    def count(connection,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO '+TABLE) and MODE in repr(parameters):
            state['insertions']+=1
    @contextmanager
    def competing(db):
        if state['once']:
            state['once']=False
            assert mode.initialize(boot.factory,portal_enabled=True)==MODE
        with original(db) as acquired:
            yield acquired
    monkeypatch.setattr(mode,'executor_fence',competing)
    event.listen(boot.engine,'after_cursor_execute',count)
    try:
        assert boot.initialize()==MODE
        assert boot.value()==1 and state['insertions']==1
    finally:
        event.remove(boot.engine,'after_cursor_execute',count)
    assert lock_owner(boot) is None


def test_stale_caller_transaction_cannot_enter_legacy_executor(boot,monkeypatch):
    from app.invoice import outbound_mode as mode,outbound_task_service as tasks
    action=Mock(); monkeypatch.setattr(tasks,'_reconcile_missing_outbound_tasks',action)
    with boot.factory() as stale:
        assert mode.read_mode(stale)=='legacy'
        install_record(boot)
        with pytest.raises(RuntimeError,match='fresh owned session'):
            mode.reconcile_legacy(lambda:stale)
    action.assert_not_called()
    assert mode.reconcile_legacy(boot.factory)=={'status':'disabled','enqueued':0}
    action.assert_not_called()
    assert lock_owner(boot) is None


@pytest.mark.parametrize('rollback',[True,False])
def test_legacy_commit_or_rollback_holds_fence_until_end_and_blocks_first_mode(boot,monkeypatch,rollback):
    from app.invoice import outbound_mode as mode,outbound_task_service as tasks
    observed=[]
    def action(db):
        observed.append(lock_owner(boot))
        assert observed[-1] is not None
        with pytest.raises(RuntimeError,match='still owns the fence'):
            mode.initialize(boot.factory,portal_enabled=True)
        db.execute(text(f"INSERT INTO {TABLE}(code,version) VALUES ('fixture_legacy_queue',1)"))
        if rollback: raise RuntimeError('Owned legacy queue rollback')
        return {'enqueued':1}
    def before_commit(db):
        assert lock_owner(boot) is not None
        observed.append('before_commit')
    monkeypatch.setattr(tasks,'_reconcile_missing_outbound_tasks',action)
    event.listen(boot.factory.class_,'before_commit',before_commit)
    try:
        if rollback:
            with pytest.raises(RuntimeError,match='Owned legacy queue rollback'):
                mode.reconcile_legacy(boot.factory)
        else:
            assert mode.reconcile_legacy(boot.factory)=={'enqueued':1}
    finally:
        event.remove(boot.factory.class_,'before_commit',before_commit)
    assert lock_owner(boot) is None and boot.value() is None
    with boot.engine.connect() as connection:
        assert connection.scalar(text(f"SELECT COUNT(*) FROM {TABLE} WHERE code='fixture_legacy_queue'"))==(0 if rollback else 1)
    assert boot.initialize()==MODE
    assert len(observed)==(1 if rollback else 2)


@pytest.mark.parametrize('mode_value,portal,legacy_registered',[
    ('legacy',False,True),(MODE,False,False),(MODE,True,False)])
def test_registry_suppresses_legacy_after_persistent_mode_and_keeps_delete_gate_separate(boot,monkeypatch,mode_value,portal,legacy_registered):
    from app.schedulers import registry
    from app.core.config import get_settings
    settings=get_settings().model_copy(update={'PORTAL_ENABLED':portal,'OKKI_OUTBOUND_AUTO_ENABLED':True,
        'OKKI_CLIENT_ID':'test-only','OKKI_CLIENT_SECRET':'test-only'})
    monkeypatch.setattr(registry,'get_settings',lambda:settings)
    scheduler=Mock()
    registry._register_jobs(scheduler,outbound_mode=mode_value)
    jobs={call.kwargs['id']:call.args[0] for call in scheduler.add_job.call_args_list}
    assert (registry.JOB_OKKI_OUTBOUND_RECONCILE in jobs)==legacy_registered
    # This preexisting writer remains a separately open gate; do not silently disable it.
    assert registry.JOB_OKKI_OUTBOUND_DELETE_RECONCILE in jobs


def test_registered_legacy_callback_rechecks_after_another_starter_commits_mode(boot,monkeypatch):
    from app.schedulers import registry
    from app.invoice import outbound_mode as mode,outbound_task_service as tasks
    from app.core.config import get_settings
    settings=get_settings().model_copy(update={'PORTAL_ENABLED':False,'OKKI_OUTBOUND_AUTO_ENABLED':True})
    monkeypatch.setattr(registry,'get_settings',lambda:settings)
    monkeypatch.setattr(registry,'SessionLocal',boot.factory)
    scheduler=Mock(); registry._register_jobs(scheduler,outbound_mode='legacy')
    job=next(call.args[0] for call in scheduler.add_job.call_args_list
             if call.kwargs['id']==registry.JOB_OKKI_OUTBOUND_RECONCILE)
    with boot.factory() as initial:
        assert mode.read_mode(initial)=='legacy'
        assert boot.initialize()==MODE
        # The registration's legacy snapshot remains stale; the callback uses a fresh session.
        assert mode.read_mode(initial)=='legacy'
        action=Mock(); monkeypatch.setattr(tasks,'_reconcile_missing_outbound_tasks',action)
        before=boot.snapshot()
        assert job()=={'status':'disabled','enqueued':0}
        action.assert_not_called()
        assert boot.snapshot()==before
    assert lock_owner(boot) is None


@pytest.mark.parametrize('failure',['ack','rollback'])
@pytest.mark.parametrize('entry',['bootstrap','legacy','worker'])
def test_acquisition_unknown_invalidates_actual_held_connection_and_retry_succeeds(boot,monkeypatch,capsys,caplog,failure,entry):
    from sqlalchemy.engine import Connection
    from app.invoice import outbound_mode as mode,outbound_task_service as tasks,outbound_worker as worker
    original_scalar=Connection.scalar
    original_rollback=Connection.rollback
    original_invalidate=Connection.invalidate
    state={'armed':True,'connection':None,'acquired':None,'invalidated':[], 'physical':None,'connection_id':None}
    before=boot.snapshot()
    action=Mock();monkeypatch.setattr(tasks,'_reconcile_missing_outbound_tasks',action)
    monkeypatch.setattr(worker,'get_settings',lambda:boot.settings)
    def scalar(connection,statement,*args,**kwargs):
        result=original_scalar(connection,statement,*args,**kwargs)
        if state['armed'] and 'SELECT GET_LOCK' in str(statement):
            assert result==1
            state['connection']=connection
            state['physical']=connection.connection.driver_connection
            state['connection_id']=original_scalar(connection,text('SELECT CONNECTION_ID()'))
            state['acquired']=result
            if failure=='ack':
                state['armed']=False
                raise RuntimeError('password=never-expose-fence-secret')
        return result
    def rollback(connection):
        if failure=='rollback' and state['armed'] and connection is state['connection']:
            state['armed']=False
            raise RuntimeError('password=never-expose-fence-secret')
        return original_rollback(connection)
    def invalidate(connection,*args,**kwargs):
        state['invalidated'].append(connection)
        return original_invalidate(connection,*args,**kwargs)
    monkeypatch.setattr(Connection,'scalar',scalar)
    monkeypatch.setattr(Connection,'rollback',rollback)
    monkeypatch.setattr(Connection,'invalidate',invalidate)
    observer=boot.engine.connect()
    observer_id=original_scalar(observer,text('SELECT CONNECTION_ID()'));observer.rollback()
    try:
        with pytest.raises(RuntimeError):
            if entry=='bootstrap':boot.initialize()
            elif entry=='legacy':mode.reconcile_legacy(boot.factory)
            else:worker.run_once(boot.factory)
        assert state['acquired']==1
        assert state['connection_id']!=observer_id
        assert original_scalar(observer,text('SELECT IS_USED_LOCK(:name)'),{'name':LOCK}) is None
        observer.rollback()
        assert state['invalidated']==[state['connection']]
        assert state['physical']._sock is None
        assert boot.value() is None and boot.snapshot()==before
        action.assert_not_called()
        assert 'never-expose-fence-secret' not in capsys.readouterr().out+caplog.text
        assert boot.initialize()==MODE
        assert lock_owner(boot) is None and boot.snapshot()==before
    finally:
        # The old implementation leaks the named lock; close owned idle sockets after asserting.
        observer.close()
        boot.engine.dispose()


@pytest.mark.parametrize('failure',['before','ack','rollback','invalid'])
@pytest.mark.parametrize('entry',['bootstrap','legacy','worker'])
def test_release_unknown_discards_physical_connection_without_rewriting_mode(boot,monkeypatch,failure,entry):
    from sqlalchemy.engine import Connection
    from app.invoice import outbound_mode as mode,outbound_task_service as tasks,outbound_worker as worker
    original_scalar=Connection.scalar; original_rollback=Connection.rollback
    original_invalidate=Connection.invalidate
    state={'armed':True,'connection':None,'physical':None,'released':None,'invalidated':[]}
    before=boot.snapshot()
    monkeypatch.setattr(tasks,'_reconcile_missing_outbound_tasks',lambda db:{'enqueued':0})
    monkeypatch.setattr(worker,'get_settings',lambda:boot.settings)
    def scalar(connection,statement,*args,**kwargs):
        if state['armed'] and 'SELECT RELEASE_LOCK' in str(statement):
            state['connection']=connection;state['physical']=connection.connection.driver_connection
            if failure=='before':
                state['armed']=False
                raise RuntimeError('Owned release transport unavailable')
        result=original_scalar(connection,statement,*args,**kwargs)
        if state['armed'] and 'SELECT RELEASE_LOCK' in str(statement):
            assert result==1
            state['released']=result
            if failure in ('ack','invalid'):
                state['armed']=False
                if failure=='ack':raise RuntimeError('Owned release acknowledgement lost')
                return None
        return result
    def rollback(connection):
        if state['armed'] and failure=='rollback' and connection is state['connection'] and state['released']==1:
            state['armed']=False
            raise RuntimeError('Owned release rollback unavailable')
        return original_rollback(connection)
    def invalidate(connection,*args,**kwargs):
        state['invalidated'].append(connection)
        return original_invalidate(connection,*args,**kwargs)
    monkeypatch.setattr(Connection,'scalar',scalar)
    monkeypatch.setattr(Connection,'rollback',rollback);monkeypatch.setattr(Connection,'invalidate',invalidate)
    observer=boot.engine.connect()
    try:
        with pytest.raises(RuntimeError,match='fence release'):
            if entry=='bootstrap':
                # The bootstrap wrapper uses a different safe public error.
                mode.initialize(boot.factory,portal_enabled=True)
            elif entry=='legacy':mode.reconcile_legacy(boot.factory)
            else:worker.run_once(boot.factory)
        assert state['invalidated']==[state['connection']]
        assert state['physical']._sock is None
        assert original_scalar(observer,text('SELECT IS_USED_LOCK(:name)'),{'name':LOCK}) is None
        observer.rollback()
        assert boot.value()==(None if entry=='legacy' else 1)
        assert boot.snapshot()==before
        assert boot.initialize()==MODE
    finally:
        observer.close();boot.engine.dispose()


def test_connection_with_preexisting_recursive_lock_is_discarded_before_reacquisition(boot):
    from sqlalchemy import create_engine
    from app.invoice import outbound_mode as mode
    # This separate one-slot pool guarantees that the fence borrows the leaked socket.
    pool=create_engine(boot.engine.url,pool_size=1,max_overflow=0)
    observer=boot.engine.connect()
    try:
        with pool.connect() as leaked:
            leaked_id=leaked.scalar(text('SELECT CONNECTION_ID()'))
            physical=leaked.connection.driver_connection
            assert leaked.scalar(text('SELECT GET_LOCK(:name,0)'),{'name':LOCK})==1
            assert leaked.scalar(text('SELECT GET_LOCK(:name,0)'),{'name':LOCK})==1
            leaked.rollback()
        assert observer.scalar(text('SELECT IS_USED_LOCK(:name)'),{'name':LOCK})==leaked_id
        observer.rollback()
        with Session(pool) as db:
            with pytest.raises(RuntimeError,match='fence acquisition'):
                with mode.executor_fence(db):pytest.fail('Borrowed preheld lock entered executor')
        assert physical._sock is None
        assert observer.scalar(text('SELECT IS_USED_LOCK(:name)'),{'name':LOCK}) is None
        observer.rollback()
        with Session(pool) as db:
            with mode.executor_fence(db) as acquired:assert acquired
        assert observer.scalar(text('SELECT IS_USED_LOCK(:name)'),{'name':LOCK}) is None
    finally:
        observer.close();pool.dispose()


@pytest.mark.parametrize('phase',['acquisition','release'])
def test_interrupted_fence_discards_actual_socket_and_preserves_interrupt(boot,monkeypatch,phase):
    from sqlalchemy.engine import Connection
    from app.invoice import outbound_mode as mode
    original=Connection.scalar; state={'armed':True,'physical':None}
    keyword='SELECT GET_LOCK' if phase=='acquisition' else 'SELECT RELEASE_LOCK'
    def scalar(connection,statement,*args,**kwargs):
        result=original(connection,statement,*args,**kwargs)
        if state['armed'] and keyword in str(statement):
            assert result==1
            state['armed']=False;state['physical']=connection.connection.driver_connection
            raise KeyboardInterrupt('Owned interruption')
        return result
    monkeypatch.setattr(Connection,'scalar',scalar)
    with boot.engine.connect() as observer:
        with boot.factory() as db:
            with pytest.raises(KeyboardInterrupt,match='Owned interruption'):
                with mode.executor_fence(db):pass
        assert state['physical']._sock is None
        assert original(observer,text('SELECT IS_USED_LOCK(:name)'),{'name':LOCK}) is None
        observer.rollback()
        with boot.factory() as db:
            with mode.executor_fence(db) as acquired:assert acquired


def test_release_validation_allows_another_physical_owner_to_take_over(boot,monkeypatch):
    from sqlalchemy.engine import Connection
    from app.invoice import outbound_mode as mode
    original=Connection.scalar;state={'once':True}
    with boot.engine.connect() as successor:
        successor_id=original(successor,text('SELECT CONNECTION_ID()'));successor.rollback()
        def scalar(connection,statement,*args,**kwargs):
            result=original(connection,statement,*args,**kwargs)
            if state['once'] and 'SELECT RELEASE_LOCK' in str(statement):
                state['once']=False
                assert result==1
                assert original(successor,text('SELECT GET_LOCK(:name,0)'),{'name':LOCK})==1
                successor.rollback()
            return result
        monkeypatch.setattr(Connection,'scalar',scalar)
        try:
            with boot.factory() as db:
                with mode.executor_fence(db) as acquired:assert acquired
            assert original(successor,text('SELECT IS_USED_LOCK(:name)'),{'name':LOCK})==successor_id
        finally:
            assert original(successor,text('SELECT RELEASE_LOCK(:name)'),{'name':LOCK})==1
            successor.rollback()
