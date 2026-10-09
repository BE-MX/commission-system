"""Real dedicated Node/MySQL deployment fence. No systemd or supplier entry point."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
from sqlalchemy import text

from test_mysql_outbound_mode import boot, owner, lock_owner, MODE, LOCK  # noqa: F401
from test_mysql_node_mode_privileges import node_runtime  # noqa: F401

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'deploy'))
import okki_outbound_remote as remote

GUARD=r"""import ownedMysql from 'mysql2/promise';
const originalConnect=ownedMysql.createConnection.bind(ownedMysql);
ownedMysql.createConnection=async(options)=>{
  if(options.host!=='127.0.0.1'||options.port!==Number(process.env.OWNED_PORT)||
     options.database!=='portal_isolated_test'||options.password!==process.env.ARK_DB_PASSWORD)
    throw Error('Only owned test target allowed');
  const c=await originalConnect(options);
  try {
    const [[identity]]=await c.query('SELECT @@server_uuid AS uuid, @@port AS port');
    if(identity.uuid!==process.env.OWNED_UUID||identity.port!==Number(process.env.OWNED_PORT))
      throw Error('Owned target identity mismatch');
    const originalQuery=c.query.bind(c);let identityReads=0;
    c.query=async(sql,...args)=>{
      if(sql==='SELECT @@server_uuid AS server_uuid, DATABASE() AS schema_name'){
        identityReads++;
        if(process.env.OWNED_FAULT==='schema_change'&&identityReads===3)await originalQuery('USE portal_owned_moved');
      }
      if(sql.startsWith('SELECT GET_LOCK') && process.env.OWNED_GATE){
        const fs=await import('node:fs/promises');
        await fs.writeFile(process.env.OWNED_GATE+'.before','ready');
        const deadline=Date.now()+10000;
        while(true){
          try{await fs.access(process.env.OWNED_GATE+'.release');break;}catch{}
          if(Date.now()>deadline)throw Error('Owned gate timeout');
          await new Promise(resolve=>setTimeout(resolve,10));
        }
      }
      const fault=process.env.OWNED_FAULT;
      if(sql.startsWith('SELECT RELEASE_LOCK')&&fault==='release_before')throw Error('Injected before release');
      const result=await originalQuery(sql,...args);
      if(sql.startsWith('SELECT GET_LOCK')&&fault==='get_after')throw Error('Injected acquired ACK loss');
      if(sql.startsWith('SELECT RELEASE_LOCK')&&fault==='release_after')throw Error('Injected released ACK loss');
      if(sql.startsWith('SELECT RELEASE_LOCK')&&fault==='release_value')return [[{released:0}],[]];
      return result;
    };
    return c;
  } catch(error){c.destroy();throw error;}
};
"""


@pytest.fixture
def native(boot,node_runtime,request,monkeypatch):
    node,_=node_runtime
    runtime=Path(request.config.getoption('portal_mode_mysql2')).parent.parent.parent.resolve(strict=True)
    with boot.engine.connect() as connection:
        uuid=connection.scalar(text('SELECT @@server_uuid'))
    state={'fault':'','gate':'','children':[]}
    actual_popen=subprocess.Popen
    def popen(command,**kwargs):
        assert command[0]==str(node) and command[-2]==(ROOT/'deploy/okki_outbound_mode.mjs').as_uri()
        assert command[-1]=='hold' and kwargs['cwd']==runtime
        env=dict(os.environ)
        # Owned random password is passed only in the child environment, never CLI/logs.
        env.update(ARK_DB_HOST='127.0.0.1',ARK_DB_PORT=str(boot.engine.url.port),ARK_DB_USER='root',
                   ARK_DB_PASSWORD=boot.engine.url.password,ARK_DB_NAME='portal_isolated_test',
                   OWNED_PORT=str(boot.engine.url.port),OWNED_UUID=uuid,
                   OWNED_FAULT=state['fault'],OWNED_GATE=state['gate'])
        child=actual_popen(command,env=env,creationflags=subprocess.CREATE_NO_WINDOW,**kwargs)
        state['children'].append(child)
        return child
    monkeypatch.setattr(remote,'ROOT',runtime)
    monkeypatch.setattr(remote,'mode_command',lambda stage,config,operation:[str(node),'--input-type=module','-e',
                        GUARD+remote.MODE_CONTROL_PROBE,(ROOT/'deploy/okki_outbound_mode.mjs').as_uri(),operation])
    monkeypatch.setattr(remote.subprocess,'Popen',popen)
    state['fence']=lambda:remote.ModeFence(ROOT/'deploy',Path('unused-owned-config'))
    yield state
    for child in state['children']:
        if child.poll() is None:child.kill();child.wait(timeout=10)
        for stream in (child.stdin,child.stdout,child.stderr):
            if stream and not stream.closed:stream.close()


def test_native_legacy_fence_blocks_real_bootstrap_until_confirmed_release(boot,native):
    before=boot.snapshot()
    with native['fence']() as fence:
        assert fence.observation['mode']=='legacy'
        assert lock_owner(boot) is not None
        with pytest.raises(RuntimeError,match='bootstrap is unavailable'):boot.initialize()
        assert boot.value() is None and boot.snapshot()==before
        assert fence.check()==fence.observation
    assert lock_owner(boot) is None
    assert boot.initialize()==MODE and boot.snapshot()==before


def test_native_known_mode_preserves_existing_worker_owner(boot,native):
    assert boot.initialize()==MODE
    before=boot.snapshot()
    with owner(boot.engine):
        original=lock_owner(boot)
        with native['fence']() as fence:
            assert fence.observation['mode']==MODE
            assert fence.check()==fence.observation and lock_owner(boot)==original
        assert lock_owner(boot)==original
    assert boot.snapshot()==before


def test_native_busy_legacy_owner_is_never_released_by_deployment(boot,native):
    before=boot.snapshot()
    with owner(boot.engine):
        original=lock_owner(boot)
        with pytest.raises(RuntimeError,match='control'):native['fence']().__enter__()
        assert lock_owner(boot)==original and boot.value() is None
    assert boot.snapshot()==before


@pytest.mark.parametrize('fault',['get_after','release_before','release_after','release_value'])
def test_native_lost_lock_ack_destroys_physical_connection(boot,native,fault):
    before=boot.snapshot();native['fault']=fault
    with pytest.raises(RuntimeError,match='control|release'):
        with native['fence']() as fence:
            assert lock_owner(boot) is not None
            fence.check()
    assert all(child.poll() is not None for child in native['children'])
    assert lock_owner(boot) is None and boot.value() is None and boot.snapshot()==before
    assert boot.initialize()==MODE and boot.snapshot()==before


def test_native_controller_child_death_rejects_release_and_frees_owned_lock(boot,native):
    before=boot.snapshot()
    with pytest.raises(RuntimeError,match='control'):
        with native['fence']() as fence:
            assert lock_owner(boot) is not None
            fence.child.kill();fence.child.wait(timeout=10)
            fence.check()
    assert lock_owner(boot) is None and boot.value() is None and boot.snapshot()==before
    assert boot.initialize()==MODE


def test_native_fresh_read_after_acquisition_observes_concurrent_bootstrap(boot,native,tmp_path):
    before=boot.snapshot();gate=tmp_path/'owned-mode-gate'
    native['gate']=str(gate)
    fence=native['fence']();result=[]
    def enter():
        try:result.append(fence.__enter__())
        except BaseException as error:result.append(error)
    thread=threading.Thread(target=enter,daemon=True);thread.start()
    try:
        deadline=time.monotonic()+12
        while not gate.with_suffix('.before').exists():
            assert thread.is_alive() and time.monotonic()<deadline,'Owned race gate unavailable'
            time.sleep(.01)
        assert boot.initialize()==MODE
        gate.with_suffix('.release').write_text('continue')
        thread.join(timeout=12)
        assert not thread.is_alive() and len(result)==1 and result[0] is fence
        assert fence.observation['mode']==MODE and fence.check()==fence.observation
        assert lock_owner(boot) is not None and boot.snapshot()==before
        fence.__exit__(None)
        assert lock_owner(boot) is None
    finally:
        gate.with_suffix('.release').touch()
        fence._abort();thread.join(timeout=12)


def test_native_changed_default_schema_is_not_a_matching_database_receipt(boot,native):
    before=boot.snapshot();native['fault']='schema_change'
    with boot.engine.begin() as connection:
        connection.execute(text('CREATE DATABASE portal_owned_moved'))
        connection.execute(text('CREATE TABLE portal_owned_moved.ark_order_portal_auth_barriers LIKE ark_order_portal_auth_barriers'))
    try:
        with pytest.raises(RuntimeError,match='control'):
            with native['fence']() as fence:
                assert fence.observation['mode']=='legacy' and lock_owner(boot) is not None
                fence.check()
        assert lock_owner(boot) is None and boot.value() is None
    finally:
        with boot.engine.begin() as connection:
            connection.execute(text('DROP DATABASE portal_owned_moved'))
    assert boot.snapshot()==before
