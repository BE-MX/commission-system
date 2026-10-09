"""Activation rollback mode boundary. All service/Git/DB effects replaced."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import office_release as office
import remote_backend as backend


@pytest.fixture(params=['office','beijing'])
def activation(request,tmp_path,monkeypatch):
    live=tmp_path/'live';live.mkdir();state=tmp_path/'state';state.mkdir()
    candidate=tmp_path/'candidate';candidate.mkdir()
    revision='a'*40;previous='b'*40
    target=office if request.param=='office' else backend
    values={'mode':'legacy','database_fingerprint':'e'*64,'held':False,'events':[]}
    def observe(*_):return {key:values[key] for key in ('mode','database_fingerprint')}
    @contextmanager
    def guard(*_):
        if values['mode']!='legacy':raise RuntimeError('Rollback requires verified protocol compatibility')
        values['held']=True
        try:yield
        finally:values['held']=False
    monkeypatch.setattr(backend,'protocol_observation',observe,raising=False)
    monkeypatch.setattr(backend,'rollback_guard',guard,raising=False)
    # Office imports the shared functions by name in the target implementation.
    monkeypatch.setattr(office,'protocol_observation',observe,raising=False)
    monkeypatch.setattr(office,'rollback_guard',guard,raising=False)
    def run(command,**_):
        if command[:2]==['git','rev-parse']:return previous
        if command[:2] in (['git','merge'],['git','checkout'],['git','reset']):
            values['events'].append(('git',command[-1]))
        if command[:3]==['sudo','-n','systemctl']:
            if command[3]=='start':values['mode']='outbound-worker-v1'
            values['events'].append(('service',command[3]))
        if command[:2]==['owned-nssm','status']:return 'SERVICE_RUNNING'
        if command[:2]==['owned-nssm','start']:
            values['mode']='outbound-worker-v1';values['events'].append(('service','start'))
        if command[:2]==['owned-nssm','stop']:values['events'].append(('service','stop'))
        return ''
    monkeypatch.setattr(target,'run',run)
    monkeypatch.setattr(target,'ROOT',candidate if request.param=='office' else live)
    monkeypatch.setattr(target,'STATE',state)
    monkeypatch.setattr(target.time,'sleep',lambda *_:None)
    if request.param=='office':
        monkeypatch.setattr(office,'health',Mock(side_effect=RuntimeError('Candidate startup failed')))
        prepared={'nssm':'owned-nssm','live':live,'python':Path('owned-python'),
            'application':Path('old-python.exe'),'parameters':'old args','port':8001,
            'schema':'177_portal_pi_header','schema_changed':False,'backend_changed':True,
            'connector_changed':False,'static':[],'revision':revision,'previous':previous}
        call=lambda:office.activate_locked(prepared)
    else:
        monkeypatch.setattr(backend,'schema_check',Mock())
        monkeypatch.setattr(backend,'healthy',Mock(side_effect=RuntimeError('Candidate startup failed')))
        info={'revision':revision,'previous':previous,'schema':'177_portal_pi_header',
              'schema_changed':False,'changed':True,'environment':None}
        (state/('backend-prepared-'+revision+'.json')).write_text(json.dumps(info))
        call=lambda:backend.activate_locked(revision)
    return SimpleNamespace(call=call,values=values,previous=previous)


def test_no_ddl_but_committed_mode_never_restarts_unverified_old_artifact(activation):
    with pytest.raises(RuntimeError):activation.call()
    assert activation.values['mode']=='outbound-worker-v1'
    assert ('git',activation.previous) not in activation.values['events']
    assert activation.values['events'].count(('service','start'))==1


def test_absolute_control_script_imports_settings_from_its_trusted_candidate(tmp_path):
    # Execute the exact product script bytes, not runpy or a mocked controller.
    # Settings and SQL are confined substitutes; no application startup or socket.
    import os
    import subprocess
    candidate=tmp_path/'owned-candidate'
    (candidate/'deploy').mkdir(parents=True)
    configured=candidate/'backend/app/core';configured.mkdir(parents=True)
    (candidate/'backend/app/__init__.py').write_text('')
    (configured/'__init__.py').write_text('')
    (configured/'config.py').write_text("from types import SimpleNamespace\ndef get_settings():return SimpleNamespace(commission_db_url='owned_test_only')\n")
    (candidate/'backend/sqlalchemy.py').write_text("""class Result:
 def __init__(self,value):self.value=value
 def all(self):return self.value
class Connection:
 def exec_driver_sql(self,sql,*args):
  if sql=='SELECT @@server_uuid, DATABASE()':return Result([('11111111-2222-3333-4444-555555555555','portal_isolated_test')])
  if sql.startswith('SELECT code,version FROM '):return Result([])
  raise AssertionError('Unexpected SQL')
 def invalidate(self):pass
 def close(self):pass
class Engine:
 def connect(self):return Connection()
 def dispose(self):pass
def create_engine(url,**kwargs):
 assert url=='owned_test_only' and kwargs['isolation_level']=='AUTOCOMMIT'
 return Engine()
""")
    script=candidate/'deploy/rollback_protocol.py'
    script.write_bytes((Path(backend.__file__).parent/'rollback_protocol.py').read_bytes())
    env={key:value for key,value in os.environ.items() if key.upper() not in {'PYTHONPATH','PYTHONHOME'}}
    result=subprocess.run([sys.executable,'-B','-u',str(script),'observe'],cwd=tmp_path,
                          env=env,text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    observed=json.loads(result.stdout)
    assert observed['phase']=='observed' and observed['mode']=='legacy'
    assert len(observed['database_fingerprint'])==64
    assert result.stderr==''
