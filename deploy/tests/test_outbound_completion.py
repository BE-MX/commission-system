"""Shared outbound completion/resume boundary, local effects only."""
from contextlib import nullcontext
import copy
import hashlib
import json
import subprocess
from types import SimpleNamespace
from pathlib import Path
import sys
from unittest.mock import Mock
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import schema_release as schema
import okki_outbound_release as release

REAL_PHASE=release.phase


def test_resume_cannot_restore_managed_outbound_without_verified_release(monkeypatch):
    monkeypatch.setattr(release,'pause_registered',Mock())
    monkeypatch.setattr(schema,'database_lock',lambda *_:nullcontext())
    monkeypatch.setattr(schema,'schema_check',Mock())
    control=Mock();monkeypatch.setattr(schema,'control',control)
    writer=schema.registered_writer('ark-okki-outbound-poller')
    with pytest.raises(RuntimeError,match='outbound|Outbound'):
        schema.resume_external([writer],{'python':'unused-owned-python','nssm':'unused'})
    control.assert_not_called()


@pytest.fixture
def completion(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'pause_registered',Mock())
    digest=hashlib.sha256(b'{}').hexdigest()
    receipt={'status':'verified','digest':digest,'revision':'a'*40,'release_id':'c'*32,
             'mode':'outbound-worker-v1','database_fingerprint':'e'*64,
             'baseline':{'active':True,'enabled':True},'schedule':{'active':False,'enabled':False},
             'target_schedule':{'active':False,'enabled':False},'release_confirmed':True}
    prepared={'root':tmp_path/'deploy','files':{},'revision':'a'*40,'release_id':'c'*32,
              'receipt':{'mode':'outbound-worker-v1','database_fingerprint':'e'*64},
              '_baseline':{'active':True,'enabled':True},'_mode_floor':'outbound-worker-v1'}
    journal={'revision':'a'*40,'release_id':'c'*32,'outbound':copy.deepcopy(receipt)}
    phase=Mock(return_value=copy.deepcopy(receipt));monkeypatch.setattr(release,'phase',phase)
    prepare=Mock(return_value=copy.deepcopy(prepared));monkeypatch.setattr(release,'prepare',prepare)
    monkeypatch.setattr(release,'artifact',Mock(return_value={}))
    return prepared,journal,phase,prepare,receipt


@pytest.mark.parametrize('key,value',[
    ('status','installed_paused'),('release_confirmed',False),('release_confirmed',1),
    ('digest','f'*64),('revision','b'*40),('release_id','d'*32),
    ('database_fingerprint','f'*64),('mode','legacy'),
    ('target_schedule',{'active':0,'enabled':0}),('schedule',{'active':True,'enabled':True}),
    ('baseline',{'active':False,'enabled':False})])
def test_invalid_recorded_completion_never_reaches_live_verify(completion,key,value):
    prepared,journal,phase,_,_=completion
    journal['outbound'][key]=value
    with pytest.raises(RuntimeError):release.verify_completion(prepared,journal)
    phase.assert_not_called()


@pytest.mark.parametrize('key,value',[
    ('release_confirmed',False),('database_fingerprint','f'*64),
    ('mode','legacy'),('target_schedule',{'active':0,'enabled':0})])
def test_live_verify_result_is_checked_again_before_success(completion,key,value):
    prepared,journal,phase,_,_=completion
    phase.return_value[key]=value
    with pytest.raises(RuntimeError):release.verify_completion(prepared,journal)
    phase.assert_called_once_with(prepared,'verify')


def test_actual_live_verify_is_required_even_for_previously_verified_receipt(completion):
    prepared,journal,phase,_,receipt=completion
    assert release.verify_completion(prepared,journal)==receipt
    phase.assert_called_once_with(prepared,'verify')


@pytest.mark.parametrize('missing',['outbound','release_id'])
def test_historical_completion_without_binding_is_rejected_before_remote(completion,missing):
    _,journal,phase,prepare,_=completion;del journal[missing]
    with pytest.raises(RuntimeError):release.completion_context(Path('owned-unused'),journal)
    prepare.assert_not_called();phase.assert_not_called()


@pytest.mark.parametrize('key,value',[('database_fingerprint','f'*64),('mode','legacy')])
def test_restored_context_requires_current_same_database_and_no_mode_downgrade(completion,key,value):
    _,journal,_,prepare,_=completion
    prepare.return_value['receipt'][key]=value
    with pytest.raises(RuntimeError,match='target or mode'):release.completion_context(Path('owned-unused'),journal)


def test_restored_context_preserves_original_baseline_and_known_mode(completion):
    _,journal,_,prepare,_=completion
    prepared=release.completion_context(Path('owned-unused'),journal)
    assert prepared['_baseline']=={'active':True,'enabled':True}
    assert prepared['_mode_floor']=='outbound-worker-v1'
    prepare.assert_called_once_with(Path('owned-unused'),'a'*40,'c'*32)


@pytest.mark.parametrize('mode',['legacy','outbound-worker-v1'])
def test_resume_managed_timer_uses_verified_target_without_baseline_start(completion,monkeypatch,mode):
    prepared,journal,phase,_,receipt=completion
    prepared['receipt']['mode']=prepared['_mode_floor']=receipt['mode']=mode
    receipt['schedule']=receipt['target_schedule']=dict(prepared['_baseline']) if mode=='legacy' else {'active':False,'enabled':False}
    journal['outbound']=copy.deepcopy(receipt);phase.return_value=copy.deepcopy(receipt)
    monkeypatch.setattr(schema,'database_lock',lambda *_:nullcontext())
    monkeypatch.setattr(schema,'schema_check',Mock())
    control=Mock();monkeypatch.setattr(schema,'control',control)
    managed=schema.registered_writer('ark-okki-outbound-poller')
    other={'kind':'pm2','host':'owned.mock','service':'other'}
    schema.resume_external([managed,other],{'python':'owned-unused','nssm':'unused'},outbound=prepared,journal=journal)
    phase.assert_called_once();control.assert_called_once_with(other,'start','unused')
    assert journal['outbound']['mode']==mode


def test_invalid_bound_resume_never_starts_any_external_writer(completion,monkeypatch):
    prepared,journal,phase,_,_=completion;journal['outbound']['release_confirmed']=False
    monkeypatch.setattr(schema,'database_lock',lambda *_:nullcontext())
    control=Mock();monkeypatch.setattr(schema,'control',control)
    managed=schema.registered_writer('ark-okki-outbound-poller')
    with pytest.raises(RuntimeError):
        schema.resume_external([{'kind':'pm2','service':'other'},managed],{'python':'unused','nssm':'unused'},outbound=prepared,journal=journal)
    phase.assert_not_called();control.assert_not_called()


def test_restored_legacy_history_cannot_lower_fresh_known_mode_floor(completion):
    _,journal,_,_,_=completion
    journal['outbound']['mode']='legacy'
    journal['outbound']['schedule']=journal['outbound']['target_schedule']={'active':True,'enabled':True}
    prepared=release.completion_context(Path('owned-unused'),journal)
    assert prepared['_mode_floor']=='outbound-worker-v1'


def test_current_verified_receipt_cannot_forge_legacy_after_fresh_mode_observation(completion):
    prepared,journal,phase,_,_=completion
    prepared['_mode_floor']='legacy';journal['outbound']['mode']='legacy'
    journal['outbound']['schedule']=journal['outbound']['target_schedule']={'active':True,'enabled':True}
    phase.return_value=copy.deepcopy(journal['outbound'])
    with pytest.raises(RuntimeError,match='mode receipt'):
        release.verify_completion(prepared,journal)


def test_rejected_completion_requires_confirmed_pause_compensation(completion,monkeypatch):
    prepared,journal,_,_,_=completion;journal['outbound']['release_confirmed']=False
    pause=Mock(side_effect=RuntimeError('Outbound pause cannot be confirmed'))
    monkeypatch.setattr(release,'pause_registered',pause)
    with pytest.raises(RuntimeError,match='pause cannot be confirmed'):
        release.verify_completion(prepared,journal)
    pause.assert_called_once_with()


@pytest.mark.parametrize('fault',['status','target','numeric','drain','remote_failed'])
def test_pause_receipt_never_hides_unconfirmed_target_or_state(monkeypatch,fault):
    receipt={'status':'paused','target':'/root/.openclaw/workspace/okki-sync',
             'schedule':{'active':False,'enabled':False},'target_schedule':{'active':False,'enabled':False},
             'release_confirmed':False,'service_drain_confirmed':False}
    if fault=='status':receipt['status']='enabled'
    if fault=='target':receipt['target']='/unregistered'
    if fault=='numeric':receipt['schedule']={'active':0,'enabled':0}
    if fault=='drain':receipt['service_drain_confirmed']=0
    monkeypatch.setattr(release,'registered_writer',lambda *_:{'host':'owned.mock'})
    remote=Mock(return_value=SimpleNamespace(returncode=1 if fault=='remote_failed' else 0,
                                            stdout=json.dumps(receipt),stderr='raw-secret-never-output'))
    monkeypatch.setattr(release,'remote_python',remote)
    with pytest.raises(RuntimeError,match='pause cannot be confirmed') as error:release.pause_registered()
    assert 'raw-secret' not in str(error.value)
    assert remote.call_args.args[2]=={'action':'pause'}


def test_phase_never_sends_a_lower_floor_than_prepared_observation(completion,monkeypatch):
    prepared,_,_,_,receipt=completion;prepared['_mode_floor']='legacy'
    invoke=Mock(return_value=receipt);monkeypatch.setattr(release,'invoke',invoke)
    REAL_PHASE(prepared,'verify')
    assert invoke.call_args.kwargs['mode']=='outbound-worker-v1'


def test_pause_only_client_requires_exact_success_control(monkeypatch):
    receipt={'status':'paused','target':'/root/.openclaw/workspace/okki-sync',
             'schedule':{'active':False,'enabled':False},'target_schedule':{'active':False,'enabled':False},
             'release_confirmed':False,'service_drain_confirmed':False}
    monkeypatch.setattr(release,'registered_writer',lambda *_:{'host':'owned.mock'})
    command=Mock(return_value=SimpleNamespace(returncode=0,stdout=json.dumps(receipt),stderr=''))
    monkeypatch.setattr(release,'remote_python',command)
    assert release.pause_registered()==receipt
    assert command.call_args.args[2]=={'action':'pause'}


@pytest.mark.parametrize('failure',[RuntimeError('raw-secret-driver-data'),OSError('raw-secret-io'),
    subprocess.TimeoutExpired('owned-command',1,output='raw-secret-output',stderr='raw-secret-stderr')])
def test_pause_transport_failure_is_safe_and_never_confirmation(monkeypatch,failure):
    monkeypatch.setattr(release,'registered_writer',lambda *_:{'host':'owned.mock'})
    monkeypatch.setattr(release,'remote_python',Mock(side_effect=failure))
    with pytest.raises(RuntimeError,match='pause cannot be confirmed') as error:release.pause_registered()
    assert 'raw-secret' not in str(error.value) and error.value.__suppress_context__ is True


def test_pause_registration_failure_is_unconfirmed_and_safe(monkeypatch):
    monkeypatch.setattr(release,'registered_writer',Mock(side_effect=ValueError('raw-secret-registration')))
    command=Mock();monkeypatch.setattr(release,'remote_python',command)
    with pytest.raises(RuntimeError,match='pause cannot be confirmed') as error:release.pause_registered()
    command.assert_not_called()
    assert 'raw-secret' not in str(error.value) and error.value.__suppress_context__ is True
