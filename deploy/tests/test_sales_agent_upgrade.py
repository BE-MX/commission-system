"""Old runtime pause and cloud-only model continuity, with synthetic secrets."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sales_agent_release as release
import sales_agent_remote as remote


@pytest.fixture
def bound(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    profile = tmp_path / 'profile'
    root.mkdir()
    (profile / 'secrets').mkdir(parents=True)
    monkeypatch.setattr(remote, 'ROOT', root)
    monkeypatch.setattr(remote, 'PROFILE', profile)
    key = 'synthetic-protected-mimo-key'
    (profile / 'secrets/mimo-api-key').write_text(key)
    (profile / 'secrets/mimo-api-key').chmod(0o600)
    config = {'agents': {'defaults': {'model': {'primary': 'mimo/mimo-v2.6-flash'}},
              'entries': {'main': {'heartbeat': {'every': '0m'}}}},
        'models': {'providers': {'mimo': {'baseUrl': 'https://token-plan-cn.xiaomimimo.com/v1',
            'apiKey': {'source': 'file', 'provider': 'mimo_key_file', 'id': 'value'},
            'models': [{'id': 'mimo-v2.6-flash'}]}}},
        'secrets': {'providers': {'mimo_key_file': {'source': 'file', 'path': str(profile / 'secrets/mimo-api-key'), 'mode': 'singleValue'}}}}
    (profile / 'openclaw.json').write_text(json.dumps(config))
    ready = {'runtime_revision': 'a' * 40, 'probe': 'passed', 'model': 'mimo/mimo-v2.6-flash',
        'base_url': 'https://token-plan-cn.xiaomimimo.com/v1', 'config_digest': remote.model_config_digest(config),
        'key_digest': hashlib.sha256(key.encode()).hexdigest()}
    (root / 'model-ready.json').write_text(json.dumps(ready))
    unit = tmp_path / 'units'
    unit.mkdir()
    (unit / 'ark-sales-agent.service').write_text(remote.unit_text(root / 'releases' / ('a' * 40)))
    original = remote.Path
    monkeypatch.setattr(remote, 'Path', lambda value: unit if value == '/etc/systemd/system' else original(value))
    commands = []
    monkeypatch.setattr(remote, 'run', lambda args, **kwargs: commands.append(args))
    monkeypatch.setattr(remote, 'inactive', lambda: None)
    return root, profile, ready, commands, config


def payload(action='pause'):
    return {'revision': 'b' * 40, 'runtime_revision': 'a' * 40, 'action': action,
        'files': release.artifact(Path(__file__).resolve().parents[2])}


def test_new_controller_pauses_exact_old_runtime_and_saves_verified_provider(bound):
    root, _, ready, commands, _ = bound
    result = remote.execute(payload())
    assert result['status'] == 'pause'
    assert result['runtime_revision'] == 'a' * 40
    assert commands == [['systemctl', 'disable', '--now', 'ark-sales-agent']]
    assert json.loads((root / 'model-reuse-source.json').read_text()) == ready


def test_wrong_runtime_cannot_stop_current_service(bound):
    root, _, _, commands, _ = bound
    with pytest.raises(RuntimeError, match='different service'):
        remote.execute({**payload(), 'runtime_revision': 'c' * 40})
    assert not commands and not (root / 'model-reuse-source.json').exists()


def test_configuration_drift_blocks_pause_before_state_change(bound):
    root, profile, _, commands, config = bound
    config['models']['providers']['mimo']['baseUrl'] = 'https://other.invalid'
    (profile / 'openclaw.json').write_text(json.dumps(config))
    with pytest.raises(RuntimeError, match='drifted'):
        remote.execute(payload())
    assert not commands and not (root / 'model-reuse-source.json').exists()


def test_other_actions_still_reject_new_artifacts_against_old_runtime(bound):
    with pytest.raises(RuntimeError, match='artifact drift'):
        remote.execute(payload('activate'))


def test_model_reuse_keeps_verified_provider_across_template_reset(bound):
    root, profile, _, _, config = bound
    remote.execute(payload())
    config['agents']['defaults']['model']['primary'] = 'mimo/mimo-v2.5'
    (profile / 'openclaw.json').write_text(json.dumps(config))
    value = remote.reusable_model_config()
    assert value['model'] == 'mimo-v2.6-flash'
    assert value['base_url'] == 'https://token-plan-cn.xiaomimimo.com/v1'
    assert value['api_key'] == 'synthetic-protected-mimo-key'
    (profile / 'secrets/mimo-api-key').write_text('different-protected-key')
    with pytest.raises(RuntimeError, match='key changed'):
        remote.reusable_model_config()


def test_stale_model_proof_cannot_reuse_current_key(bound):
    root, _, ready, _, _ = bound
    remote.execute(payload())
    (root / 'model-ready.json').write_text(json.dumps({**ready, 'runtime_revision': 'c' * 40}))
    with pytest.raises(RuntimeError, match='identity changed'):
        remote.reusable_model_config()


@pytest.mark.parametrize('args', [['--sales-agent-reuse-model'],
    ['--sales-agent-stage', 'model', '--sales-agent-reuse-model', '--sales-agent-model-config', 'private'],
    ['--sales-agent-stage', 'configure', '--sales-agent-reuse-model']])
def test_invalid_reuse_flags_never_fall_through_to_application_publish(args):
    script = Path(__file__).resolve().parents[1] / 'publish.py'
    result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'Sales parameters require' in result.stdout + result.stderr or 'Model stage requires' in result.stdout + result.stderr
