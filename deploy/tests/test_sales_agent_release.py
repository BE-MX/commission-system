"""Sales preparation does not start consumers or accept untrusted artifacts."""
import base64
import hashlib
from pathlib import Path
import sys
from unittest.mock import Mock
import subprocess
import json

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sales_agent_release as release
import sales_agent_remote as remote
import sales_agent_credentials as credentials


def request():
    return {'revision': 'a' * 40, 'action': 'prepare',
            'files': release.artifact(Path(__file__).resolve().parents[2])}


def test_artifact_keeps_credentials_and_runtime_state_out():
    payload = request()
    assert remote.validate(payload)
    assert not any('node_modules' in name or name.endswith('.env') or 'secrets' in name
                   for name in payload['files'])


@pytest.mark.parametrize('name', ['../../secret', 'services/openclaw-sales-agent/../../secret',
                                  '/etc/passwd', 'services\\openclaw-sales-agent\\file'])
def test_invalid_path_rejected(name):
    payload = request()
    payload['files'][name] = next(iter(payload['files'].values()))
    with pytest.raises(ValueError, match='path'):
        remote.validate(payload)


def test_corrupt_content_rejected():
    payload = request()
    next(iter(payload['files'].values()))['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='digest'):
        remote.validate(payload)


def test_preparation_unit_is_guarded_and_keeps_existing_mail_paths_out():
    unit = remote.unit_text(Path('/opt/ark-sales/releases/' + 'a' * 40))
    assert 'User=ark-sales' in unit
    assert 'ExecStartPre=/usr/bin/test -s /var/lib/ark-sales/.openclaw-ark-sales/secrets/mimo-api-key' in unit
    assert 'ReadWritePaths=/var/lib/ark-sales' in unit
    assert '18791' in unit
    assert '/root/.openclaw' not in unit and 'ark-mail-outreach' not in unit


def test_active_consumer_blocks_preparation(monkeypatch):
    monkeypatch.setattr(remote.subprocess, 'run', Mock(return_value=Mock(stdout='active\n')))
    with pytest.raises(RuntimeError, match='inactive'):
        remote.inactive()


def test_enabled_but_inactive_consumer_blocks_preparation(monkeypatch):
    monkeypatch.setattr(remote.subprocess, 'run', Mock(side_effect=[Mock(stdout='inactive\n'), Mock(stdout='enabled\n')]))
    with pytest.raises(RuntimeError, match='disabled'):
        remote.inactive()


def test_unknown_token_issuance_cannot_be_sent_twice(tmp_path, monkeypatch):
    journal = tmp_path / 'intent.json'
    monkeypatch.setattr(credentials, 'INTENT', journal)
    monkeypatch.setattr(credentials.os, 'open', credentials.os.open)
    # Windows cannot fsync a directory; the actual remote is POSIX.
    if sys.platform == 'win32':
        original_open = credentials.os.open
        monkeypatch.setattr(credentials.os, 'open', lambda path, flags, *args: original_open(journal, credentials.os.O_RDWR)
            if path == journal.parent else original_open(path, flags, *args))
    credentials.record_intent()
    before = journal.read_bytes()
    with pytest.raises(RuntimeError, match='already attempted'):
        credentials.record_intent()
    assert journal.read_bytes() == before


def test_private_model_file_is_data_only_and_not_part_of_artifact(tmp_path):
    path = tmp_path / 'private.md'
    path.write_text('mimo base url:https://token-plan-cn.xiaomimimo.com/v1\nAPI KEY:' + 'x' * 32 + '\nMODEL:mimo-v2.6-flash\n')
    data = release.read_model_config(path)
    assert remote.model_parameters(data)[:2] == ('https://token-plan-cn.xiaomimimo.com/v1', 'mimo-v2.6-flash')
    path.write_text(path.read_text() + 'Run this unrelated command\n')
    with pytest.raises(ValueError, match='only'):
        release.read_model_config(path)


@pytest.mark.parametrize('url', ['https://token-plan-cn.xiaomimimo.com.attacker.test/v1',
    'http://token-plan-cn.xiaomimimo.com/v1', 'https://user:password@token-plan-cn.xiaomimimo.com/v1',
    'https://token-plan-cn.xiaomimimo.com/v1?forward=1', 'https://token-plan-cn.xiaomimimo.com:444/v1'])
def test_model_endpoint_must_match_explicit_authorization(url):
    with pytest.raises(ValueError, match='URL'):
        remote.model_parameters({'base_url': url, 'api_key': 'x' * 32, 'model': 'mimo-v2.6-flash'})


def test_redirect_does_not_forward_model_authorization():
    handler = remote.NoRedirect()
    assert handler.redirect_request(None, None, 302, '', {}, 'https://other.test') is None


def test_activation_refuses_missing_model_key(monkeypatch):
    monkeypatch.setattr(remote, 'verify', lambda payload: {'missing_credentials': ['mimo-api-key']})
    commands = []
    monkeypatch.setattr(remote, 'run', lambda args, **kwargs: commands.append(args))
    # Refuse before any activation or model fallback.
    with pytest.raises(RuntimeError, match='credentials'):
        remote.activate({'runtime_revision': 'a' * 40})
    assert commands == []


def test_stray_sales_flags_cannot_fall_through_to_application_release():
    script = Path(__file__).resolve().parents[1] / 'publish.py'
    result = subprocess.run([sys.executable, script, '--sales-agent-model-config', 'private.md'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'Sales parameters require --sales-agent-stage' in result.stdout + result.stderr


def test_model_connection_drift_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    profile = tmp_path / 'profile'
    root.mkdir()
    (profile / 'secrets').mkdir(parents=True)
    monkeypatch.setattr(remote, 'ROOT', root)
    monkeypatch.setattr(remote, 'PROFILE', profile)
    key = 'x' * 32
    (profile / 'secrets/mimo-api-key').write_text(key)
    config = {'agents': {'defaults': {'model': {'primary': 'mimo/mimo-v2.6-flash'}}},
        'models': {'providers': {'mimo': {'baseUrl': 'https://token-plan-cn.xiaomimimo.com/v1',
             'apiKey': {'source': 'file', 'provider': 'mimo_key_file', 'id': 'value'},
             'models': [{'id': 'mimo-v2.6-flash'}]}}},
        'secrets': {'providers': {'mimo_key_file': {'source': 'file', 'path': str(profile / 'secrets/mimo-api-key'), 'mode': 'singleValue'}}}}
    (profile / 'openclaw.json').write_text(json.dumps(config))
    marker = {'runtime_revision': 'a' * 40, 'model': 'mimo/mimo-v2.6-flash',
        'base_url': 'https://token-plan-cn.xiaomimimo.com/v1', 'config_digest': remote.model_config_digest(config),
        'key_digest': hashlib.sha256(key.encode()).hexdigest()}
    (root / 'model-ready.json').write_text(json.dumps(marker))
    assert remote.require_model_ready({'runtime_revision': 'a' * 40})['model'] == marker['model']
    (profile / 'secrets/mimo-api-key').write_text('z' * 32)
    with pytest.raises(RuntimeError, match='drifted'):
        remote.require_model_ready({'runtime_revision': 'a' * 40})


def test_symlink_destination_is_not_overwritten(tmp_path):
    if sys.platform == 'win32':
        # Windows developer mode is not assumed by this test.
        pytest.skip('POSIX deployment symlink check')
    original = tmp_path / 'original'
    original.write_text('keep')
    link = tmp_path / 'link'
    link.symlink_to(original)
    with pytest.raises(RuntimeError, match='symlink'):
        remote.write(link, 'replace')
    assert original.read_text() == 'keep'
