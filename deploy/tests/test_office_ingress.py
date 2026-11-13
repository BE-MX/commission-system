"""No production services/data: exercise routing boundaries and failure rollback."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ingress', DEPLOY / 'office_ingress_remote.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def original():
    blocks = []
    for feature in m.FEATURES:
        count = 4 if feature == 'SHIPPING VIDEO' else 1
        blocks.append(f'# BEGIN ARK {feature} ROUTING\n' + (
            'location /test {\nproxy_pass https://119.28.107.92;\n'
            'proxy_ssl_verify on;\nproxy_set_header Host leshine.work;\n'
            'proxy_next_upstream off;\n}\n') * count
            + f'# END ARK {feature} ROUTING\n')
    return ('server {\n' + ''.join(blocks) +
            'location /api/ { proxy_pass http://127.0.0.1:8001; }\n'
            'location ^~ /mcp/social-customer/ { proxy_pass http://127.0.0.1:9000; }\n}\n') * 2


def test_route_boundary_and_no_automatic_write_retry():
    value = m.render(original())
    assert value.count('proxy_pass http://127.0.0.1:8002;') == 14
    assert value.count('proxy_next_upstream off;') == 16
    assert value.count('proxy_pass http://127.0.0.1:8001;') == 4
    assert value.count('location ^~ /mcp/social-customer/') == 2
    assert 'proxy_ssl_' not in value and '119.28.107.92' not in value


@pytest.mark.parametrize('change', [lambda x: x.replace('BEGIN ARK RECEIPT', 'BEGIN CUSTOM', 1),
    lambda x: x.replace('119.28.107.92', 'example.com', 1),
    lambda x: x + 'location /mcp/ {}', lambda x: m.render(x)])
def test_route_drift_or_repeat_refused(change):
    with pytest.raises(ValueError):
        m.render(change(original()))


@pytest.fixture
def local_routes(tmp_path, monkeypatch):
    root = tmp_path / 'state'; root.mkdir()
    nginx = tmp_path / 'nginx'; nginx.write_text(original())
    monkeypatch.setattr(m, 'ROOT', root)
    # Routes only permit /etc/nginx in production; use a path shim for fixtures.
    class FixedPath(type(nginx)):
        def is_relative_to(self, *args):
            return True
    monkeypatch.setattr(m, 'NGINX', FixedPath(nginx))
    monkeypatch.setattr(m, 'verify_tunnel', Mock(return_value={'health': 'ok'}))
    monkeypatch.setattr(m, 'run', Mock(return_value=''))
    return root, nginx


def test_activation_drift_does_not_write(local_routes):
    root, nginx = local_routes
    prepared = m.routes('routes-prepare', {})
    nginx.write_text(original() + '# changed\n')
    with pytest.raises(RuntimeError, match='changed after prepare'):
        m.routes('routes-activate', prepared)
    assert nginx.read_text().endswith('# changed\n')


def test_nginx_failure_restores_baseline(local_routes, monkeypatch):
    root, nginx = local_routes
    prepared = m.routes('routes-prepare', {})
    monkeypatch.setattr(m, 'run', Mock(side_effect=[RuntimeError('syntax'), '', '']))
    with pytest.raises(RuntimeError, match='syntax'):
        m.routes('routes-activate', prepared)
    assert nginx.read_text() == original()
    assert json.loads((root / 'routes.json').read_text())['status'] == 'failed-restored'


def test_rollback_preserves_unrelated_changes(local_routes):
    root, nginx = local_routes
    prepared = m.routes('routes-prepare', {})
    m.routes('routes-activate', prepared)
    nginx.write_text(nginx.read_text() + '# concurrent\n')
    with pytest.raises(RuntimeError, match='drift'):
        m.routes('rollback', {})


def test_success_and_explicit_rollback(local_routes):
    root, nginx = local_routes
    prepared = m.routes('routes-prepare', {})
    assert m.routes('routes-activate', prepared)['status'] == 'activated'
    assert nginx.read_text() == m.render(original())
    assert m.routes('rollback', {})['status'] == 'rolled-back'
    assert nginx.read_text() == original()


def test_failed_rollback_can_be_retried(local_routes, monkeypatch):
    root, nginx = local_routes
    prepared = m.routes('routes-prepare', {})
    m.routes('routes-activate', prepared)
    monkeypatch.setattr(m, 'run', Mock(side_effect=[RuntimeError('temporary'), '', '']))
    with pytest.raises(RuntimeError, match='temporary'):
        m.routes('rollback', {})
    assert json.loads((root / 'routes.json').read_text())['status'] == 'activated'
    monkeypatch.setattr(m, 'run', Mock(return_value=''))
    assert m.routes('rollback', {})['status'] == 'rolled-back'


def test_public_listener_rejected(monkeypatch):
    monkeypatch.setattr(m, 'run', lambda _: 'LISTEN 0 128 0.0.0.0:8002 0.0.0.0:* users:(("sshd"))')
    with pytest.raises(RuntimeError, match='loopback'):
        m.verify_tunnel()


@pytest.mark.parametrize('drift', ['', '# unrelated change\n'])
def test_rollback_after_colorwork_publisher_reorders_blocks(local_routes, drift):
    root, nginx = local_routes
    colorwork = ('# BEGIN ARK COLORWORK ROUTING\n'
                 'location ^~ /api/colorwork/ { proxy_pass http://127.0.0.1:8787; }\n'
                 '# END ARK COLORWORK ROUTING\n')
    before = original().replace('location /api/ {', colorwork + 'location /api/ {')
    nginx.write_text(before)
    m.routes('routes-activate', m.routes('routes-prepare', {}))
    reordered = nginx.read_text().replace(colorwork + m.MCP, m.MCP + colorwork)
    nginx.write_text(reordered + drift)
    if drift:
        with pytest.raises(RuntimeError, match='drift'):
            m.routes('rollback', {})
        assert nginx.read_text() == reordered + drift
    else:
        assert m.routes('rollback', {})['status'] == 'rolled-back'
        assert nginx.read_text() == before


def test_reordered_candidate_requires_untampered_snapshot(local_routes):
    root, nginx = local_routes
    m.routes('routes-activate', m.routes('routes-prepare', {}))
    current = nginx.read_text() + '# drift\n'
    (root / 'nginx-candidate.conf').write_text(current)
    record = json.loads((root / 'routes.json').read_text())
    assert not m.matches_active_candidate(current, record)


def test_effective_ssh_rejects_wider_forwarding(monkeypatch):
    monkeypatch.setattr(m, 'effective', lambda _: {'allowtcpforwarding': 'yes'})
    with pytest.raises(RuntimeError, match='restrictions'):
        m.verify_ssh()


def test_receipt_origin_preserves_other_settings_and_rejects_drift(local_routes, monkeypatch):
    root, nginx = local_routes
    m.routes('routes-activate', m.routes('routes-prepare', {}))
    env = root / 'fixture.env'
    before = 'SOME_KEY=fixture-only\nRECEIPT_STORAGE_PROXY_URL=https://leshine.work\nOTHER=value\n'
    env.write_text(before)
    monkeypatch.setattr(m, 'ENV', env)
    record = m.receipt_config()
    assert record['status'] == 'saved-restart-pending'
    assert env.read_text() == before.replace('https://leshine.work', 'https://leshine.cloud')
    assert (root / 'backend-env-before').read_text() == before
    assert m.receipt_config() == record
    env.write_text(env.read_text() + 'ADDED=setting\n')
    with pytest.raises(RuntimeError, match='changed'):
        m.receipt_config()
