"""Protected overlay and exact migration gate; no remote processes or database."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from customer_portal_backup import BASE, TARGET, option, validate_proof
from customer_portal_config_remote import merge_text, portal_values, service_environment, apply_failure


def test_overlay_retains_other_settings_and_secret_without_duplicate_key():
    before = '# original\nJWT_SECRET="kept exactly"\nPORTAL_ENABLED=false\nOTHER=x\n'
    result = merge_text(before, {'PORTAL_ENABLED':'true', 'PORTAL_AUTH_SECRET':'generated-server-side'})
    assert '# original\nJWT_SECRET="kept exactly"\n' in result and 'OTHER=x\n' in result
    assert result.count('PORTAL_ENABLED=') == 1 and 'PORTAL_ENABLED=true\n' in result
    assert merge_text(result, {'PORTAL_ENABLED':'true', 'PORTAL_AUTH_SECRET':'generated-server-side'}) == result


def test_backup_option_file_escapes_quote_slash_and_newline():
    assert option('a"b\\c\nd') == '"a\\"b\\\\c\\nd"'


class Result:
    def __init__(self, value): self.value = value
    def scalars(self): return self
    def all(self): return self.value


class Connection:
    def execute(self, query): return Result([BASE])
    def scalar(self, query): return 'owned-uuid'


def proof_file(path, **changes):
    migration = Path(__file__).resolve().parents[2] / 'backend/alembic/versions/181_portal_password_login.py'
    proof = {'database_uuid':'owned-uuid','base':BASE,'target':TARGET,
        'business_rows_and_constraints_unchanged':True,'restore_after_ddl_verified':True,
        'migration_sha256':hashlib.sha256(migration.read_bytes().replace(b'\r\n', b'\n')).hexdigest()}
    proof.update(changes)
    (path / 'customer-portal-upgrade-proof.json').write_text(json.dumps(proof))


def test_exact_actual_upgrade_proof_passes(tmp_path):
    proof_file(tmp_path)
    validate_proof(tmp_path, Connection(), [TARGET], TARGET)


@pytest.mark.parametrize('pending', [[BASE,TARGET], [TARGET,'182_new'], ['unknown',TARGET]])
def test_longer_chain_cannot_bypass_portal_gate(tmp_path, pending):
    proof_file(tmp_path)
    with pytest.raises(RuntimeError, match='unique'):
        validate_proof(tmp_path, Connection(), pending, TARGET)


@pytest.mark.parametrize('changes', [{'database_uuid':'other'}, {'restore_after_ddl_verified':'false'},
    {'migration_sha256':'0'*64}, {'business_rows_and_constraints_unchanged':False}])
def test_unmatched_or_unverified_recovery_proof_rejects(tmp_path, changes):
    proof_file(tmp_path, **changes)
    with pytest.raises(RuntimeError, match='does not match'):
        validate_proof(tmp_path, Connection(), [TARGET], TARGET)


@pytest.mark.parametrize('content', ['export PORTAL_AUTH_SECRET=retained', 'export\tPORTAL_AUTH_SECRET=retained', 'portal_auth_secret=retained',
    'PORTAL_AUTH_SECRET=one\nportal_auth_secret=two', 'PORTAL_AUTH_SECRET=one\nPORTAL_AUTH_SECRET=two'])
def test_noncanonical_durable_key_rejected_before_generation(content):
    with pytest.raises(RuntimeError, match='Noncanonical'):
        portal_values(content)


def test_quoted_canonical_durable_key_is_retained():
    assert portal_values('PORTAL_AUTH_SECRET="kept"\nPORTAL_CSRF_KEYS=\'{"v1":"kept"}\'')['PORTAL_AUTH_SECRET'] == 'kept'


@pytest.mark.parametrize('phase', ['stop-orders', 'close'])
def test_stop_failure_keeps_closed_configuration_and_pauses_service(phase):
    called = []
    assert apply_failure(phase, lambda: called.append('reopen'), lambda: called.append('stop')) == 'failed_paused'
    assert called == ['stop']


@pytest.mark.parametrize('key', [b'portal_writes_enabled', b'PoRtAl_EnAbLeD'])
def test_case_insensitive_service_override_rejected(monkeypatch, key):
    import customer_portal_config_remote as remote
    monkeypatch.setattr(remote.subprocess, 'check_output', lambda *a, **k: '42')
    monkeypatch.setattr(Path, 'read_bytes', lambda self: key + b'=true\0')
    with pytest.raises(RuntimeError, match='overrides'):
        service_environment()


def test_closing_already_paused_backend_does_not_require_or_start_process(monkeypatch):
    import customer_portal_config_remote as remote
    monkeypatch.setattr(remote.subprocess, 'check_output', lambda *a, **k: '0')
    assert service_environment(allow_stopped=True) is None


def test_configuration_probe_uses_the_service_identity(monkeypatch):
    import customer_portal_config_remote as remote
    from types import SimpleNamespace
    captured = []
    monkeypatch.setattr(remote.subprocess, 'run', lambda *a, **kw: captured.append(kw) or SimpleNamespace(returncode=0, stdout='{}'))
    remote.runtime_probe({'SAFE_TEST':'value'}, (1000,1000))
    assert captured[0]['user'] == 1000 and captured[0]['group'] == 1000 and captured[0]['extra_groups'] == []


def test_private_temporary_is_unique_and_never_overwrites_existing_file(tmp_path, monkeypatch):
    import customer_portal_config_remote as remote
    monkeypatch.setattr(remote, 'ENV', tmp_path / '.env')
    monkeypatch.setattr(remote.os, 'chown', lambda *args: None, raising=False)
    existing = tmp_path / '.env.portal-next'; existing.write_text('unrelated')
    first = remote.private_next(b'isolated-test-content', (1,1))
    second = remote.private_next(b'other', (1,1))
    assert first != second and first.name.startswith('.env.portal-')
    assert first.read_bytes() == b'isolated-test-content' and existing.read_text() == 'unrelated'
