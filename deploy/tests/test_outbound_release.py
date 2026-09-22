"""Local release regression tests: no production processes or database writes."""
import base64
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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
    state = {'active': True, 'enabled': True, 'pid': '0', 'service': 'inactive'}
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
    return SimpleNamespace(root=root, units=units, state=state, commands=commands, files=files,
                           call=lambda action, **kw: remote.execute({'action': action, 'files': files, 'coordinated': True,
                                                                    'revision': 'a' * 40, 'release_id': 'c' * 32, **kw}))


def test_prepare_never_stops_or_installs(host):
    assert host.call('prepare')['status'] == 'prepared'
    assert not list(host.units.iterdir())
    assert not any(c[:2] == ['systemctl', 'stop'] for c in host.commands)


@pytest.mark.parametrize('active,enabled', [(True, True), (False, True), (False, False), (True, False)])
def test_coordinated_release_preserves_schedule_and_verifies_bytes(host, active, enabled):
    host.state.update(active=active, enabled=enabled)
    host.call('prepare'); host.call('freeze')
    assert not host.state['active']
    host.call('activate')
    assert host.call('verify')['schedule'] == {'active': active, 'enabled': enabled}
    assert host.state['active'] == active and host.state['enabled'] == enabled
    for name in remote.NAMES:
        folder = host.units if name.endswith(('.service', '.timer')) else host.root
        assert (folder / name).read_text() == name


def test_retry_preserves_original_active_baseline(host):
    host.call('freeze')
    assert not host.state['active']
    assert host.call('freeze')['schedule']['active'] is True
    host.call('activate'); host.call('verify')
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
    for action in ['prepare', 'freeze', 'activate', 'verify']:
        with pytest.raises(RuntimeError, match='requires inspection'):
            host.call(action, release_id='d' * 32)
    with pytest.raises(RuntimeError, match='requires inspection'):
        remote.execute({'action': 'activate', 'files': host.files})
    name = 'okki_outbound_creator.mjs'
    host.files[name] = {'content': base64.b64encode(b'changed').decode(), 'sha256': hashlib.sha256(b'changed').hexdigest()}
    with pytest.raises(RuntimeError, match='requires inspection'):
        host.call('prepare')


def test_tampering_prevents_success(host):
    host.call('freeze'); host.call('activate')
    (host.root / 'okki_outbound_creator.mjs').write_text('wrong version')
    with pytest.raises(RuntimeError, match='digest mismatch'):
        host.call('verify')
    journal = host.root / '.deploy-state/ark-outbound/release-current.json'
    assert json.loads(journal.read_text())['status'] != 'completed'


def test_new_schema_is_required_at_activation_even_with_pending_migration(host):
    host.call('prepare', allow_pending=True)
    assert 'linked_sync_id' not in host.commands[-1][-1]
    host.call('freeze', allow_pending=True)
    host.call('activate', allow_pending=True)
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
        release.invoke(Path('.'), 'activate', {})
