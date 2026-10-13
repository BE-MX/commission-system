"""Exact completion checkpoint; all service, database and provider effects replaced."""
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import recover_release_completion as recovery
from static_retention import artifact_id


def facts():
    inventory = json.loads((Path(__file__).parents[1] / 'platforms.json').read_text())
    migration = {'status': 'upgraded', 'schema': recovery.SCHEMA, 'database': '183_portal_password_login',
        'pending': recovery.PENDING, 'writers': [{'writer': w, 'before': 'running'} for w in inventory['migration_writers']],
        'stopped': inventory['migration_writers'][:4]}
    receipt = {'status': 'enabled', 'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID,
        'digest': 'a'*64, 'database_fingerprint': 'b'*64, 'mode': 'legacy',
        'baseline': {'active': True, 'enabled': True}}
    journal = {'revision': recovery.REVISION, 'release_id': recovery.RELEASE_ID, 'status': 'failed',
        'completed': recovery.COMPLETED, 'recovery': {'phase': 'outbound-activate'}, 'outbound': receipt}
    original = copy.deepcopy(journal); original['completed'] = []
    original['outbound']['status'] = 'installed_paused'
    archived = {'publish': original, 'migration': copy.deepcopy(migration)}
    remote = {'record': {**receipt, 'status': 'failed_paused', 'release_confirmed': False,
        'target_schedule': {'active': False, 'enabled': False}},
        'timer': {'ActiveState': 'inactive', 'UnitFileState': 'disabled'},
        'service': {'ActiveState': 'inactive', 'MainPID': '0'}}
    return copy.deepcopy((journal, migration, archived, inventory, remote))


@pytest.mark.parametrize('target,key,value', [
    ('journal','status','succeeded'), ('journal','release_id','c'*32),
    ('journal','completed',['office']), ('migration','schema','185_announcement_push_option'),
    ('migration','stopped',[]), ('migration','database','182_announcement_reads')])
def test_checkpoint_drift_rejected(target,key,value):
    journal,migration,archived,inventory,_=facts()
    (journal if target=='journal' else migration)[key]=value
    with pytest.raises(RuntimeError,match='checkpoint'):
        recovery.validate(journal,migration,archived,inventory)


@pytest.mark.parametrize('part,key,value', [('record','release_id','x'*32),
    ('record','digest','f'*64), ('record','status','activated'),
    ('timer','ActiveState','active'), ('service','MainPID','42')])
def test_pause_must_be_positive_not_inferred(part,key,value):
    journal,_,_,_,remote=facts(); remote[part][key]=value
    with pytest.raises(RuntimeError,match='paused and drained'):
        recovery.validate_paused(remote,journal['outbound'])


def test_original_timer_baseline_cannot_be_replaced_at_completion():
    journal,migration,archived,inventory,_=facts()
    journal['outbound']['baseline']={'active':False,'enabled':False}
    with pytest.raises(RuntimeError,match='activation receipt'):
        recovery.validate(journal,migration,archived,inventory)


@pytest.fixture
def simulated(tmp_path,monkeypatch):
    live=tmp_path/'live'; state=live/'.deploy_state'; source=state/'sources'/recovery.REVISION
    (source/'deploy').mkdir(parents=True); (live/'backend').mkdir()
    journal,migration,archived,inventory,remote=facts()
    (source/'deploy/platforms.json').write_text(json.dumps(inventory))
    (state/('office-activation-original-'+recovery.REVISION+'.json')).write_text(json.dumps(archived))
    plan=tmp_path/'plan.json'; plan.write_text(json.dumps({'revision':recovery.REVISION,'release_id':recovery.RELEASE_ID}))
    files={'index.html':'a'*64}; ident=artifact_id(files)
    events=[]; preparation=[]
    def marker(name):
        if name=='publish-current':return copy.deepcopy(journal)
        if name=='schema-writers':return copy.deepcopy(migration)
        if name=='office-success':return {'revision':recovery.REVISION,'schema':recovery.SCHEMA}
        if name.startswith('build-'):return {'digest':'d'*64,'files':files}
        raise AssertionError('Unexpected marker '+name)
    def run(args,**kwargs):
        if args[:3]==['git','rev-parse','HEAD']:return recovery.REVISION
        if args[:2]==['git','status']:return ''
        if args[1:3]==['get','CommissionSystem']:
            return {'Application':str(live/'python.exe'),'AppDirectory':str(live/'backend'),
                'AppParameters':'-m uvicorn app.main:app --host 0.0.0.0 --port 8001'}[args[3]]
        raise AssertionError('No service start, app activation, seed or migration allowed')
    def save(path,data):path.write_text(json.dumps(data))
    p=SimpleNamespace(ROOT=live,STATE=state,BJ='beijing',deployment_lock=lambda:nullcontext(),
        marker=marker,run=run,atomic_json=save)
    schema=SimpleNamespace(schema_check=lambda *a:{'schema':recovery.SCHEMA,'database':recovery.SCHEMA,'pending':[]},
        writer_state=lambda writer,*a:'running' if writer['service'] in {'CommissionSystem','WhatsAppConnector','ark-backend'} else 'stopped',
        resume_external=lambda *a,**kw:events.append(('resume',)),resume_maintenance=lambda *a:events.append(('maintenance',)),
        complete=lambda *a:events.append(('complete',)))
    def prepare(path,revision,release_id):
        preparation.append((str(path),revision,release_id))
        return {'revision':revision,'release_id':release_id,'files':{},
            'receipt':{'database_fingerprint':'b'*64,'mode':'legacy'}}
    def phase(context,action):
        events.append(('outbound',action,context['revision'],context['release_id']))
        return {**journal['outbound'],'status':{'freeze':'frozen','install':'installed_paused','activate':'enabled'}[action]}
    def verify(context,current):
        events.append(('verify',context['release_id']))
        return {**journal['outbound'],'status':'verified'}
    outbound=SimpleNamespace(artifact=lambda path:{'same-five-files':True},prepare=prepare,
        validate_receipt=Mock(),phase=phase,verify_completion=verify)
    static=SimpleNamespace(SSH_OPTIONS=[],manifest=lambda path:files,
        remote=lambda host,request:{'missing':[],'initialized':True,'artifact':ident,'active_artifact':ident})
    def mail_prepare(path,rev,rid):
        events.append(('mail-prepare',rev,rid));return {'revision':rev,'release_id':rid}
    def mail_invoke(context,action):
        events.append(('mail',action,context['release_id']));return {'revision':context['revision'],'status':action}
    def retention(*args,**kwargs):
        assert json.loads((state/'publish-current.json').read_text())['status']=='succeeded'
        events.append(('retention',));return {'status':'succeeded'}
    modules={'publish':p,'schema_release':schema,'office_release':SimpleNamespace(health=lambda port:None),
        'static_sync':static,'okki_outbound_release':outbound,
        'mail_worker_release':SimpleNamespace(prepare=mail_prepare,invoke=mail_invoke),
        'static_retention_release':SimpleNamespace(run=retention)}
    for name,module in modules.items():monkeypatch.setitem(sys.modules,name,module)
    monkeypatch.setattr(recovery,'inspect_remote',lambda *a:copy.deepcopy(remote))
    return SimpleNamespace(plan=plan,state=state,events=events,preparation=preparation,journal=journal,
        migration=migration,modules=modules)


def test_prepare_only_never_activates_or_resumes(simulated):
    assert recovery.execute(simulated.plan,True)['status']=='prepared'
    assert simulated.events==[] and len(simulated.preparation)==1
    assert not (simulated.state/'publish-success.json').exists()


def test_exact_identity_and_order_without_application_or_static_changes(simulated):
    result=recovery.execute(simulated.plan)
    assert result['revision']==recovery.REVISION
    assert [e[1] for e in simulated.events if e[0]=='outbound']==['freeze','install','activate']
    assert all(e[2:]==(recovery.REVISION,recovery.RELEASE_ID) for e in simulated.events if e[0]=='outbound')
    assert simulated.events.index(('verify',recovery.RELEASE_ID))<simulated.events.index(('resume',))
    assert simulated.events.index(('maintenance',))<simulated.events.index(('complete',))
    assert simulated.events[-1]==('retention',)
    assert json.loads((simulated.state/'publish-current.json').read_text())['outbound']['status']=='verified'


@pytest.mark.parametrize('stage',['activate','verify','resume','mail','maintenance'])
def test_failure_never_completes_or_claims_success(simulated,stage):
    fail=Mock(side_effect=RuntimeError('injected stage failure'))
    if stage=='activate':simulated.modules['okki_outbound_release'].phase=fail
    elif stage=='verify':simulated.modules['okki_outbound_release'].verify_completion=fail
    elif stage=='resume':simulated.modules['schema_release'].resume_external=fail
    elif stage=='mail':simulated.modules['mail_worker_release'].invoke=fail
    else:simulated.modules['schema_release'].resume_maintenance=fail
    with pytest.raises(RuntimeError,match='injected'):
        recovery.execute(simulated.plan)
    assert ('complete',) not in simulated.events
    assert not (simulated.state/'publish-success.json').exists()


def test_static_readback_drift_prevents_all_activation(simulated):
    simulated.modules['static_sync'].remote=lambda *a:{'missing':[],'initialized':True,'artifact':'bad','active_artifact':'bad'}
    with pytest.raises(RuntimeError,match='static artifact'):
        recovery.execute(simulated.plan)
    assert simulated.events==[]


def test_other_office_command_cannot_borrow_healthy_port(simulated):
    p=simulated.modules['publish']; original=p.run
    def changed(args,**kwargs):
        if args[1:]==['get','CommissionSystem','AppParameters']:
            return '-m uvicorn another.app:app --port 8001'
        return original(args,**kwargs)
    p.run=changed
    with pytest.raises(RuntimeError,match='installed runtime'):
        recovery.execute(simulated.plan,True)
    assert simulated.events==[] and simulated.preparation==[]


def test_receipt_is_persisted_before_later_failure(simulated):
    simulated.modules['schema_release'].resume_external=Mock(side_effect=RuntimeError('resume failure'))
    with pytest.raises(RuntimeError,match='resume failure'):recovery.execute(simulated.plan)
    current=json.loads((simulated.state/'publish-current.json').read_text())
    assert current['outbound']['status']=='verified'
    assert current['recovery']['phase']=='completion-writers-resume'
