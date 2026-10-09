"""Mode-derived release regressions; systemd and DB observation mocked, no remote calls."""
import json
import hashlib
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from test_outbound_release import host  # noqa: F401
import okki_outbound_remote as remote
import okki_outbound_release as release

MODE='outbound-worker-v1'
PAUSED={'active':False,'enabled':False}


@pytest.fixture
def legacy_receipt(host):
    hashes = {}
    for name in remote.NAMES - {'okki_outbound_mode.mjs'}:
        path = (host.units if name.endswith(('.service', '.timer')) else host.root) / name
        path.write_bytes(name.encode())
        hashes[name] = hashlib.sha256(name.encode()).hexdigest()
    record = {'digest': hashlib.sha256(json.dumps(dict(sorted(hashes.items()))).encode()).hexdigest(),
              'revision': 'b'*40, 'release_id': 'd'*32, 'status': 'completed',
              'baseline': {'active': True, 'enabled': True}}
    journal = host.root / '.deploy-state/ark-outbound/release-current.json'
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps(record))
    return host, journal, record


def test_verified_old_receipt_prepare_then_full_release(legacy_receipt):
    host, journal, record = legacy_receipt
    assert host.call('prepare')['mode'] == 'legacy'
    assert json.loads(journal.read_text()) == record
    assert not any(c[:2] == ['systemctl','stop'] for c in host.commands)
    host.call('freeze');host.call('install');host.call('activate');host.call('verify')
    assert json.loads(journal.read_text())['mode'] == 'legacy'


@pytest.mark.parametrize('bad', ['mode','floor','bytes','schedule','partial','pending','revision','digest'])
def test_unconfirmed_old_receipt_never_permits_prepare(legacy_receipt,bad):
    host, journal, record = legacy_receipt
    if bad == 'mode':host.state['mode'] = MODE
    elif bad == 'floor':
        (journal.parent/'mode-floor.json').write_text(json.dumps({'mode':MODE,'database_fingerprint':'e'*64}))
    elif bad == 'bytes':(host.root/'okki_outbound_creator.mjs').write_text('unconfirmed')
    elif bad == 'schedule':host.state['active'] = False
    elif bad == 'partial':record['mode'] = 'legacy'
    elif bad == 'pending':record['status'] = 'installed_paused'
    elif bad == 'revision':record['revision'] = 'unknown'
    elif bad == 'digest':record['digest'] = 'f'*64
    journal.write_text(json.dumps(record))
    with pytest.raises(RuntimeError):host.call('prepare')
    assert not any(c[:2] == ['systemctl','stop'] for c in host.commands)
    assert json.loads(journal.read_text()) == record


@pytest.fixture
def mode_host(host,monkeypatch):
    state={'mode':MODE,'database_fingerprint':'e'*64,'held':False,'release_error':False}
    def observe(*_):
        return {key:state[key] for key in ('mode','database_fingerprint')}
    class Fence:
        def __init__(self,*_): self.observation=None
        def __enter__(self):
            self.observation=observe()
            state['held']=self.observation['mode']=='legacy'
            return self
        def check(self):
            if state.get('check_error'):raise RuntimeError('Injected check failure')
            if observe()!=self.observation:raise RuntimeError('Mode observation changed')
            return self.observation
        def __exit__(self,kind,*_):
            state['held']=False
            if kind is None and state['release_error']:raise RuntimeError('Mode release unavailable')
    monkeypatch.setattr(remote,'observe_mode',observe,raising=False)
    monkeypatch.setattr(remote,'ModeFence',Fence,raising=False)
    return SimpleNamespace(host=host,state=state)


@pytest.mark.parametrize('active,enabled',[(True,True),(False,True),(False,False),(True,False)])
def test_known_mode_activation_keeps_old_timer_persistently_paused(mode_host,active,enabled):
    host=mode_host.host
    host.state.update(active=active,enabled=enabled)
    host.call('freeze');host.call('install')
    result=host.call('activate')
    assert result['schedule']==PAUSED
    assert not host.state['active'] and not host.state['enabled']
    assert host.call('verify')['schedule']==PAUSED
    journal=json.loads((host.root/'.deploy-state/ark-outbound/release-current.json').read_text())
    assert journal['baseline']=={'active':active,'enabled':enabled}
    assert journal['target_schedule']==PAUSED and journal['mode']==MODE
    assert journal['release_confirmed'] is True and journal['status']=='completed'


def test_standalone_old_executor_activation_rejects_known_new_mode(mode_host):
    host=mode_host.host
    with pytest.raises(RuntimeError,match='legacy'):
        host.call('activate',coordinated=False,revision=None,release_id=None)
    assert not host.state['active'] and not host.state['enabled']


def test_seen_new_mode_remains_a_durable_floor_after_activation_failure(mode_host):
    host=mode_host.host;mode_host.state['mode']='legacy'
    host.call('freeze');host.call('install')
    mode_host.state.update(mode=MODE,check_error=True)
    with pytest.raises(RuntimeError,match='check failure'):host.call('activate')
    assert not host.state['active'] and not host.state['enabled']
    mode_host.state.update(mode='legacy',check_error=False)
    with pytest.raises(RuntimeError,match='mode|Mode'):host.call('activate')
    assert not host.state['active'] and not host.state['enabled']


@pytest.mark.parametrize('action', ['activate','verify','freeze'])
def test_numeric_schedule_forgery_is_not_a_valid_boolean_receipt(monkeypatch,action):
    baseline={'active':True,'enabled':True}
    data={'status':{'activate':'enabled','verify':'verified','freeze':'frozen'}[action],
          'digest':hashlib.sha256(b'{}').hexdigest(),'mode':MODE,'database_fingerprint':'e'*64,
          'revision':'a'*40,'release_id':'c'*32,'baseline':baseline,
          'schedule':baseline if action=='freeze' else dict(PAUSED),
          'target_schedule':dict(PAUSED),'release_confirmed':action!='freeze'}
    if action=='freeze':data['schedule']={'active':1,'enabled':1}
    else:data['target_schedule']={'active':0,'enabled':0}
    monkeypatch.setattr(release,'registered_writer',lambda *_:{'host':'owned.mock'})
    monkeypatch.setattr(release,'remote_python',Mock(return_value=SimpleNamespace(
        returncode=0,stdout=json.dumps(data),stderr='')))
    with pytest.raises(RuntimeError,match='receipt'):
        release.invoke(Path(__file__).resolve().parents[1],action,{},coordinated=True,
            revision='a'*40,release_id='c'*32,database_fingerprint='e'*64,mode=MODE,baseline=baseline)


@pytest.mark.parametrize('active,enabled',[(True,True),(False,True),(False,False),(True,False)])
def test_same_completed_release_full_retry_preserves_original_baseline(mode_host,active,enabled):
    host=mode_host.host;baseline={'active':active,'enabled':enabled}
    host.state.update(baseline)
    host.call('freeze');host.call('install');host.call('activate');host.call('verify')
    # The remote verify completed, but its response was lost before the caller could consume it.
    assert host.call('prepare')['mode']==MODE
    assert host.call('freeze')['baseline']==baseline
    host.call('install');host.call('activate');host.call('verify')
    journal=json.loads((host.root/'.deploy-state/ark-outbound/release-current.json').read_text())
    assert journal['baseline']==baseline and journal['release_confirmed'] is True


def test_mode_floor_survives_prepare_response_loss_and_rejects_different_database(mode_host):
    host=mode_host.host
    host.call('prepare')
    floor=host.root/'.deploy-state/ark-outbound/mode-floor.json'
    original=floor.read_bytes()
    mode_host.state['mode']='legacy'
    with pytest.raises(RuntimeError,match='mode|Mode'):host.call('prepare')
    mode_host.state.update(mode=MODE,database_fingerprint='f'*64)
    with pytest.raises(RuntimeError,match='mode|database'):host.call('prepare')
    assert floor.read_bytes()==original and not list(host.units.iterdir())


def test_release_failure_invalidates_success_without_claiming_service_drain(mode_host):
    host=mode_host.host
    host.call('freeze');host.call('install');mode_host.state['release_error']=True
    with pytest.raises(RuntimeError,match='release'):host.call('activate')
    journal=json.loads((host.root/'.deploy-state/ark-outbound/release-current.json').read_text())
    assert journal['status']=='failed_paused' and journal['release_confirmed'] is False
    assert journal['service_drain_confirmed'] is False
    assert not host.state['active'] and not host.state['enabled']
    with pytest.raises(RuntimeError,match='install'):host.call('activate')
    with pytest.raises(RuntimeError,match='receipt'):host.call('verify')


def test_legacy_fence_remains_held_through_timer_and_durable_checkpoint(mode_host,monkeypatch):
    host=mode_host.host;mode_host.state['mode']='legacy'
    host.call('freeze');host.call('install')
    original_run=remote.run;original_save=remote.save;events=[]
    def run(command,**kwargs):
        if command[:2] in (['systemctl','enable'],['systemctl','start']):
            assert mode_host.state['held'] is True;events.append(command[1])
        return original_run(command,**kwargs)
    def save(path,record):
        if record.get('status')=='target_verified':
            assert mode_host.state['held'] is True and record['release_confirmed'] is False
            events.append('checkpoint')
        if record.get('status')=='activated':
            assert mode_host.state['held'] is False and record['release_confirmed'] is True
            events.append('confirmed')
        original_save(path,record)
    monkeypatch.setattr(remote,'run',run);monkeypatch.setattr(remote,'save',save)
    assert host.call('activate')['schedule']=={'active':True,'enabled':True}
    assert events==['enable','start','checkpoint','confirmed']


def test_pause_only_endpoint_invalidates_activation_without_draining_or_changing_bytes(host):
    host.call('freeze');host.call('install');host.call('activate')
    before={path:path.read_bytes() for path in list(host.root.glob('*.mjs'))+list(host.units.iterdir())}
    host.state.update(pid='41',service='active')
    host.commands.clear()
    receipt=remote.execute({'action':'pause'})
    assert receipt['status']=='paused' and receipt['schedule']==PAUSED
    assert receipt['service_drain_confirmed'] is False and receipt['release_confirmed'] is False
    assert host.state['pid']=='41' and host.state['service']=='active'
    assert {path:path.read_bytes() for path in before}==before
    assert not any(command[:2] in (['systemctl','start'],['systemctl','kill']) or remote.SERVICE in command for command in host.commands)
    journal=json.loads((host.root/'.deploy-state/ark-outbound/release-current.json').read_text())
    assert journal['status']=='failed_paused' and journal['release_confirmed'] is False


def test_pause_only_rejects_additional_candidate_actions(host):
    with pytest.raises(ValueError,match='pause request'):
        remote.execute({'action':'pause','files':host.files})
    assert host.state['active'] is True and host.state['enabled'] is True


@pytest.mark.parametrize('part',['.deploy-state','.deploy-state/ark-outbound',
    '.deploy-state/ark-outbound/release.lock','.deploy-state/ark-outbound/release-current.json',
    '.deploy-state/ark-outbound/release-current.next','.deploy-state/ark-outbound/mode-floor.json',
    '.deploy-state/ark-outbound/pause-current.json','.deploy-state/ark-outbound/pause-current.next'])
def test_pause_rejects_redirected_state_paths_before_service_effects(host,monkeypatch,part):
    original=Path.is_symlink;redirected=host.root/part
    monkeypatch.setattr(Path,'is_symlink',lambda path:True if path==redirected else original(path))
    host.commands.clear()
    with pytest.raises(ValueError,match='symlink'):remote.execute({'action':'pause'})
    assert not host.commands and host.state['active'] is True
