"""Local release regression tests: no production processes or database writes."""
import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

REAL_NODE_RUN = subprocess.run

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import okki_outbound_remote as remote
import okki_outbound_release as release


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / 'worker'; root.mkdir()
    units = tmp_path / 'units'; units.mkdir()
    node = tmp_path / 'node'; node.touch()
    (root / 'auth.js').touch()
    (root / 'node_modules').mkdir()
    config = root / '.ark-outbound.env'; config.touch(); config.chmod(0o600)
    # Windows cannot represent POSIX 0600: isolate the permission check as well.
    original_stat = Path.stat
    def stat(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path == config:
            return SimpleNamespace(st_mode=0o100600)
        return value
    monkeypatch.setattr(Path, 'stat', stat)
    monkeypatch.setattr(remote, 'ROOT', root)
    monkeypatch.setattr(remote, 'UNITS', units)
    monkeypatch.setattr(remote, 'NODE', str(node))
    state = {'active': True, 'enabled': True, 'pid': '0', 'service': 'inactive',
             'mode':'legacy','database_fingerprint':'e'*64,'held':False}
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if args[:3] == ['systemctl', 'show', remote.TIMER]:
            return 'LoadState=loaded\nActiveState=' + ('active' if state['active'] else 'inactive') + '\nUnitFileState=' + ('enabled' if state['enabled'] else 'disabled')
        if args[:3] == ['systemctl', 'show', remote.SERVICE]:
            return f"LoadState=loaded\nActiveState={state['service']}\nMainPID={state['pid']}"
        if args[:2] == ['systemctl', 'stop']: state['active'] = False
        if args[:2] == ['systemctl', 'start']: state['active'] = True
        if args[:2] == ['systemctl', 'enable']: state['enabled'] = True
        if args[:2] == ['systemctl', 'disable']: state['enabled'] = False
        return ''
    monkeypatch.setattr(remote, 'run', run)
    def observe(*_):
        return {key:state[key] for key in ('mode','database_fingerprint')}
    class Fence:
        def __init__(self,*_): self.observation=None
        def __enter__(self):
            self.observation=observe();state['held']=self.observation['mode']=='legacy';return self
        def check(self):
            if observe()!=self.observation:raise RuntimeError('Mode observation changed')
            return self.observation
        def __exit__(self,*_): state['held']=False
    monkeypatch.setattr(remote,'observe_mode',observe)
    monkeypatch.setattr(remote,'ModeFence',Fence)
    monkeypatch.setattr(remote.subprocess, 'run', Mock())
    # Avoid Windows symlink privilege requirements for staging-only dependencies.
    original_link = Path.symlink_to
    def link(path, target, *args, **kwargs):
        if path.name == 'node_modules': path.mkdir()
        elif path.name == 'auth.js': path.touch()
        else: original_link(path, target, *args, **kwargs)
    monkeypatch.setattr(Path, 'symlink_to', link)
    files = {name: {'content': base64.b64encode(name.encode()).decode(),
                    'sha256': hashlib.sha256(name.encode()).hexdigest()} for name in remote.NAMES}
    baseline={}
    def call(action,**kw):
        result=remote.execute({'action':action,'files':files,'coordinated':True,
            'revision':'a'*40,'release_id':'c'*32,'mode':'legacy','database_fingerprint':'e'*64,
            'baseline':baseline.get('value'),**kw})
        if action=='freeze' and 'value' not in baseline:baseline['value']=dict(result['baseline'])
        return result
    return SimpleNamespace(root=root, units=units, state=state, commands=commands, files=files,call=call)


def test_prepare_never_stops_or_installs(host):
    assert host.call('prepare')['status'] == 'prepared'
    assert not list(host.units.iterdir())
    assert not any(c[:2] == ['systemctl', 'stop'] for c in host.commands)


@pytest.mark.parametrize('active,enabled', [(True, True), (False, True), (False, False), (True, False)])
def test_coordinated_release_preserves_schedule_and_verifies_bytes(host, active, enabled):
    host.state.update(active=active, enabled=enabled)
    host.call('prepare'); host.call('freeze')
    assert not host.state['active']
    host.call('install'); host.call('activate')
    assert host.call('verify')['schedule'] == {'active': active, 'enabled': enabled}
    assert host.state['active'] == active and host.state['enabled'] == enabled
    for name in remote.NAMES:
        folder = host.units if name.endswith(('.service', '.timer')) else host.root
        assert (folder / name).read_text() == name


def test_retry_preserves_original_active_baseline(host):
    host.call('freeze')
    assert not host.state['active']
    assert host.call('freeze')['schedule']['active'] is True
    host.call('install'); host.call('activate'); host.call('verify')
    assert host.state['active']


def test_busy_service_with_inactive_state_still_blocks_install(host, monkeypatch):
    host.state['pid'] = '42'
    monkeypatch.setattr(remote.time, 'monotonic', Mock(side_effect=[0, 181]))
    with pytest.raises(RuntimeError, match='still running'):
        host.call('freeze')
    assert not host.state['active'] and not list(host.units.iterdir())
    assert not any(remote.SERVICE in c and c[1] in {'stop', 'kill'} for c in host.commands)


def test_pending_release_rejects_another_candidate_and_standalone(host):
    host.call('freeze')
    with pytest.raises(RuntimeError, match='requires inspection'):
        host.call('prepare', revision='b' * 40)
    for action in ['prepare', 'freeze', 'install', 'activate', 'verify']:
        with pytest.raises(RuntimeError, match='requires inspection'):
            host.call(action, release_id='d' * 32)
    with pytest.raises(RuntimeError, match='requires inspection'):
        remote.execute({'action': 'activate', 'files': host.files})
    name = 'okki_outbound_creator.mjs'
    host.files[name] = {'content': base64.b64encode(b'changed').decode(), 'sha256': hashlib.sha256(b'changed').hexdigest()}
    with pytest.raises(RuntimeError, match='requires inspection'):
        host.call('prepare')


def test_tampering_prevents_success(host):
    host.call('freeze'); host.call('install'); host.call('activate')
    (host.root / 'okki_outbound_creator.mjs').write_text('wrong version')
    with pytest.raises(RuntimeError, match='digest mismatch'):
        host.call('verify')
    journal = host.root / '.deploy-state/ark-outbound/release-current.json'
    assert json.loads(journal.read_text())['status'] != 'completed'


def test_new_schema_is_required_at_activation_even_with_pending_migration(host):
    host.call('prepare', allow_pending=True)
    assert 'linked_sync_id' not in host.commands[-1][-1]
    host.call('freeze', allow_pending=True)
    host.call('install', allow_pending=True); host.call('activate', allow_pending=True)
    probes = [c[-1] for c in host.commands if c[0] == remote.NODE and '--input-type=module' in c]
    assert 'linked_sync_id' in probes[-1] and 'last_error' in probes[-1]


def test_candidate_artifacts_not_launcher_checkout(tmp_path, monkeypatch):
    candidate = tmp_path / 'candidate'; (candidate / 'deploy').mkdir(parents=True)
    for name in remote.NAMES:
        path = candidate / 'deploy' / ('systemd' if name.endswith(('.service', '.timer')) else '') / name
        path.parent.mkdir(exist_ok=True); path.write_text('candidate-' + name)
    invoke = Mock(return_value={'status': 'prepared'}); monkeypatch.setattr(release, 'invoke', invoke)
    prepared = release.prepare(candidate, 'a' * 40, 'c' * 32)
    assert prepared['root'] == candidate / 'deploy'
    assert base64.b64decode(prepared['files']['okki_outbound_creator.mjs']['content']).startswith(b'candidate-')


def test_wrong_remote_receipt_rejected(monkeypatch):
    monkeypatch.setattr(release, 'remote_python', Mock(return_value=SimpleNamespace(
        returncode=0, stdout='{"status":"enabled","digest":"wrong"}', stderr='')))
    with pytest.raises(RuntimeError, match='does not match'):
        release.invoke(Path(__file__).resolve().parents[1], 'activate', {})


def test_outbound_uses_candidate_host_and_root_privileges(tmp_path, monkeypatch):
    writer = {'kind': 'systemd_timer', 'host': 'ubuntu@154.8.205.162',
              'service': 'ark-okki-outbound-poller', 'timer': 'ark-okki-outbound-poller.timer'}
    (tmp_path / 'platforms.json').write_text(json.dumps({'migration_writers': [writer]}))
    digest = hashlib.sha256(b'{}').hexdigest()
    remote_call = Mock(return_value=SimpleNamespace(returncode=0, stderr='',
                       stdout=json.dumps({'status': 'prepared', 'digest': digest,'mode':'legacy','database_fingerprint':'e'*64})))
    monkeypatch.setattr(release, 'remote_python', remote_call)
    release.invoke(tmp_path, 'prepare', {})
    assert remote_call.call_args.args[0] == 'ubuntu@154.8.205.162'
    assert remote_call.call_args.args[1] == tmp_path / 'okki_outbound_remote.py'
    assert remote_call.call_args.kwargs == {'sudo': True}


IMPORT_SIDE_EFFECT_GUARD = """
import fs from 'node:fs';
import cp from 'node:child_process';
import net from 'node:net';
import http from 'node:http';
import https from 'node:https';
import {syncBuiltinESMExports} from 'node:module';
const forbidden = [];
const deny = name => (...args) => {forbidden.push(name); throw Error('Business effect during import: '+name);};
for (const name of ['writeFileSync','appendFileSync','renameSync','mkdirSync','rmSync','unlinkSync']) fs[name]=deny('fs.'+name);
for (const name of ['writeFile','appendFile','rename','mkdir','rm','unlink']) fs.promises[name]=deny('fs.promises.'+name);
for (const name of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']) cp[name]=deny('cp.'+name);
net.Socket.prototype.connect=deny('net.Socket.connect');
http.request=deny('http.request'); http.get=deny('http.get');
https.request=deny('https.request'); https.get=deny('https.get');
globalThis.fetch=deny('fetch');
syncBuiltinESMExports();
const envBefore=JSON.stringify(process.env);
"""
IMPORT_SIDE_EFFECT_ASSERT = """
if(forbidden.length || JSON.stringify(process.env)!==envBefore) throw Error('Import changed business state/configuration');
"""


EXPECTED_ARTIFACTS = {
    'okki_outbound_poller.js', 'okki_outbound_creator.mjs', 'okki_outbound_mode.mjs',
    'ark-okki-outbound-poller.service', 'ark-okki-outbound-poller.timer',
}


def test_artifact_includes_every_imported_mode_dependency():
    files = release.artifact(Path(__file__).resolve().parents[1])
    assert set(files) == EXPECTED_ARTIFACTS
    mode = base64.b64decode(files['okki_outbound_mode.mjs']['content'])
    assert hashlib.sha256(mode).hexdigest() == files['okki_outbound_mode.mjs']['sha256']
    assert mode == (Path(__file__).resolve().parents[1] / 'okki_outbound_mode.mjs').read_bytes()


@pytest.fixture
def real_import_host(host, monkeypatch):
    node = shutil.which('node')
    assert node, 'These release contracts require a real local Node runtime'
    monkeypatch.setattr(remote, 'NODE', node)
    mocked_run = remote.run
    effects = []
    def run(args, **kwargs):
        # The database probe is the only Node call that receives protected config.
        # It remains mocked; syntax/module resolution uses the actual Node process.
        if args[0] == node and not any(str(a).startswith('--env-file=') for a in args):
            effects.append(args)
            guarded = list(args)
            if '--input-type=module' in args:
                code_index = guarded.index('-e') + 1
                guarded[code_index] = IMPORT_SIDE_EFFECT_GUARD + guarded[code_index] + IMPORT_SIDE_EFFECT_ASSERT
            result = REAL_NODE_RUN(guarded, check=True, text=True, capture_output=True,
                                   timeout=20, **kwargs)
            assert not result.stdout, 'Import executed a business entry point'
            return result.stdout.strip()
        return mocked_run(args, **kwargs)
    monkeypatch.setattr(remote, 'run', run)
    host.files.clear()
    host.files.update(release.artifact(Path(__file__).resolve().parents[1]))
    return SimpleNamespace(host=host, effects=effects)


def test_actual_module_import_rejects_missing_dependency_before_activation(real_import_host):
    host = real_import_host.host
    name = 'okki_outbound_creator.mjs'
    broken = b"import './dependency-that-is-missing.mjs';"
    host.files[name] = {'content': base64.b64encode(broken).decode(),
                        'sha256': hashlib.sha256(broken).hexdigest()}
    with pytest.raises(subprocess.CalledProcessError):
        host.call('prepare')
    assert not list(host.units.iterdir())
    assert not any(c[:2] == ['systemctl', 'stop'] for c in host.commands)
    assert any('--input-type=module' in c for c in real_import_host.effects)


def test_actual_import_of_candidate_is_read_only_and_does_not_run_creator(real_import_host):
    host = real_import_host.host
    assert host.call('prepare')['status'] == 'prepared'
    assert not list(host.units.iterdir())
    assert not (host.root / '.deploy-state/ark-outbound/release-current.json').exists()
    imports = [c for c in real_import_host.effects if '--input-type=module' in c]
    assert imports and len(imports[-1][-3:]) == 3
    assert {Path(url.removeprefix('file://')).name for url in imports[-1][-3:]} == {
        'okki_outbound_poller.js', 'okki_outbound_creator.mjs', 'okki_outbound_mode.mjs'}
    assert not any(c[:2] in (['systemctl', 'start'], ['systemctl', 'stop']) for c in host.commands)


def test_install_paused_precedes_activation_and_keeps_original_baseline(host):
    baseline = {'active': True, 'enabled': True}
    host.call('freeze')
    result = host.call('install')
    assert result['status'] == 'installed_paused'
    assert result['schedule'] == {'active': False, 'enabled': False}
    assert host.state['active'] is False and host.state['enabled'] is False
    journal = json.loads((host.root / '.deploy-state/ark-outbound/release-current.json').read_text())
    assert journal['baseline'] == baseline and journal['status'] == 'installed_paused'
    assert host.call('install')['status'] == 'installed_paused'
    assert json.loads((host.root / '.deploy-state/ark-outbound/release-current.json').read_text())['baseline'] == baseline
    for name in EXPECTED_ARTIFACTS:
        folder = host.units if name.endswith(('.service', '.timer')) else host.root
        assert (folder / name).is_file()


def test_coordinated_activation_without_installed_guard_is_rejected(host):
    host.call('freeze')
    with pytest.raises(RuntimeError, match='install'):
        host.call('activate')
    assert not list(host.units.iterdir()) and not host.state['active']


def test_install_requires_coordinated_frozen_release(host):
    with pytest.raises(RuntimeError, match='freeze'):
        host.call('install')
    with pytest.raises(ValueError, match='coordinated'):
        host.call('install', coordinated=False, revision=None, release_id=None)


def test_install_import_failure_keeps_old_timer_paused(host, monkeypatch):
    host.call('freeze')
    original = remote.run
    def run(args, **kwargs):
        if args[0] == remote.NODE and '--input-type=module' in args and not any(str(a).startswith('--env-file=') for a in args):
            raise RuntimeError('Module import failed')
        return original(args, **kwargs)
    monkeypatch.setattr(remote, 'run', run)
    with pytest.raises(RuntimeError, match='Module import failed'):
        host.call('install')
    assert not host.state['active'] and not list(host.units.iterdir())
    assert json.loads((host.root / '.deploy-state/ark-outbound/release-current.json').read_text())['status'] == 'frozen'


@pytest.mark.parametrize('fault', ['status', 'baseline', 'boolean'])
def test_unknown_or_corrupted_journal_never_recaptures_baseline(host, fault):
    host.call('freeze')
    path = host.root / '.deploy-state/ark-outbound/release-current.json'
    data = json.loads(path.read_text())
    if fault == 'status': data['status'] = 'unknown'
    elif fault == 'baseline': data.pop('baseline')
    else: data['baseline']['active'] = 1
    path.write_text(json.dumps(data))
    host.commands.clear()
    with pytest.raises(RuntimeError, match='requires inspection'):
        host.call('freeze')
    assert json.loads(path.read_text()) == data
    assert not any(c[0] == 'systemctl' for c in host.commands)


def test_second_file_replace_failure_preserves_pause_backups_and_recovers(host, monkeypatch):
    destinations = [((host.units if name.endswith(('.service','.timer')) else host.root) / name)
                    for name in EXPECTED_ARTIFACTS]
    originals = {path: ('old-' + path.name).encode() for path in destinations}
    for path, body in originals.items(): path.write_bytes(body)
    host.call('freeze')
    replace = remote.os.replace
    mutations = []
    def fail_second(source, destination):
        if destination in originals:
            mutations.append(destination)
            if len(mutations) == 2: raise OSError('Second managed file replacement failed')
        return replace(source, destination)
    monkeypatch.setattr(remote.os, 'replace', fail_second)
    with pytest.raises(OSError, match='Second managed'):
        host.call('install')
    assert len(mutations) == 2
    assert sum(path.read_bytes() != old for path, old in originals.items()) == 1
    assert host.state['active'] is False and host.state['enabled'] is False
    journal_path = host.root / '.deploy-state/ark-outbound/release-current.json'
    assert json.loads(journal_path.read_text())['status'] == 'frozen'
    assert not any(c[:2] == ['systemctl','start'] for c in host.commands)
    monkeypatch.setattr(remote.os, 'replace', replace)
    receipt = host.call('install')
    assert receipt['status'] == 'installed_paused'
    assert receipt['changed_files'] == 4
    journal = json.loads(journal_path.read_text())
    assert journal['baseline'] == {'active':True,'enabled':True}
    backup = host.root / '.deploy-state/ark-outbound' / receipt['digest'] / 'backup'
    for path, old in originals.items():
        assert path.read_text() == path.name
        assert (backup / path.name).read_bytes() == old


def test_lost_installed_receipt_preserves_installed_phase_on_retry(host, monkeypatch):
    host.call('freeze')
    original = remote.save
    def lost_ack(path, record):
        original(path, record)
        if record['status'] == 'installed_paused': raise RuntimeError('Client lost installed receipt')
    monkeypatch.setattr(remote, 'save', lost_ack)
    with pytest.raises(RuntimeError, match='lost installed receipt'):
        host.call('install')
    journal_path = host.root / '.deploy-state/ark-outbound/release-current.json'
    committed = json.loads(journal_path.read_text())
    assert committed['status'] == 'installed_paused'
    assert not host.state['active'] and not host.state['enabled']
    monkeypatch.setattr(remote, 'save', original)
    assert host.call('prepare')['status'] == 'prepared'
    assert host.call('freeze')['schedule'] == committed['baseline']
    assert json.loads(journal_path.read_text())['status'] == 'installed_paused'
    receipt = host.call('install')
    assert receipt['changed_files'] == 0 and receipt['status'] == 'installed_paused'
    assert json.loads(journal_path.read_text())['baseline'] == committed['baseline']
    assert not any(c[:2] == ['systemctl','start'] for c in host.commands)


@pytest.mark.parametrize('field,value', [
    ('revision', 'b'*40), ('release_id', 'd'*32),
    ('schedule', {'active':True,'enabled':False}),
    ('schedule', {'active':False,'enabled':0}),
    ('schedule', {'active':False}),
])
def test_install_receipt_rejects_wrong_identity_or_unconfirmed_pause(monkeypatch, field, value):
    data = {'status':'installed_paused','digest':hashlib.sha256(b'{}').hexdigest(),
            'revision':'a'*40,'release_id':'c'*32,'schedule':{'active':False,'enabled':False},
            'baseline':{'active':True,'enabled':True},'target_schedule':{'active':False,'enabled':False},
            'mode':'legacy','database_fingerprint':'e'*64,'release_confirmed':False}
    data[field] = value
    monkeypatch.setattr(release, 'registered_writer', lambda *_: {'host':'isolated.test'})
    monkeypatch.setattr(release, 'remote_python', Mock(return_value=SimpleNamespace(
        returncode=0, stdout=json.dumps(data), stderr='')))
    with pytest.raises(RuntimeError, match=('mode receipt' if field in {'revision','release_id'} else 'paused installation receipt')):
        release.invoke(Path(__file__).resolve().parents[1], 'install', {}, coordinated=True,
                       revision='a'*40, release_id='c'*32)


def test_install_receipt_accepts_same_candidate_and_actual_pause(monkeypatch):
    data = {'status':'installed_paused','digest':hashlib.sha256(b'{}').hexdigest(),
            'revision':'a'*40,'release_id':'c'*32,'schedule':{'active':False,'enabled':False},
            'baseline':{'active':True,'enabled':True},'target_schedule':{'active':False,'enabled':False},
            'mode':'legacy','database_fingerprint':'e'*64,'release_confirmed':False}
    monkeypatch.setattr(release, 'registered_writer', lambda *_: {'host':'isolated.test'})
    monkeypatch.setattr(release, 'remote_python', Mock(return_value=SimpleNamespace(
        returncode=0, stdout=json.dumps(data), stderr='')))
    assert release.invoke(Path(__file__).resolve().parents[1], 'install', {}, coordinated=True,
                          revision='a'*40, release_id='c'*32) == data


@pytest.mark.parametrize('name', ['.env', '.ark-outbound.env'])
def test_staging_configuration_is_rejected_before_real_import(real_import_host, name):
    host = real_import_host.host
    first = host.call('prepare')
    stage = host.root / '.deploy-state/ark-outbound' / first['digest']
    (stage / name).write_text('ARK_DB_NAME=untrusted-staging-configuration')
    old_effects = list(real_import_host.effects)
    with pytest.raises(RuntimeError, match='must not contain runtime configuration'):
        host.call('prepare')
    assert real_import_host.effects == old_effects
    assert not list(host.units.iterdir())


def test_pending_migration_never_skips_schema_probe_at_install(host, monkeypatch):
    host.call('prepare', allow_pending=True)
    host.call('freeze', allow_pending=True)
    original = remote.run
    probes = []
    def run(args, **kwargs):
        if args[0] == remote.NODE and any(str(a).startswith('--env-file=') for a in args):
            probes.append(args[-1])
            assert 'linked_sync_id' in args[-1] and 'last_error' in args[-1]
            raise RuntimeError('Required schema column missing')
        return original(args, **kwargs)
    monkeypatch.setattr(remote, 'run', run)
    with pytest.raises(RuntimeError, match='Required schema column missing'):
        host.call('install', allow_pending=True)
    assert len(probes) == 1
    assert not list(host.units.iterdir()) and not host.state['active'] and not host.state['enabled']
    journal = json.loads((host.root / '.deploy-state/ark-outbound/release-current.json').read_text())
    assert journal['status'] == 'frozen'


def test_installed_mode_tampering_blocks_freeze_retry_without_downgrading_receipt(host):
    host.call('freeze'); host.call('install')
    path = host.root / '.deploy-state/ark-outbound/release-current.json'
    receipt = json.loads(path.read_text())
    (host.root / 'okki_outbound_mode.mjs').write_text('tampered-active-module')
    with pytest.raises(RuntimeError, match='digest mismatch'):
        host.call('freeze')
    assert json.loads(path.read_text()) == receipt
    assert not host.state['active'] and not host.state['enabled']
