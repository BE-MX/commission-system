from types import SimpleNamespace
from pathlib import Path
import sys
from contextlib import nullcontext
from unittest.mock import Mock
import json

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from whatsapp_connector_release import validate_args, validate_changes


def args(**values):
    return SimpleNamespace(whatsapp_connector_only='a' * 40, revision='b' * 40,
                           live_root='D:/commission-system', no_pull=True, prepare_only=True, **values)


@pytest.mark.parametrize('other', ['cloud_only', 'office_beijing_ingress', 'migration_credentials', 'inline_maintenance'])
def test_reject_mixed_scope(other):
    with pytest.raises(RuntimeError, match='no mixed actions'):
        validate_args(args(**{other: True}))


@pytest.mark.parametrize('field,value', [('revision', 'short'), ('whatsapp_connector_only', ''), ('no_pull', False), ('live_root', None)])
def test_require_pinned_controller(field, value):
    request = args()
    setattr(request, field, value)
    with pytest.raises(RuntimeError):
        validate_args(request)


@pytest.mark.parametrize('path', ['backend/app/core/config.py', 'backend/alembic/versions/263_other.py',
                                 'frontend/package.json', 'services/whatsapp-connector/package-lock.json',
                                 'deploy/remote_backend.py'])
def test_reject_unrelated_runtime_or_dependency_changes(path):
    with pytest.raises(RuntimeError, match='outside'):
        validate_changes(['services/whatsapp-connector/src/projection.js', path])


def test_only_reviewed_connector_and_release_support_are_allowed():
    validate_args(args())
    validate_changes(['services/whatsapp-connector/src/projection.js', 'deploy/whatsapp_connector_release.py',
                      'docs/reports/2026-11-14-whatsapp-contact-metadata.md'])
    with pytest.raises(RuntimeError, match='no connector'):
        validate_changes(['docs/handoff.md'])


@pytest.mark.parametrize('broken', [False, 'health', 'backup'])
def test_activation_and_rollback_touch_only_connector(tmp_path, monkeypatch, broken):
    import office_release as office
    import whatsapp_connector_release as release
    live, candidate, state = (tmp_path / name for name in ['live', 'candidate', 'state'])
    for root in (live, candidate):
        (root / 'services/whatsapp-connector/node_modules').mkdir(parents=True)
    state.mkdir()
    calls, verified = [], []
    running = {'WhatsAppConnector': True}
    guard = Mock()
    def run(command, cwd=None, **kwargs):
        calls.append(command)
        if command[:3] == ['git', 'rev-parse', 'HEAD']:
            return 'new' if cwd == candidate else 'old'
        if command[:2] == ['git', 'status']: return ''
        if command[1:2] == ['status']:
            return 'SERVICE_RUNNING' if running[command[2]] else 'SERVICE_STOPPED'
        if command[1:2] == ['stop']: running[command[2]] = False
        if command[1:2] == ['start']: running[command[2]] = True
        return ''
    def backup(prepared):
        assert running['WhatsAppConnector'] is False
        if broken == 'backup': raise RuntimeError('state backup failed')
    def verify(prepared):
        verified.append(True)
        if broken == 'health' and len(verified) == 1: raise RuntimeError('unhealthy connector')
    monkeypatch.setattr(office, 'ROOT', candidate)
    monkeypatch.setattr(office, 'STATE', state)
    monkeypatch.setattr(office, 'run', run)
    monkeypatch.setattr(office, 'wait_ready', lambda port, nssm, services: services == ['WhatsAppConnector'])
    monkeypatch.setattr(office, 'protocol_observation', lambda *a: {'mode': 'legacy'})
    monkeypatch.setattr(office, 'rollback_guard', lambda *a: nullcontext(guard))
    monkeypatch.setattr(release, 'backup_store', backup)
    monkeypatch.setattr(release, 'verify_connector', verify)
    prepared = dict(nssm='nssm', live=live, revision='new', previous='old', python='python',
                    backend_changed=False, connector_changed=True, static=[], port=8001, schema='262',
                    connector_only_backup=state / 'backup')
    if broken:
        with pytest.raises(RuntimeError, match='unhealthy connector|state backup failed'): office.activate_locked(prepared)
        assert len(verified) == (2 if broken == 'health' else 1)
        guard.check.assert_called_once()
    else:
        assert office.activate_locked(prepared)['status'] == 'updated'
        assert len(verified) == 1
    assert not any('CommissionSystem' in command for command in calls)
    assert running['WhatsAppConnector'] is True
    assert not (state / 'office-success.json').exists()


def test_unfinished_connector_journal_blocks_normal_office_prepare(tmp_path, monkeypatch):
    import office_release as office
    monkeypatch.setattr(office, 'STATE', tmp_path)
    (tmp_path / 'whatsapp-connector-release.json').write_text(json.dumps({'status': 'activating'}))
    with pytest.raises(RuntimeError, match='Interrupted connector'):
        office.prepare(tmp_path, 'old', 'new')
