"""Color guide publication checks use only temporary files and fake commands."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import color_guide_site as release
import color_guide_site_remote as site


@pytest.fixture
def owned(tmp_path, monkeypatch):
    config = tmp_path / 'nginx.conf'
    state = tmp_path / 'state'
    state.mkdir()
    monkeypatch.setattr(site, 'CONFIG', config)
    monkeypatch.setattr(site, 'STATE', state)
    monkeypatch.setattr(site, 'run', lambda args: b'')
    return config, state


def request():
    template = (release.HERE / 'nginx/color-guide.conf.template').read_text()
    return {'domain': site.DOMAIN, 'phase': 'plan', 'template': template, 'digest': site.digest(template.encode())}


def test_plan_requires_exact_reviewed_bytes(tmp_path):
    (tmp_path / 'index.html').write_text('approved')
    plan = {'source': str(tmp_path), 'files': release.static_sync.manifest(tmp_path)}
    assert release.validate_plan(plan)[0] == tmp_path
    (tmp_path / 'index.html').write_text('changed')
    with pytest.raises(ValueError, match='reviewed manifest'):
        release.validate_plan(plan)


def test_plan_rejects_unknown_domain(tmp_path):
    with pytest.raises(ValueError, match='domain'):
        release.validate_plan({'source': str(tmp_path), 'domain': 'another.example'})


def test_nginx_failure_restores_exact_previous(owned, monkeypatch):
    config, state = owned
    site.install('before')
    calls = []
    def fail_once(args):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError('bad nginx')
        return b''
    monkeypatch.setattr(site, 'run', fail_once)
    with pytest.raises(RuntimeError, match='bad nginx'):
        site.install('candidate')
    assert config.read_text() == 'before'
    assert json.loads((state / 'current.json').read_text())['config_digest'] == site.digest(b'before')
    assert not (state / 'pending.json').exists()
    assert calls[-1] == ['systemctl', 'reload', 'nginx']


def test_failed_install_preserves_concurrent_edit(owned, monkeypatch):
    config, state = owned
    def fail_with_drift(args):
        config.write_text('concurrent operator')
        raise RuntimeError('failure')
    monkeypatch.setattr(site, 'run', fail_with_drift)
    with pytest.raises(RuntimeError, match='drift'):
        site.install('candidate')
    assert config.read_text() == 'concurrent operator'
    assert (state / 'pending.json').exists()


def test_unacknowledged_install_leaves_pending_evidence(owned, monkeypatch):
    config, state = owned
    original = site.record
    def interrupted(path, value):
        if path.name == 'current.json':
            raise RuntimeError('interrupted')
        original(path, value)
    monkeypatch.setattr(site, 'record', interrupted)
    with pytest.raises(RuntimeError, match='interrupted'):
        site.install('candidate')
    assert config.read_text() == 'candidate'
    assert (state / 'pending.json').exists()


def test_pending_blocks_automatic_replay(owned, monkeypatch):
    _, state = owned
    (state / 'pending.json').write_text('{}')
    monkeypatch.setattr(site.socket, 'getaddrinfo', lambda *a: [(None, None, None, None, ('154.8.205.162', 80))])
    with pytest.raises(RuntimeError, match='Interrupted'):
        site.validate(request())


def test_unmanaged_configuration_is_not_adopted(owned, monkeypatch):
    config, _ = owned
    config.write_text('operator-owned')
    monkeypatch.setattr(site.socket, 'getaddrinfo', lambda *a: [(None, None, None, None, ('154.8.205.162', 80))])
    with pytest.raises(RuntimeError, match='unmanaged'):
        site.validate(request())
    assert config.read_text() == 'operator-owned'


def test_configure_checks_preparation_digest(owned, monkeypatch):
    config, _ = owned
    site.install('existing')
    monkeypatch.setattr(site, 'validate', lambda data: None)
    data = {**request(), 'phase': 'configure', 'expected': 'wrong'}
    with pytest.raises(RuntimeError, match='after preparation'):
        site.execute(data)
    assert config.read_text() == 'existing'


@pytest.mark.parametrize('existing', [True, False])
def test_certificate_failure_restores_initial_ingress_and_blocks_resend(owned, monkeypatch, existing):
    config, state = owned
    if existing:
        site.install('initial config')
    initial_receipt = (state / 'current.json').read_bytes() if existing else None
    monkeypatch.setattr(site, 'CERT', state / 'missing-certificate')
    monkeypatch.setattr(site, 'CHALLENGE_ROOT', state / 'challenge')
    monkeypatch.setattr(site, 'validate', lambda data: None)
    def fail_certificate(args):
        if args[0] == 'certbot':
            raise RuntimeError('certificate command failed')
        return b''
    monkeypatch.setattr(site, 'run', fail_certificate)
    data = {**request(), 'phase': 'configure', 'expected': site.config_digest()}
    with pytest.raises(RuntimeError, match='certificate command failed'):
        site.execute(data)
    assert config.exists() is existing
    if existing:
        assert config.read_text() == 'initial config'
        assert (state / 'current.json').read_bytes() == initial_receipt
    else:
        assert not (state / 'current.json').exists()
    assert (state / 'certificate-pending.json').exists()
    assert not (state / 'pending.json').exists()


def test_boundary_rejects_proxy_even_with_valid_digest():
    data = request()
    data['template'] += '\nproxy_pass http://127.0.0.1;'
    data['digest'] = site.digest(data['template'].encode())
    with pytest.raises(ValueError, match='Static-only'):
        site.validate(data)


def test_dns_must_only_select_expected_server(monkeypatch):
    monkeypatch.setattr(site.socket, 'getaddrinfo', lambda *a: [(None, None, None, None, ('192.0.2.1', 80))])
    with pytest.raises(RuntimeError, match='DNS'):
        site.validate(request())


def test_verify_rejects_wrong_live_index(monkeypatch):
    monkeypatch.setattr(site, 'run', lambda args: b'')
    monkeypatch.setattr(site, 'probe', lambda path, body=False: b'wrong' if body else b'404')
    with pytest.raises(RuntimeError, match='Live index'):
        site.verify(site.digest(b'correct'))


def test_public_api_must_be_unavailable(monkeypatch):
    monkeypatch.setattr(site, 'run', lambda args: b'')
    monkeypatch.setattr(site, 'probe', lambda path, body=False: b'200' if path.startswith('/api') else b'404')
    with pytest.raises(RuntimeError, match='boundary'):
        site.verify()
