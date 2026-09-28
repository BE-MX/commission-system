import base64
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import colorwork_backup_policy as policy


@pytest.fixture
def install_env(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    units = tmp_path / 'units'
    units.mkdir()
    machine = tmp_path / 'machine-id'
    machine.write_text(policy.MACHINE)
    script = tmp_path / 'installed.py'
    for key, val in [('STATE', state), ('UNITS', units), ('SCRIPT', script), ('MACHINE_FILE', machine)]:
        monkeypatch.setattr(policy, key, val)
    monkeypatch.setattr(policy, 'installation_lock', nullcontext)
    monkeypatch.setattr(policy.uuid, 'uuid4', lambda: type('Installation', (), {'hex': 'new-install'})())
    source = b'"""Retain two recent Colorwork backups fixture."""\ndef run_cleanup(apply):\n return {"status":"planned","keep":["a","b"],"delete":[]}\n'
    request = {'action': 'install', 'source_b64': base64.b64encode(source).decode(), 'sha256': policy.digest(source)}
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        if args[:2] == ['systemctl', 'start'] and args[-1].endswith('.service'):
            (state / 'maintenance/retention-outcome.json').write_text(json.dumps({'status': 'completed', 'keep': ['a', 'b'], 'deleted': [], 'invocation_id': 'this-run', 'installation_id': 'new-install', 'script_sha256': request['sha256']}))
        if 'InvocationID' in args:
            return subprocess.CompletedProcess(args, 0, stdout='\n')  # completed unit was garbage-collected
        # Initial units are absent; post-install timer checks succeed.
        code = 1 if args[:2] in [['systemctl', 'is-enabled'], ['systemctl', 'is-active']] and not script.exists() else 0
        return subprocess.CompletedProcess(args, code, stdout='ActiveState=inactive\nMainPID=0\n')

    monkeypatch.setattr(policy.subprocess, 'run', run)
    return state, script, units, request, commands


def test_prepare_does_not_install_or_call_systemctl(install_env):
    state, script, units, request, commands = install_env
    request['action'] = 'prepare'
    assert policy.install(request)['status'] == 'prepared'
    assert not script.exists() and not list(units.iterdir()) and not commands


def test_first_install_after_unit_gc_enables_policy_without_application_restart(install_env):
    state, script, units, request, commands = install_env
    result = policy.install(request)
    assert result['status'] == 'installed'
    assert script.exists()
    assert 'OnCalendar=hourly' in (units / (policy.UNIT + '.timer')).read_text()
    assert 'ProtectSystem=strict' in (units / (policy.UNIT + '.service')).read_text()
    assert not any('ark-colorwork' in command[2:] or 'ark-backend' in command[2:] for command in commands)
    assert not (state / 'maintenance/unit-validation').exists()


def test_start_failure_rolls_back_only_policy_files(install_env, monkeypatch):
    state, script, units, request, commands = install_env
    real = policy.subprocess.run

    def fail_start(args, **kwargs):
        if args == ['systemctl', 'start', policy.UNIT + '.service']:
            raise subprocess.CalledProcessError(1, args)
        return real(args, **kwargs)

    monkeypatch.setattr(policy.subprocess, 'run', fail_start)
    with pytest.raises(subprocess.CalledProcessError):
        policy.install(request)
    assert not script.exists() and not list(units.iterdir())
    assert ['systemctl', 'disable', '--now', policy.UNIT + '.timer'] in commands


def test_unknown_existing_unit_is_preserved(install_env):
    _, script, units, request, commands = install_env
    path = units / (policy.UNIT + '.service')
    path.write_text('Unmanaged unit')
    with pytest.raises(RuntimeError, match='unmanaged'):
        policy.install(request)
    assert path.read_text() == 'Unmanaged unit' and not script.exists()


def test_artifact_digest_mismatch_is_rejected(install_env):
    _, _, _, request, commands = install_env
    request['sha256'] = 'invalid'
    with pytest.raises(ValueError, match='digest'):
        policy.install(request)
    assert not commands


def test_activating_oneshot_blocks_script_replacement(install_env, monkeypatch):
    _, script, units, request, commands = install_env
    real = policy.subprocess.run

    def running(args, **kwargs):
        if args[:2] == ['systemctl', 'show']:
            return subprocess.CompletedProcess(args, 0, stdout='ActiveState=activating\nMainPID=123\n')
        return real(args, **kwargs)

    monkeypatch.setattr(policy.subprocess, 'run', running)
    with pytest.raises(RuntimeError, match='running'):
        policy.install(request)
    assert not script.exists() and not list(units.iterdir())


@pytest.mark.parametrize('outcome, accepted', [
    ({'status': 'completed', 'invocation_id': 'old-run', 'installation_id': 'old-install'}, False),
    ({'status': 'completed', 'invocation_id': 'this-run', 'script_sha256': 'wrong-artifact'}, False),
    ({'status': 'skipped', 'reason': 'deployment-in-progress', 'invocation_id': 'this-run'}, True),
])
def test_install_does_not_report_stale_cleanup(install_env, monkeypatch, outcome, accepted):
    state, script, units, request, _ = install_env
    real = policy.subprocess.run

    def outcome_run(args, **kwargs):
        result = real(args, **kwargs)
        if args == ['systemctl', 'start', policy.UNIT + '.service']:
            (state / 'maintenance/retention-outcome.json').write_text(json.dumps({'installation_id': 'new-install', 'script_sha256': request['sha256'], **outcome}))
        return result

    monkeypatch.setattr(policy.subprocess, 'run', outcome_run)
    if accepted:
        result = policy.install(request)
        assert result['last_run'] == 'skipped' and result['deleted'] == []
    else:
        with pytest.raises(RuntimeError, match='outcome'):
            policy.install(request)
        assert not script.exists() and not list(units.iterdir())
