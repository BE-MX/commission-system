from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
import publish as p
import office_release as office
import recover_office_readiness as recovery
import remote_backend as remote
import static_sync


@pytest.fixture
def checkpoint(tmp_path, monkeypatch):
    live = tmp_path / 'live'
    state = live / '.deploy_state'
    source = state / 'sources' / ('b' * 40)
    source.mkdir(parents=True)
    service = {'Application': str(live / 'python.exe'), 'AppDirectory': str(live / 'backend'),
        'AppParameters': '-m uvicorn app.main:app --host 0.0.0.0 --port 8001'}
    outbound = dict(status='installed_paused', mode='legacy', revision='b'*40, release_id='c'*32,
        database_fingerprint='d'*64, baseline={'active': True, 'enabled': True})
    journal = dict(status='failed', completed=[], scope='office-and-cloud', revision='b'*40,
        release_id='c'*32, outbound=outbound, mail_worker={'baseline': {'was_active': False, 'was_enabled': False}})
    raw = json.dumps(journal).encode()
    (state / 'publish-current.json').write_bytes(raw)
    plan = dict(previous='a'*40, revision='b'*40, release_id='c'*32, schema='197',
        journal_sha256=hashlib.sha256(raw).hexdigest(), service=service, service_state='SERVICE_STOPPED')
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(plan))
    running = [False]
    commands = []
    def run(args, cwd=None, **kwargs):
        commands.append(args)
        if args[:3] == ['git', 'rev-parse', 'HEAD']: return 'b'*40 if cwd == source else 'a'*40
        if args[:2] == ['git', 'status']: return ''
        if args[1:3] == ['get', 'CommissionSystem']: return service[args[3]]
        if args[1] == 'status': return 'SERVICE_RUNNING' if running[0] else 'SERVICE_STOPPED'
        if args[1] in {'start', 'stop'}: running[0] = args[1] == 'start'
        return ''
    monkeypatch.setattr(p, 'ROOT', live)
    monkeypatch.setattr(p, 'STATE', state)
    monkeypatch.setattr(p, 'run', run)
    monkeypatch.setattr(p, 'marker', lambda name: dict(revision='a'*40, schema='197') if name == 'office-success' else {'files': {'index.html': 'hash'}})
    monkeypatch.setattr(static_sync, 'manifest', lambda path: {'index.html': 'hash'})
    monkeypatch.setattr(remote, 'database_lock', lambda *a: nullcontext())
    monkeypatch.setattr(remote, 'schema_check', lambda *a: dict(schema='197', pending=[]))
    observation = {k: outbound[k] for k in ('mode', 'database_fingerprint')}
    monkeypatch.setattr(remote, 'protocol_observation', lambda *a: observation)
    guard = Mock()
    monkeypatch.setattr(remote, 'rollback_guard', lambda *a: nullcontext(guard))
    monkeypatch.setattr(office, 'wait_ready', Mock())
    monkeypatch.setattr(office, 'ROOT', live)
    publish = Mock(return_value={'status': 'succeeded'})
    monkeypatch.setattr(p, 'publish', publish)
    args = SimpleNamespace(prepare_only=False, recover_office_readiness=str(path), revision='e'*40, no_pull=True)
    return SimpleNamespace(**locals())


def test_restores_only_office_and_resumes_original_binding(checkpoint):
    c = checkpoint
    recovery.execute(c.path, c.args)
    c.guard.check.assert_called_once()
    resumed = c.publish.call_args.args[0]
    assert resumed.revision == c.plan['revision'] and resumed.no_pull
    assert resumed.recover_office_readiness is None
    assert resumed._readiness_checkpoint == c.plan
    assert [a for a in c.commands if len(a) > 1 and a[1] == 'start'] == [[c.commands[-1][0], 'start', 'CommissionSystem']]
    saved = json.loads(next(c.state.glob('office-readiness-recovery-*.json')).read_text())
    assert saved['original'] == c.journal
    assert saved['original']['outbound']['baseline'] == {'active': True, 'enabled': True}


@pytest.mark.parametrize('failure', ['schema', 'protocol', 'static', 'journal'])
def test_drift_never_starts_service_or_republishes(checkpoint, monkeypatch, failure):
    c = checkpoint
    if failure == 'schema': monkeypatch.setattr(remote, 'schema_check', lambda *a: dict(schema='198', pending=[]))
    if failure == 'protocol': monkeypatch.setattr(remote, 'protocol_observation', lambda *a: dict(mode='outbound-worker-v1', database_fingerprint='d'*64))
    if failure == 'static': monkeypatch.setattr(static_sync, 'manifest', lambda *a: {})
    if failure == 'journal': (c.state / 'publish-current.json').write_text('{}')
    with pytest.raises(RuntimeError): recovery.execute(c.path, c.args)
    assert not c.running[0]
    assert not any(len(a) > 1 and a[1] == 'start' for a in c.commands)
    c.publish.assert_not_called()


def test_startup_failure_stops_and_preserves_failed_journal(checkpoint, monkeypatch):
    c = checkpoint
    monkeypatch.setattr(office, 'wait_ready', Mock(side_effect=RuntimeError('startup failed')))
    with pytest.raises(RuntimeError, match='startup failed'): recovery.execute(c.path, c.args)
    assert not c.running[0]
    assert json.loads((c.state / 'publish-current.json').read_text()) == c.journal
    c.publish.assert_not_called()


def test_prepare_is_read_only(checkpoint):
    c = checkpoint
    c.args.prepare_only = True
    assert recovery.execute(c.path, c.args)['status'] == 'prepared'
    assert not list(c.state.glob('office-readiness-recovery-*.json'))
    c.publish.assert_not_called()


def test_service_only_recovers_availability_then_resumes_without_second_start(checkpoint):
    c = checkpoint
    c.args.restore_service_only = True
    result = recovery.execute(c.path, c.args)
    assert c.running[0] and result['status'] == 'old_service_restored'
    c.publish.assert_not_called()
    assert json.loads((c.state / 'publish-current.json').read_text()) == c.journal
    c.args.restore_service_only = False
    recovery.execute(result['resume_plan'], c.args)
    c.publish.assert_called_once()
    assert len([a for a in c.commands if len(a) > 1 and a[1] == 'start']) == 1


@pytest.mark.parametrize('fail', [False, True])
def test_running_service_is_never_restarted_or_stopped(checkpoint, monkeypatch, fail):
    c = checkpoint
    c.plan['service_state'] = 'SERVICE_RUNNING'
    c.path.write_text(json.dumps(c.plan))
    c.running[0] = True
    if fail:
        monkeypatch.setattr(office, 'wait_ready', Mock(side_effect=RuntimeError('not ready')))
        with pytest.raises(RuntimeError, match='not ready'): recovery.execute(c.path, c.args)
        c.publish.assert_not_called()
    else:
        recovery.execute(c.path, c.args)
        c.publish.assert_called_once()
    assert c.running[0]
    assert not any(len(a)>1 and a[1] in {'start','stop'} for a in c.commands)


def test_already_activated_office_prefix_requires_candidate_and_running_state(checkpoint):
    c=checkpoint
    plan=dict(c.plan, previous='b'*40, service_state='SERVICE_RUNNING')
    journal=dict(c.journal, completed=['office','beijing-backend'])
    success={'revision':'b'*40,'schema':'197'}
    recovery.validate(plan,journal,success,'b'*40)
    for completed in [['beijing-backend'],['office','unknown'],['office','beijing-backend','unknown']]:
        with pytest.raises(RuntimeError): recovery.validate(plan,dict(journal,completed=completed),success,'b'*40)
    with pytest.raises(RuntimeError): recovery.validate(dict(plan,service_state='SERVICE_STOPPED'),journal,success,'b'*40)


def test_legacy_receipt_rejects_same_plan_checkpoint(checkpoint):
    c=checkpoint
    legacy=c.state/('office-readiness-recovery-'+c.plan['release_id']+'.json')
    legacy.write_text(json.dumps({'plan':{'journal_sha256':c.plan['journal_sha256']}}))
    with pytest.raises(RuntimeError,match='already attempted'): recovery.execute(c.path,c.args)
    c.publish.assert_not_called()
    assert not c.running[0]
