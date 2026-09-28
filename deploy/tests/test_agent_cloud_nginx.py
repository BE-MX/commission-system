"""Agent route migration checks with local files and mocked nginx/systemctl."""

import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_cloud_nginx as routing


ORIGINAL = '''server {
    listen 80;
    server_name leshine.cloud www.leshine.cloud;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name leshine.cloud www.leshine.cloud;
    ssl_certificate /etc/letsencrypt/live/leshine.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/leshine.cloud/privkey.pem;
    location /api/ { proxy_pass http://127.0.0.1:8001; }
    location ^~ /mcp/ { proxy_pass http://127.0.0.1:8001; }
    location / { root /var/www/ark-dist; try_files $uri /index.html; }
}
'''


@pytest.fixture
def host(tmp_path, monkeypatch):
    nginx = tmp_path / 'nginx'
    (nginx / 'sites-enabled').mkdir(parents=True)
    (nginx / 'conf.d').mkdir()
    main = nginx / 'nginx.conf'
    main.write_text('events {}\nhttp { include conf.d/*.conf; include sites-enabled/*; }\n')
    site = nginx / 'sites-enabled/ark-cloud.conf'
    site.write_text(ORIGINAL)
    zone = nginx / 'conf.d/ark-agent-social-customer-limit.conf'
    machine = tmp_path / 'machine-id'
    machine.write_text('a' * 32)
    for key, value in {'NGINX_ROOT': nginx, 'MAIN': main, 'SITE': site, 'ZONE': zone,
                       'STATE': tmp_path / 'state', 'MACHINE_ID': machine}.items():
        monkeypatch.setattr(routing, key, value)
    monkeypatch.setattr(routing.os, 'geteuid', lambda: 0, raising=False)
    command = Mock()
    monkeypatch.setattr(routing, 'run', command)
    return {'target': routing.TARGET, 'expected_machine_id': 'a' * 32}, site, zone, command


def prepared(host):
    request, site, zone, command = host
    plan = routing.execute({**request, 'action': 'prepare'})
    return {**request, 'plan_id': plan['plan_id'], 'original_sha256': plan['original_sha256']}, plan


def test_render_is_idempotent_and_preserves_other_routes():
    candidate = routing.render(ORIGINAL)
    assert routing.render(candidate) == candidate
    assert candidate.replace('\n' + routing.snippet(), '') == ORIGINAL
    assert candidate.index(routing.BEGIN) > candidate.index('listen 80;')
    assert candidate.count(routing.BEGIN) == 1
    assert 'proxy_pass http://127.0.0.1:8001;' in candidate
    assert '/messages?' not in candidate.split('server {', 2)[1]


def test_route_contracts():
    content = routing.snippet()
    for service, port in [('inventory-mcp', 3100), ('shipment-mcp', 3200)]:
        assert f'location = /{service}/sse' in content
        assert f'location = /{service}/messages' in content
        assert f'proxy_pass http://127.0.0.1:{port}/sse;' in content
        assert f"sub_filter 'data: /messages?' 'data: /{service}/messages?';" in content
    assert 'location = /relay/ws' in content
    assert 'location = /relay/ws {\n    access_log off;' in content
    assert 'proxy_pass http://127.0.0.1:3800/ws;' in content
    assert 'proxy_set_header Upgrade $http_upgrade;' in content
    assert content.count('proxy_set_header Authorization $http_authorization;') == 7
    assert '18789' not in content


@pytest.mark.parametrize('content', [ORIGINAL.replace('443 ssl', '444 ssl'),
                                    ORIGINAL + ORIGINAL, ORIGINAL.replace('www.leshine.cloud', 'other.cloud'),
                                    ORIGINAL.replace('location / {', 'location /relay/ {')])
def test_unknown_layout_and_conflicts_rejected(content):
    with pytest.raises(ValueError):
        routing.render(content)


def test_prepare_does_not_mutate_active_files_or_reload(host):
    request, site, zone, command = host
    call, plan = prepared(host)
    assert site.read_text() == ORIGINAL
    assert not zone.exists()
    assert all('reload' not in item.args[0] for item in command.call_args_list)
    expanded = (routing.STATE / plan['plan_id'] / 'candidate-main.conf').read_text()
    assert routing.ZONE_TEXT in expanded
    assert routing.snippet() in expanded
    assert 'include sites-enabled/' not in expanded
    assert not list(routing.NGINX_ROOT.glob('.ark-agent-check-*'))
    check_command = command.call_args.args[0]
    assert '-p' not in check_command
    assert Path(check_command[-1]).parent == routing.NGINX_ROOT
    assert routing.execute({**request, 'action': 'prepare'})['plan_id'] == plan['plan_id']


def test_activate_verify_and_retry(host):
    request, site, zone, command = host
    call, plan = prepared(host)
    result = routing.execute({**call, 'action': 'activate'})
    assert result['status'] == 'active'
    assert site.read_text() == routing.render(ORIGINAL)
    assert zone.read_text() == routing.ZONE_TEXT
    assert routing.execute({**call, 'action': 'verify'})['status'] == 'verified'
    reloads = [item for item in command.call_args_list if item.args[0] == ['systemctl', 'reload', 'nginx']]
    assert len(reloads) == 1
    routing.execute({**call, 'action': 'activate'})
    assert len([item for item in command.call_args_list if 'reload' in item.args[0]]) == 1


def test_reload_failure_restores_original_and_removes_new_zone(host):
    request, site, zone, command = host
    call, plan = prepared(host)
    failed = False

    def run(args):
        nonlocal failed
        if 'reload' in args and not failed:
            failed = True
            raise RuntimeError('reload failed')

    command.side_effect = run
    with pytest.raises(RuntimeError, match='original nginx configuration restored'):
        routing.execute({**call, 'action': 'activate'})
    assert site.read_text() == ORIGINAL
    assert not zone.exists()
    saved = json.loads((routing.STATE / plan['plan_id'] / 'plan.json').read_text())
    assert saved['status'] == 'rolled-back'
    assert routing.execute({**call, 'action': 'activate'})['status'] == 'active'


def test_drift_or_wrong_approval_digest_prevents_activation(host):
    request, site, zone, command = host
    call, plan = prepared(host)
    with pytest.raises(ValueError, match='digest mismatch'):
        routing.execute({**call, 'action': 'activate', 'original_sha256': '0' * 64})
    site.write_text(ORIGINAL + '# concurrent edit\n')
    with pytest.raises(ValueError, match='changed after preparation'):
        routing.execute({**call, 'action': 'activate'})
    assert site.read_text().endswith('# concurrent edit\n')
    assert not zone.exists()


def test_existing_global_zone_is_reused(host):
    request, site, zone, command = host
    (zone.parent / 'existing.conf').write_text(routing.ZONE_TEXT)
    call, plan = prepared(host)
    assert plan['zone_candidate_sha256'] is None
    routing.execute({**call, 'action': 'activate'})
    assert not zone.exists()


def test_unincluded_new_zone_is_rejected(host):
    request, site, zone, command = host
    routing.MAIN.write_text('events {}\nhttp { include sites-enabled/*; }')
    with pytest.raises(ValueError, match='not included exactly once'):
        prepared(host)


@pytest.mark.parametrize('change', [{'target': 'root@119.28.107.92'}, {'expected_machine_id': 'b' * 32}])
def test_wrong_host_rejected_before_commands(host, change):
    request, site, zone, command = host
    with pytest.raises(ValueError):
        routing.execute({**request, **change, 'action': 'prepare'})
    command.assert_not_called()


def test_nginx_candidate_failure_never_reloads_or_writes(host):
    request, site, zone, command = host
    command.side_effect = [None, RuntimeError('candidate invalid')]
    with pytest.raises(RuntimeError, match='candidate invalid'):
        prepared(host)
    assert site.read_text() == ORIGINAL
    assert not zone.exists()
    assert not list(routing.NGINX_ROOT.glob('.ark-agent-check-*'))


def test_comment_does_not_fake_existing_limit_zone(host):
    request, site, zone, command = host
    (zone.parent / 'comments.conf').write_text('# ' + routing.ZONE_TEXT)
    call, plan = prepared(host)
    assert plan['zone_candidate_sha256'] is not None


def test_preexisting_managed_zone_survives_rollback(host):
    request, site, zone, command = host
    zone.write_bytes(routing.ZONE_TEXT.encode())
    call, plan = prepared(host)
    failed = False

    def run(args):
        nonlocal failed
        if 'reload' in args and not failed:
            failed = True
            raise RuntimeError('reload failed')

    command.side_effect = run
    with pytest.raises(RuntimeError, match='original nginx configuration restored'):
        routing.execute({**call, 'action': 'activate'})
    assert zone.read_text() == routing.ZONE_TEXT
    assert site.read_text() == ORIGINAL
