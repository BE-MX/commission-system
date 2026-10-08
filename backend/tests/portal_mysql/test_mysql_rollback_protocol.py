"""Actual Python rollback control child/owned MySQL; no service or provider startup."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
from sqlalchemy import text

from test_mysql_outbound_mode import boot, owner, lock_owner, install_record, MODE, LOCK  # noqa: F401

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'deploy'))
import remote_backend as remote
from rollback_protocol import observe as actual_observe

# This temporary Settings substitute permits only this suite's random process,
# then checks the server UUID/port before the product's first protocol query.
# No production app module or .env is loaded. SQLAlchemy/PyMySQL are real.
CONFIG=r"""import os,time
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import event
from sqlalchemy.engine import Engine,URL
owned_port=int(os.environ['OWNED_PORT'])
owned_uuid=os.environ['OWNED_UUID']
owned_password=os.environ['OWNED_PASSWORD']
@event.listens_for(Engine,'do_connect')
def target(dialect,record,args,kwargs):
 if args or kwargs.get('host')!='127.0.0.1' or kwargs.get('port')!=owned_port or kwargs.get('database')!='portal_isolated_test' or kwargs.get('password')!=owned_password:
  raise RuntimeError('Only owned test target is allowed')
@event.listens_for(Engine,'connect')
def identity(connection,record):
 with connection.cursor() as cursor:
  cursor.execute('SELECT @@server_uuid,@@port')
  if cursor.fetchone()!=(owned_uuid,owned_port):raise RuntimeError('Owned process identity mismatch')
reads=0
@event.listens_for(Engine,'before_cursor_execute',retval=True)
def before(connection,cursor,statement,parameters,context,executemany):
 global reads
 fault=os.environ['OWNED_FAULT'];gate=os.environ['OWNED_GATE']
 if statement=='SELECT @@server_uuid, DATABASE()':
  reads+=1
  if fault=='schema_change' and reads==2:cursor.execute('USE portal_owned_moved')
 if statement.startswith('SELECT GET_LOCK') and gate:
  Path(gate+'.before').write_text('ready')
  deadline=time.monotonic()+10
  while not Path(gate+'.release').exists():
   if time.monotonic()>deadline:raise RuntimeError('Owned gate expired')
   time.sleep(.01)
 if statement.startswith('SELECT RELEASE_LOCK'):
  if fault=='release_before':raise RuntimeError('Injected release send failure')
  if fault=='release_value':return 'SELECT 0',()
 return statement,parameters
@event.listens_for(Engine,'after_cursor_execute')
def after(connection,cursor,statement,parameters,context,executemany):
 fault=os.environ['OWNED_FAULT']
 if statement.startswith('SELECT GET_LOCK') and fault=='get_after':raise RuntimeError('Injected acquired ACK loss')
 if statement.startswith('SELECT RELEASE_LOCK') and fault=='release_after':raise RuntimeError('Injected released ACK loss')
def get_settings():
 return SimpleNamespace(commission_db_url=URL.create('mysql+pymysql',username='root',password=owned_password,host='127.0.0.1',port=owned_port,database='portal_isolated_test'))
"""


@pytest.fixture
def native(boot,tmp_path,monkeypatch):
    candidate=tmp_path/'candidate'
    (candidate/'deploy').mkdir(parents=True)
    configured=candidate/'backend/app/core';configured.mkdir(parents=True)
    (configured.parent/'__init__.py').write_text('')
    (configured/'__init__.py').write_text('')
    (configured/'config.py').write_text(CONFIG)
    (candidate/'deploy/rollback_protocol.py').write_bytes((ROOT/'deploy/rollback_protocol.py').read_bytes())
    with boot.engine.connect() as connection:
        uuid=connection.scalar(text('SELECT @@server_uuid'))
    state={'fault':'','gate':'','children':[],'candidate':candidate}
    actual_run=subprocess.run;actual_popen=subprocess.Popen
    def options():
        env={key:value for key,value in os.environ.items() if key.upper() not in {'PYTHONPATH','PYTHONHOME'}}
        env.update(OWNED_PORT=str(boot.engine.url.port),OWNED_UUID=uuid,
                   OWNED_PASSWORD=boot.engine.url.password,OWNED_FAULT=state['fault'],OWNED_GATE=state['gate'])
        return {'env':env,'creationflags':subprocess.CREATE_NO_WINDOW}
    def popen(command,**kwargs):
        assert command==remote.protocol_command(candidate,Path(sys.executable),'hold')
        child=actual_popen(command,**options(),**kwargs)
        state['children'].append(child);return child
    def observe():
        result=actual_run(remote.protocol_command(candidate,Path(sys.executable),'observe'),
            cwd=tmp_path,**options(),capture_output=True,text=True,timeout=15)
        if result.returncode!=0:raise RuntimeError(result.stderr.strip())
        return remote.parse_protocol(result.stdout,'observed')
    monkeypatch.setattr(remote.subprocess,'Popen',popen)
    # subprocess.run itself calls Popen: run the original under the original
    # factory while observing, before any rollback controller exists.
    def observation():
        with monkeypatch.context() as patch:
            patch.setattr(subprocess,'Popen',actual_popen)
            return observe()
    state['observe']=observation
    state['fence']=lambda expected:remote.rollback_guard(candidate,Path(sys.executable),expected)
    yield state
    for child in state['children']:
        if child.poll() is None:child.kill();child.wait(timeout=10)
        for stream in (child.stdin,child.stdout,child.stderr):
            if stream and not stream.closed:stream.close()


def assert_released(boot):
    deadline=time.monotonic()+5
    while lock_owner(boot) is not None and time.monotonic()<deadline:time.sleep(.01)
    assert lock_owner(boot) is None


def test_actual_script_and_controller_hold_legacy_across_readiness(boot,native):
    before=boot.snapshot();expected=native['observe']()
    assert expected['mode']=='legacy'
    with native['fence'](expected) as fence:
        assert lock_owner(boot) is not None
        assert fence.check()==expected
        with pytest.raises(RuntimeError,match='bootstrap is unavailable'):boot.initialize()
        assert boot.value() is None and boot.snapshot()==before
    assert_released(boot)
    assert boot.initialize()==MODE and boot.snapshot()==before


def test_actual_busy_owner_is_not_released_by_failed_controller(boot,native):
    expected=native['observe']();before=boot.snapshot()
    with owner(boot.engine):
        prior=lock_owner(boot)
        with pytest.raises(RuntimeError):
            with native['fence'](expected):pytest.fail('Busy owner accepted')
        assert lock_owner(boot)==prior and boot.snapshot()==before
    assert_released(boot)


def test_actual_mode_committed_after_baseline_refuses_unverified_rollback(boot,native):
    expected=native['observe']();before=boot.snapshot()
    assert boot.initialize()==MODE
    with pytest.raises(RuntimeError):
        with native['fence'](expected):pytest.fail('Persistent mode accepted for legacy rollback')
    assert boot.value()==1 and boot.snapshot()==before
    assert_released(boot)


@pytest.mark.parametrize('records',[
    [(MODE,2)],[('outbound-worker-v2',1)],[(MODE,1),('outbound-worker-v2',1)]])
def test_actual_unknown_mode_observation_is_safe_and_read_only(boot,native,records):
    for code,version in records:install_record(boot,code,version)
    before=boot.snapshot()
    with pytest.raises(RuntimeError,match='Rollback protocol control unavailable'):native['observe']()
    assert boot.snapshot()==before
    assert_released(boot)


@pytest.mark.parametrize('fault',['get_after','release_before','release_after','release_value'])
def test_actual_lock_ack_failure_terminates_owned_socket(boot,native,fault):
    expected=native['observe']();before=boot.snapshot();native['fault']=fault
    with pytest.raises(RuntimeError):
        with native['fence'](expected) as fence:
            assert fault!='get_after'
            assert lock_owner(boot) is not None and fence.check()==expected
    assert_released(boot)
    assert boot.snapshot()==before and boot.value() is None
    assert boot.initialize()==MODE


def test_actual_control_child_kill_frees_lock_without_release_receipt(boot,native):
    expected=native['observe']();before=boot.snapshot()
    with pytest.raises(RuntimeError,match='Rollback control cannot be confirmed'):
        with native['fence'](expected) as fence:
            assert lock_owner(boot) is not None
            fence.child.kill();fence.child.wait(timeout=10)
    assert_released(boot)
    assert boot.snapshot()==before and boot.initialize()==MODE


def test_actual_schema_change_after_get_is_rejected_and_lock_freed(boot,native):
    with boot.engine.begin() as connection:
        connection.exec_driver_sql('CREATE DATABASE portal_owned_moved')
        connection.exec_driver_sql('CREATE TABLE portal_owned_moved.ark_order_portal_auth_barriers LIKE portal_isolated_test.ark_order_portal_auth_barriers')
    try:
        expected=native['observe']();before=boot.snapshot()
        with boot.engine.connect() as connection:
            try:
                connection.exec_driver_sql('USE portal_owned_moved')
                moved=actual_observe(connection)
                assert moved['mode']==expected['mode']=='legacy'
                assert moved['database_fingerprint']!=expected['database_fingerprint']
            finally:
                # Reset even if an assertion fails, before returning to the pool.
                connection.exec_driver_sql('USE portal_isolated_test')
                connection.rollback()
        native['fault']='schema_change'
        with pytest.raises(RuntimeError):
            with native['fence'](expected):pytest.fail('Changed database accepted')
        assert_released(boot)
        assert boot.snapshot()==before
    finally:
        with boot.engine.begin() as connection:connection.exec_driver_sql('DROP DATABASE portal_owned_moved')


def test_actual_get_after_new_bootstrap_rechecks_mode(boot,native,tmp_path):
    expected=native['observe']();before=boot.snapshot()
    gate=tmp_path/'gate';native['gate']=str(gate);errors=[]
    def enter():
        try:
            with native['fence'](expected):errors.append('Unexpected readiness')
        except RuntimeError:errors.append('Refused')
    thread=threading.Thread(target=enter);thread.start()
    try:
        deadline=time.monotonic()+10
        while not Path(str(gate)+'.before').exists() and thread.is_alive() and time.monotonic()<deadline:time.sleep(.01)
        assert Path(str(gate)+'.before').exists()
        assert boot.initialize()==MODE
    finally:
        Path(str(gate)+'.release').write_text('release')
        thread.join(timeout=15)
    assert not thread.is_alive() and errors==['Refused']
    assert_released(boot)
    assert boot.value()==1 and boot.snapshot()==before


def test_current_legacy_callback_rechecks_after_control_release_and_bootstrap(boot,native,monkeypatch):
    # Actual current callback wrapper/transaction and SQL write, queue body
    # substitute. This is not an older artifact or all-writer compatibility.
    from app.invoice import outbound_mode as mode,outbound_task_service as tasks
    calls=[]
    def action(db):
        calls.append('legacy')
        db.execute(text("INSERT INTO ark_order_portal_auth_barriers(code,version) VALUES ('fixture_legacy_queue',1)"))
        return {'enqueued':1}
    monkeypatch.setattr(tasks,'_reconcile_missing_outbound_tasks',action)
    expected=native['observe']()
    with native['fence'](expected):
        assert mode.reconcile_legacy(boot.factory)=={'status':'busy','enqueued':0}
        assert calls==[]
    assert_released(boot)
    assert mode.reconcile_legacy(boot.factory)=={'enqueued':1}
    assert calls==['legacy']
    with boot.engine.connect() as observer:
        assert observer.scalar(text("SELECT version FROM ark_order_portal_auth_barriers WHERE code='fixture_legacy_queue'"))==1
    before=boot.snapshot()
    assert boot.initialize()==MODE
    assert mode.reconcile_legacy(boot.factory)=={'status':'disabled','enqueued':0}
    assert calls==['legacy'] and boot.snapshot()==before
    assert_released(boot)
