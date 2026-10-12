"""Bound recovery and readiness tests use synthetic files and replaced effects."""
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
import recover_office_activation as recovery


def facts():
    writers = [{'kind': 'nssm', 'host': 'office', 'service': 'CommissionSystem'},
               {'kind': 'nssm', 'host': 'office', 'service': 'WhatsAppConnector'}]
    journal = {'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID, 'status': 'failed', 'completed': [],
        'outbound': {'status': 'installed_paused', 'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
            'baseline': {'active': True, 'enabled': True}, 'mode': 'legacy'}}
    migration = {'status': 'upgraded', 'schema': recovery.SCHEMA, 'pending': recovery.PENDING,
        'writers': [{'writer': w, 'before': 'running'} for w in writers], 'stopped': writers}
    return journal, migration, {'migration_writers': writers, 'static_targets': []}


@pytest.mark.parametrize('target,key,value', [
    ('journal', 'revision', 'x'*40), ('journal', 'release_id', 'x'*32),
    ('journal', 'status', 'preparing'), ('journal', 'completed', ['office']),
    ('migration', 'status', 'completed'), ('migration', 'schema', '183_portal_password_login'),
    ('migration', 'pending', ['185_announcement_push_option']), ('migration', 'writers', [])])
def test_drift_is_rejected(target, key, value):
    journal, migration, inventory = facts()
    (journal if target == 'journal' else migration)[key] = value
    with pytest.raises(RuntimeError):
        recovery.validate(journal, migration, recovery.REVISION, inventory)


def test_readiness_can_finish_after_old_30_second_budget():
    clock = [0]
    attempts = [0]
    def health():
        attempts[0] += 1
        if clock[0] < 80:
            raise OSError('startup still seeding')
    recovery.wait_ready(health, lambda: 'SERVICE_RUNNING', monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert clock[0] == 80 and attempts[0] > 15


def test_readiness_still_requires_health_and_has_a_deadline():
    clock = [0]
    with pytest.raises(RuntimeError, match='deadline'):
        recovery.wait_ready(lambda: None, lambda: 'SERVICE_STOPPED', timeout=6,
            monotonic=lambda: clock[0], sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert clock[0] == 6


@pytest.fixture
def simulated(tmp_path, monkeypatch):
    live=tmp_path/'live'; state=live/'.deploy_state'; source=state/'sources'/recovery.REVISION
    (source/'deploy').mkdir(parents=True); (live/'backend').mkdir()
    journal,migration,inventory=facts()
    (source/'deploy/platforms.json').write_text(json.dumps(inventory))
    plan=tmp_path/'plan.json'; plan.write_text(json.dumps({'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID}))
    events=[]
    running = {'CommissionSystem': False, 'WhatsAppConnector': False}
    def save(path, data):
        path.write_text(json.dumps(data))
    def run(args, **kwargs):
        if args[:3]==['git','rev-parse','HEAD']: return recovery.REVISION
        if args[:2]==['git','status']: return ''
        if args[0]=='ssh': return json.dumps({'current':recovery.PREVIOUS,'dirty':'','source_revision':recovery.REVISION,
            'source_dirty':'','revision':recovery.REVISION,'previous':recovery.PREVIOUS,'schema':recovery.SCHEMA})
        if args[1:3]==['get','CommissionSystem']:
            return {'Application': str(live/'python.exe'), 'AppDirectory': str(live/'backend'),
                'AppParameters': '-m uvicorn app.main:app --host 0.0.0.0 --port 8001'}[args[3]]
        if args[1]=='status': return 'SERVICE_RUNNING' if running[args[2]] else 'SERVICE_STOPPED'
        if args[1] in {'start','stop'}: running[args[2]]=args[1]=='start'
        events.append(tuple(args[1:]))
        return ''
    p=SimpleNamespace(ROOT=live,STATE=state,deployment_lock=lambda:nullcontext(),
        marker=lambda name: copy.deepcopy(journal if name=='publish-current' else migration),
        run=run,atomic_json=save,BJ='beijing',build_frontends=lambda **kw: {'frontend':source/'frontend/dist','frontend-pm':source/'frontend-pm/dist'},
        build_lan=lambda:source/'frontend-pm/dist-lan')
    schema=SimpleNamespace(schema_check=lambda *a: {'schema': recovery.SCHEMA},
        writer_state=lambda *a:'stopped',database_lock=lambda *a:nullcontext(),
        resume_external=lambda *a,**kw:events.append(('resume_external',)),
        resume_maintenance=lambda *a:events.append(('resume_maintenance',)),
        complete=lambda *a:events.append(('complete',)))
    outbound=SimpleNamespace(prepare=lambda *a:{'files':{},'receipt':{'database_fingerprint':'fingerprint'}},
        validate_receipt=Mock(),phase=lambda context,action:events.append(('outbound',action,context['release_id'])) or {'status':'enabled'},
        verify_completion=lambda *a:{'status':'verified'})
    # Keep the actual identity supplied to preparation available to the phase.
    outbound.prepare=lambda source,rev,rid:{'files':{},'receipt':{'database_fingerprint':'fingerprint'},'revision':rev,'release_id':rid}
    cloud=SimpleNamespace(activate=lambda *a:events.append(('beijing',)))
    static=SimpleNamespace(SSH_OPTIONS=[],manifest=lambda *a:{'index.html':'digest'},
        prepare=lambda *a:{},activate=Mock())
    modules={'publish':p,'schema_release':schema,'office_release':SimpleNamespace(health=lambda *a:None),
        'cloud_backend':cloud,'okki_outbound_release':outbound,
        'mail_worker_release':SimpleNamespace(prepare=lambda *a:{},invoke=lambda *a:{'status':a[1]}),
        'colorwork_routing':SimpleNamespace(prepare=lambda *a:[],activate=Mock()),
        'static_sync':static}
    def retention(*args,**kwargs):
        assert json.loads((state/'publish-current.json').read_text())['status']=='succeeded'
        return {'status':'succeeded'}
    modules['static_retention_release']=SimpleNamespace(run=retention)
    for name,module in modules.items():monkeypatch.setitem(sys.modules,name,module)
    return SimpleNamespace(plan=plan,events=events,state=state,cloud=cloud,outbound=outbound,modules=modules)


def test_prepare_has_no_service_or_activation_effect(simulated):
    result=recovery.execute(simulated.plan,True)
    assert result['status']=='prepared'
    assert simulated.events==[]
    assert not (simulated.state/'publish-success.json').exists()


def test_recovery_retains_identity_and_restores_writers_after_backends(simulated):
    result=recovery.execute(simulated.plan)
    assert result['revision']==recovery.REVISION
    assert simulated.events.index(('beijing',)) < simulated.events.index(('outbound','activate',recovery.RELEASE_ID))
    assert simulated.events.index(('outbound','activate',recovery.RELEASE_ID)) < simulated.events.index(('resume_external',))
    assert ('complete',) in simulated.events
    assert json.loads((simulated.state/'publish-current.json').read_text())['status']=='succeeded'
    assert not any('upgrade' in str(event) for event in simulated.events)


@pytest.mark.parametrize('fault', ['receipt','beijing'])
def test_stage_failure_never_writes_success_or_resumes_external(simulated,fault):
    fail=Mock(side_effect=RuntimeError('stage failure'))
    if fault=='receipt': simulated.outbound.validate_receipt=fail
    else: simulated.cloud.activate=fail
    with pytest.raises(RuntimeError,match='stage failure'):
        recovery.execute(simulated.plan)
    assert not (simulated.state/'publish-success.json').exists()
    assert ('resume_external',) not in simulated.events
    if fault=='receipt': assert simulated.events==[]


def test_unhealthy_office_is_stopped_and_confirmed_before_failure(simulated,monkeypatch):
    monkeypatch.setattr(recovery,'wait_ready',Mock(side_effect=RuntimeError('readiness deadline')))
    with pytest.raises(RuntimeError,match='readiness deadline'):
        recovery.execute(simulated.plan)
    assert ('stop','CommissionSystem') in simulated.events
    assert ('beijing',) not in simulated.events
    current=json.loads((simulated.state/'publish-current.json').read_text())
    assert current['recovery']=={'status':'failed','phase':'office-stopped','revision':recovery.REVISION}


def test_confirmed_office_checkpoint_resumes_without_restarting_office(simulated):
    journal,migration,inventory=facts()
    original=copy.deepcopy(journal)
    journal['completed']=['office']
    journal['recovery']={'phase':'beijing','status':'running','revision':recovery.REVISION}
    p=simulated.modules['publish']
    p.marker=lambda name:copy.deepcopy(journal if name=='publish-current' else
        {'revision':recovery.REVISION,'schema':recovery.SCHEMA} if name=='office-success' else migration)
    simulated.modules['schema_release'].writer_state=lambda writer,*a:'running' if writer['host']=='office' else 'stopped'
    # Actual synthetic NSSM readback matches the previously verified instance.
    old_run=p.run
    p.run=lambda args,**kw:'SERVICE_RUNNING' if len(args)>1 and args[0] not in {'git','ssh'} and args[1]=='status' else old_run(args,**kw)
    (simulated.state/('office-activation-original-'+recovery.REVISION+'.json')).write_text(json.dumps({'publish':original,'migration':migration}))
    result=recovery.execute(simulated.plan)
    assert result['revision']==recovery.REVISION
    assert not any(event[:1] in {('start',),('stop',)} for event in simulated.events)
    assert ('beijing',) in simulated.events


@pytest.mark.parametrize('field',['before','stopped'])
def test_checkpoint_rejects_changed_migration_baseline(simulated,field):
    journal,migration,inventory=facts()
    original=copy.deepcopy(journal)
    archived=copy.deepcopy(migration)
    journal['completed']=['office']
    journal['recovery']={'phase':'beijing','status':'running','revision':recovery.REVISION}
    if field=='before': migration['writers'][0]['before']='stopped'
    else: migration['stopped']=[]
    p=simulated.modules['publish']
    p.marker=lambda name:copy.deepcopy(journal if name=='publish-current' else
        {'revision':recovery.REVISION,'schema':recovery.SCHEMA} if name=='office-success' else migration)
    simulated.modules['schema_release'].writer_state=lambda *a:'running'
    (simulated.state/('office-activation-original-'+recovery.REVISION+'.json')).write_text(json.dumps({'publish':original,'migration':archived}))
    with pytest.raises(RuntimeError,match='baseline changed'):
        recovery.execute(simulated.plan,True)
    assert simulated.events==[]
