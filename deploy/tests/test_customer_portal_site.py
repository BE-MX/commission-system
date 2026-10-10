"""Infrastructure failure recovery uses owned paths and fake commands only."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import customer_portal_site_remote as site


@pytest.fixture
def owned(tmp_path, monkeypatch):
    config = tmp_path / 'nginx.conf'
    state = tmp_path / 'state'; state.mkdir()
    certificate = tmp_path / 'certificate'; certificate.touch()
    hook = tmp_path / 'hook'; hook.touch()
    for name, value in [('CONFIG', config), ('STATE', state), ('CERTIFICATE', certificate), ('RENEW_HOOK', hook)]:
        monkeypatch.setattr(site, name, value)
    monkeypatch.setattr(site, 'run', lambda args: '')
    return config, state


def test_interrupted_activation_recovers_exact_candidate(owned, monkeypatch):
    config, state = owned
    atomic = site.atomic_json
    def interrupted(path, record):
        if path.name == 'current.json': raise RuntimeError('interrupted')
        atomic(path, record)
    monkeypatch.setattr(site, 'atomic_json', interrupted)
    with pytest.raises(RuntimeError): site.install('candidate')
    assert config.read_text() == 'candidate' and (state / 'pending.json').exists()
    monkeypatch.setattr(site, 'atomic_json', atomic)
    site.recover_pending()
    assert json.loads((state / 'current.json').read_text())['config_digest'] == site.digest(b'candidate')
    assert not (state / 'pending.json').exists()


def test_pending_drift_never_overwrites_unknown_bytes(owned):
    config, state = owned
    config.write_text('another operator')
    site.atomic_json(state / 'pending.json', {'config_digest': site.digest(b'candidate'), 'previous_digest': None})
    with pytest.raises(RuntimeError, match='restore withheld'): site.recover_pending()
    assert config.read_text() == 'another operator'


def test_disk_restored_interruption_still_reloads_workers(owned, monkeypatch):
    config, state = owned
    site.install('before')
    previous = json.loads((state / 'current.json').read_text())
    backup = state / ('backup-' + 'a' * 32); backup.mkdir()
    (backup / 'nginx.conf').write_text('before')
    site.atomic_json(state / 'pending.json', {'config_digest': site.digest(b'candidate'),
        'previous_digest': site.digest(b'before'), 'backup': str(backup), 'previous_receipt': previous})
    commands = []
    monkeypatch.setattr(site, 'run', lambda args: commands.append(args) or '')
    site.recover_pending()
    assert commands == [['nginx', '-t'], ['systemctl', 'reload', 'nginx']]
    assert not (state / 'pending.json').exists()


def test_invalid_interrupted_candidate_uses_checked_backup(owned, monkeypatch):
    config, state = owned
    site.install('before')
    original = site.atomic_json
    def interrupted(path, value):
        if path.name == 'current.json': raise RuntimeError('lost ACK')
        original(path, value)
    monkeypatch.setattr(site, 'atomic_json', interrupted)
    with pytest.raises(RuntimeError): site.install('candidate')
    monkeypatch.setattr(site, 'atomic_json', original)
    commands = []
    def reject_once(args):
        commands.append(args)
        if len(commands) == 1: raise RuntimeError('candidate is invalid')
        return ''
    monkeypatch.setattr(site, 'run', reject_once)
    with pytest.raises(RuntimeError, match='previous ingress restored'): site.recover_pending()
    assert config.read_text() == 'before'
    assert commands[-1] == ['systemctl', 'reload', 'nginx']
    assert not (state / 'pending.json').exists()


def test_nginx_failure_restores_previous_and_reloads(owned, monkeypatch):
    config, state = owned
    site.install('before')
    commands = []
    def fail_once(args):
        commands.append(args)
        if len(commands) == 1: raise RuntimeError('syntax rejected')
        return ''
    monkeypatch.setattr(site, 'run', fail_once)
    with pytest.raises(RuntimeError, match='syntax rejected'): site.install('candidate')
    assert config.read_text() == 'before'
    assert commands[-1] == ['systemctl', 'reload', 'nginx']
    assert not (state / 'pending.json').exists()


def test_public_probe_failure_restores_safe_ingress(owned, monkeypatch):
    config, state = owned
    site.install('safe before')
    monkeypatch.setattr(site, 'validate', lambda request: None)
    monkeypatch.setattr(site, 'verify', lambda: (_ for _ in ()).throw(RuntimeError('public probe rejected')))
    request = {'phase': 'https', 'template': 'candidate', 'digest': site.digest(b'candidate')}
    with pytest.raises(RuntimeError, match='public probe rejected'): site.execute(request)
    assert config.read_text() == 'safe before'
    assert json.loads((state / 'failure.json').read_text())['restored_previous'] is True


def test_dns_with_another_ipv6_endpoint_is_blocked(owned, monkeypatch):
    monkeypatch.setattr(site.socket, 'getaddrinfo', lambda *args, **kwargs: [
        (2, 1, 6, '', (site.ADDRESS, 80)), (10, 1, 6, '', ('2001:db8::1', 80, 0, 0))])
    template = (Path(__file__).resolve().parents[1] / 'nginx/customer-orders.conf.template').read_text().replace('__PORTAL_DOMAIN__', site.DOMAIN)
    with pytest.raises(RuntimeError, match='DNS'):
        site.validate({'phase': 'plan', 'domain': site.DOMAIN, 'template': template,
            'digest': hashlib.sha256(template.encode()).hexdigest(), 'revision': 'a' * 40, 'script_digest': 'b' * 64})


def test_reload_convergence_retries_without_disabling_certificate_checks(monkeypatch):
    calls = []
    def once():
        calls.append(True)
        if len(calls) == 1: raise site.urllib.error.URLError('old worker certificate')
        return {'https_verified': True}
    monkeypatch.setattr(site, 'verify_once', once)
    monkeypatch.setattr(site.time, 'sleep', lambda seconds: None)
    assert site.verify() == {'https_verified': True} and len(calls) == 2
