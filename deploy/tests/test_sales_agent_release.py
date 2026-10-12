"""Sales preparation does not start consumers or accept untrusted artifacts."""
import base64
import hashlib
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sales_agent_release as release
import sales_agent_remote as remote


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
