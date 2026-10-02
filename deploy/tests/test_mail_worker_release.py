"""Mail deployment tests use temporary files and mocked services; never production."""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mail_worker_remote as remote
import mail_worker_release as release
import mail_worker_config as config


def request():
    return {'action': 'prepare', 'revision': 'a' * 40, 'release_id': 'test-release',
            'files': release.artifact(Path(__file__).resolve().parents[2])}


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / 'runtime'
    root.mkdir()
    state = tmp_path / 'state'
    state.mkdir()
    monkeypatch.setattr(remote, 'ROOT', root)
    monkeypatch.setattr(remote, 'STATE', state)
    monkeypatch.setattr(remote, 'write', lambda path, value, mode=0o600: path.write_text(json.dumps(value) if not isinstance(value, str) else value))
    monkeypatch.setattr(remote, 'prepared', lambda payload: (root, {}))
    monkeypatch.setattr(remote.time, 'sleep', lambda delay: None)
    status = {'LoadState': 'loaded', 'ActiveState': 'active', 'MainPID': '10', 'UnitFileState': 'enabled'}
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if args[:2] == ['systemctl', 'stop']:
            status.update(ActiveState='inactive', MainPID='0')
        if args[:2] == ['systemctl', 'start']:
            status.update(ActiveState='active', MainPID='10')
        return ''
    monkeypatch.setattr(remote, 'run', run)
    monkeypatch.setattr(remote, 'state', lambda: dict(status))
    return root, state, status, commands


def test_artifact_is_narrow_and_hash_checked():
    payload = request()
    assert set(remote.validate(payload)) == remote.NAMES
    payload['files']['../../secret'] = payload['files']['mail-worker.mjs']
    with pytest.raises(ValueError, match='paths'):
        remote.validate(payload)


def test_tampered_artifact_and_revision_rejected():
    payload = request()
    payload['files']['mail-worker.mjs']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='digest'):
        remote.validate(payload)
    payload = request()
    payload['revision'] = '../wrong'
    with pytest.raises(ValueError, match='revision'):
        remote.validate(payload)


def test_freeze_preserves_baseline_across_retries(host):
    root, state, status, commands = host
    payload = request()
    remote.freeze(payload)
    assert remote.read(state / 'freeze.json')['release_id'] == payload['release_id']
    remote.freeze(payload)
    record = remote.read(root / 'release-current.json')
    assert record['was_active'] is True and record['was_enabled'] is True
    payload['release_id'] = 'different-release'
    with pytest.raises(RuntimeError, match='Unfinished'):
        remote.freeze(payload)


def test_pending_receipt_blocks_release_without_erasing_evidence(host):
    root, state, status, commands = host
    (state / 'pending.json').write_text('{"id":7,"result":{"outcome":"accepted"}}')
    with pytest.raises(RuntimeError, match='cannot be reconciled'):
        remote.freeze(request())
    assert remote.read(state / 'pending.json')['result']['outcome'] == 'accepted'
    assert status['MainPID'] == '0'
    assert remote.read(root / 'release-current.json')['status'] == 'freezing'


def test_pending_receipt_flush_restart_is_frozen(host, monkeypatch):
    root, state, status, commands = host
    (state / 'pending.json').write_text('{"id":7}')
    original_run = remote.run
    def run(args, **kwargs):
        result = original_run(args, **kwargs)
        if args[:2] == ['systemctl', 'start']:
            assert (state / 'freeze.json').exists()
            (state / 'pending.json').write_text('null')
        return result
    monkeypatch.setattr(remote, 'run', run)
    remote.freeze(request())
    assert status['MainPID'] == '0'
    assert remote.read(root / 'release-current.json')['status'] == 'frozen'


def test_environment_patch_preserves_unrelated_secrets_and_existing_hashes():
    old_hash, new_hash = 'a' * 64, 'b' * 64
    original = ('OTHER_SECRET=do-not-print\r\n# retained\r\nMAIL_OUTREACH_SEND_ENABLED=true\r\n'
                + 'MAIL_OUTREACH_WORKER_TOKENS_JSON=\'{"existing":"' + old_hash + '"}\'\r\n').encode()
    updated = remote.update_environment(original, new_hash)
    assert b'OTHER_SECRET=do-not-print\r\n# retained\r\n' in updated
    assert b'MAIL_OUTREACH_SEND_ENABLED=false\r\n' in updated
    assert remote.worker_hashes(updated) == {'existing': old_hash, 'ark-mail-beijing': new_hash}
    assert updated == remote.update_environment(updated, new_hash)


def test_duplicate_or_invalid_config_is_not_overwritten():
    with pytest.raises(RuntimeError, match='Duplicate'):
        remote.update_environment(b'MAIL_OUTREACH_SEND_ENABLED=true\nMAIL_OUTREACH_SEND_ENABLED=false', 'a' * 64)
    with pytest.raises(RuntimeError, match='Unrecognized'):
        remote.worker_hashes(b'MAIL_OUTREACH_WORKER_TOKENS_JSON={"bad":"plaintext"}')


def test_unit_waits_for_drain_and_preserves_private_oauth_state():
    unit = remote.unit_text(Path('/opt/ark-mail-outreach/releases/' + 'a' * 40), Path('/opt/runtime/bin/node'), 'a' * 40)
    assert 'KillMode=mixed' in unit and 'TimeoutStopSec=180' in unit
    assert 'flock --no-fork --nonblock' in unit
    assert 'ReadWritePaths=/var/lib/ark-mail-outreach' in unit
    assert 'User=ark-mail' in unit and 'ProtectHome=true' in unit


def test_result_receipt_must_match_revision(monkeypatch):
    result = Mock(returncode=0, stdout=json.dumps({'status': 'prepare', 'revision': 'b' * 40}), stderr='')
    monkeypatch.setattr(release, 'remote_python', Mock(return_value=result))
    with pytest.raises(RuntimeError, match='receipt'):
        release.prepare(Path(__file__).resolve().parents[2], 'a' * 40, 'release')


def test_modified_office_backup_is_rejected_before_remote_mutation(tmp_path, monkeypatch):
    root = tmp_path / 'live'
    directory = root / '.deploy_state/credentials/mail-worker'
    directory.mkdir(parents=True)
    (root / 'backend').mkdir()
    original = b'EXISTING=original\n'
    (root / 'backend/.env').write_bytes(original)
    plan = {'revision': 'a' * 40, 'attempt': 'b' * 32, 'token': 'x' * 48,
            'office_original_sha': config.env_hash(original), 'status': 'prepared'}
    (directory / 'configure-current.json').write_text(json.dumps(plan))
    (directory / ('office-before-' + 'b' * 32 + '.env')).write_bytes(b'EXISTING=tampered\n')
    monkeypatch.setattr(config, 'secure_directory', lambda path: None)
    remote_call = Mock()
    monkeypatch.setattr(config, 'invoke', remote_call)
    with pytest.raises(RuntimeError, match='backup identity'):
        config.configure(tmp_path / 'candidate', root, 'a' * 40)
    remote_call.assert_not_called()
    assert (root / 'backend/.env').read_bytes() == original


def test_office_temp_is_empty_until_acl_and_cas_prevents_lost_update(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    original = b'SECRET=old'
    env.write_bytes(original)
    def set_acl(*args, **kwargs):
        temporary = next(tmp_path.glob('.env.mail-*'))
        assert temporary.read_bytes() == b''
        env.write_bytes(b'SECRET=concurrent')
    monkeypatch.setattr(config.subprocess, 'run', set_acl)
    with pytest.raises(RuntimeError, match='drift'):
        config.atomic_local(env, b'SECRET=new', config.env_hash(original))
    assert env.read_bytes() == b'SECRET=concurrent'


def test_failed_readiness_refreezes_and_stops_sender(host, monkeypatch):
    root, state, status, commands = host
    payload = request()
    (root / 'release-current.json').write_text(json.dumps({'revision': payload['revision'],
        'release_id': payload['release_id'], 'status': 'activated', 'was_active': True, 'first_install': False}))
    monkeypatch.setattr(remote, 'verify_ready', Mock(side_effect=RuntimeError('readiness failed')))
    with pytest.raises(RuntimeError, match='readiness failed'):
        remote.verify(payload)
    assert status['MainPID'] == '0'
    assert (state / 'freeze.json').exists()
    assert remote.read(root / 'release-current.json')['status'] == 'activation-failed'


def test_start_timeout_after_process_started_also_stops_sender(host, monkeypatch):
    root, state, status, commands = host
    payload = request()
    (root / 'release-current.json').write_text(json.dumps({'revision': payload['revision'],
        'release_id': payload['release_id'], 'status': 'frozen', 'was_active': True, 'first_install': False}))
    def activation(_):
        status.update(ActiveState='active', MainPID='45')
        raise TimeoutError('start response lost')
    monkeypatch.setattr(remote, 'activate_inner', activation)
    with pytest.raises(TimeoutError):
        remote.activate(payload)
    assert status['MainPID'] == '0'
    assert (state / 'freeze.json').exists()


def test_enable_sending_reuses_plan_token_and_changes_only_false_flag(tmp_path, monkeypatch):
    root, source = tmp_path / 'live', tmp_path / 'candidate'
    directory = root / '.deploy_state/credentials/mail-worker'
    directory.mkdir(parents=True)
    (root / 'backend').mkdir()
    (source / 'backend').mkdir(parents=True)
    original, token = b'UNRELATED=retained\n', 'x' * 48
    digest = hashlib.sha256(token.encode()).hexdigest()
    configured = remote.update_environment(original, digest)
    (root / 'backend/.env').write_bytes(configured)
    (source / 'backend/.env').write_bytes(configured)
    plan = {'revision': 'a' * 40, 'attempt': 'b' * 32, 'token': token,
            'office_original_sha': config.env_hash(original), 'beijing_original_sha': 'c' * 64,
            'beijing_config_sha': None, 'beijing_token_sha': None, 'status': 'configured'}
    (directory / 'configure-current.json').write_text(json.dumps(plan))
    (directory / ('office-before-' + 'b' * 32 + '.env')).write_bytes(original)
    monkeypatch.setattr(config, 'secure_directory', lambda path: None)
    def replace(path, body, expected):
        assert config.env_hash(path.read_bytes()) == expected
        path.write_bytes(body)
    monkeypatch.setattr(config, 'atomic_local', replace)
    remote_call = Mock(return_value={})
    monkeypatch.setattr(config, 'invoke', remote_call)
    result = config.configure(source, root, 'a' * 40, enable_sending=True)
    assert result['status'] == 'sending-enabled' and result['services_restarted'] is False
    assert remote_call.call_args.args[3]['send_enabled'] is True
    assert remote_call.call_args.args[3]['token'] == token
    enabled = (root / 'backend/.env').read_bytes()
    assert enabled == configured.replace(b'MAIL_OUTREACH_SEND_ENABLED=false', b'MAIL_OUTREACH_SEND_ENABLED=true')
    assert (source / 'backend/.env').read_bytes() == enabled
    # Exact replay is idempotent; credentials never rotate.
    config.configure(source, root, 'a' * 40, enable_sending=True)
    assert json.loads((directory / 'configure-current.json').read_text())['token'] == token


def test_enable_without_configure_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'secure_directory', lambda path: path.mkdir(parents=True))
    with pytest.raises(RuntimeError, match='Configure credentials'):
        config.configure(tmp_path / 'candidate', tmp_path / 'live', 'a' * 40, enable_sending=True)


def test_cli_install_uses_distinct_empty_npm_configs_and_tls(host, monkeypatch):
    root, _, _, _ = host
    payload = request()
    payload['release_id'] = 'setup'
    monkeypatch.setattr(remote, 'ensure_node', lambda: root / 'runtime/bin/node')
    installs = []
    def run(args, **kwargs):
        if len(args) > 2 and args[2] == 'ci':
            env = kwargs['env']
            assert env['NPM_CONFIG_USERCONFIG'] != env['NPM_CONFIG_GLOBALCONFIG']
            assert Path(env['NPM_CONFIG_USERCONFIG']).read_bytes() == b''
            assert Path(env['NPM_CONFIG_GLOBALCONFIG']).read_bytes() == b''
            assert env['npm_config_strict_ssl'] == 'true'
            installs.append(args)
        return 'agently-cli 1.0.18' if args[-1] == '--version' else ''
    monkeypatch.setattr(remote, 'run', run)
    remote.prepare(payload, remote.validate(payload))
    assert len(installs) == 1
