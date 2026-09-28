"""Only old Agent ingress changes, with nginx and SSH absent from these tests."""

import base64
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_cloud_nginx as helper
import agent_cloud_source_routes as routes


def fixture_content(spec):
    result = []
    for path, (upstream, _) in spec.items():
        result.append(f'''location {'^~' if path.endswith('/') else '='} {path} {{
    proxy_pass {upstream};
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Origin $http_origin;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 3600s;
}}\n''')
    return ''.join(result)


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / 'nginx'
    for folder in ['snippets', 'conf.d', 'sites-enabled']:
        (root / folder).mkdir(parents=True)
    files = [root / 'snippets/ark-main-mcp-location.conf', root / 'conf.d/leshine.conf',
             root / 'sites-enabled/deputy-relay.conf']
    contents = [fixture_content(routes.SPECS[0]) + 'location ^~ /mcp/ { proxy_pass http://127.0.0.1:8002; }\n',
                'server {\ninclude snippets/ark-main-mcp-location.conf;\n' + fixture_content(routes.SPECS[1])
                + 'location /api/ { proxy_pass http://127.0.0.1:8002; }\n}\n',
                'upstream deputy_relay { server 127.0.0.1:3800; }\nserver {\n'
                + fixture_content(routes.SPECS[2]) + '}\n']
    for path, text in zip(files, contents):
        path.write_bytes(text.encode())
    main = root / 'nginx.conf'
    main.write_text('events {}\nhttp { include conf.d/*.conf; include sites-enabled/*; }')
    machine = tmp_path / 'machine-id'
    machine.write_text('b' * 32)
    monkeypatch.setattr(routes, 'FILES', files)
    monkeypatch.setattr(routes, 'STATE', tmp_path / 'state')
    monkeypatch.setattr(routes, 'MACHINE_ID', machine)
    monkeypatch.setattr(routes.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(helper, 'NGINX_ROOT', root)
    monkeypatch.setattr(helper, 'MAIN', main)
    command = Mock()
    monkeypatch.setattr(helper, 'run', command)
    return {'target': routes.TARGET, 'expected_machine_id': 'b' * 32}, files, contents, command


def prepare(source):
    request, files, originals, command = source
    plan = routes.execute({**request, 'action': 'prepare'}, helper)
    call = {**request, 'plan_id': plan['plan_id'], 'original_sha256': plan['original_sha256']}
    return call, plan


@pytest.mark.parametrize('spec', routes.SPECS)
def test_route_render_idempotent_and_retains_protocol_headers(spec):
    original = fixture_content(spec)
    candidate = routes.render(original, spec, helper)
    assert routes.render(candidate, spec, helper) == candidate
    for _, cloud_path in spec.values():
        assert 'proxy_pass https://154.8.205.162' + cloud_path + ';' in candidate
    assert candidate.count('proxy_ssl_verify on;') == len(spec)
    assert candidate.count('proxy_ssl_name leshine.cloud;') == len(spec)
    assert candidate.count('proxy_set_header Host leshine.cloud;') == len(spec)
    for retained in ['Authorization $http_authorization', 'Origin $http_origin', 'Upgrade $http_upgrade',
                     'Connection "upgrade"', 'proxy_buffering off', 'proxy_read_timeout 3600s']:
        assert candidate.count(retained) == original.count(retained)


def test_prepare_activate_verify_does_not_touch_office_routes(source):
    request, files, originals, command = source
    call, plan = prepare(source)
    assert [path.read_text() for path in files] == originals
    assert all('reload' not in item.args[0] for item in command.call_args_list)
    assert not list(helper.NGINX_ROOT.glob('.ark-source-agent-check-*'))
    assert routes.execute({**call, 'action': 'activate'}, helper)['status'] == 'active'
    assert 'location ^~ /mcp/ { proxy_pass http://127.0.0.1:8002; }' in files[0].read_text()
    assert 'location /api/ { proxy_pass http://127.0.0.1:8002; }' in files[1].read_text()
    assert routes.execute({**call, 'action': 'verify'}, helper)['status'] == 'verified'
    routes.execute({**call, 'action': 'activate'}, helper)
    assert len([item for item in command.call_args_list if 'reload' in item.args[0]]) == 1
    assert not any(any(name in item.args[0] for name in ['start', 'enable', 'pm2']) for item in command.call_args_list)


def test_failure_restores_all_three_files(source):
    request, files, originals, command = source
    call, plan = prepare(source)
    failed = False

    def run(args):
        nonlocal failed
        if 'reload' in args and not failed:
            failed = True
            raise RuntimeError('reload rejected')

    command.side_effect = run
    with pytest.raises(RuntimeError, match='original nginx restored'):
        routes.execute({**call, 'action': 'activate'}, helper)
    assert [path.read_text() for path in files] == originals
    assert routes.execute({**call, 'action': 'activate'}, helper)['status'] == 'active'


def test_changed_file_blocks_whole_activation(source):
    request, files, originals, command = source
    call, plan = prepare(source)
    files[1].write_text(originals[1] + '# manual edit\n')
    with pytest.raises(ValueError, match='changed since prepare'):
        routes.execute({**call, 'action': 'activate'}, helper)
    assert files[0].read_text() == originals[0]
    assert files[2].read_text() == originals[2]


def test_wrong_source_machine_and_original_digests_rejected(source):
    request, files, originals, command = source
    with pytest.raises(ValueError, match='identity mismatch'):
        routes.execute({**request, 'expected_machine_id': 'a' * 32, 'action': 'prepare'}, helper)
    call, plan = prepare(source)
    with pytest.raises(ValueError, match='original digests differ'):
        routes.execute({**call, 'action': 'activate', 'original_sha256': {}}, helper)


@pytest.mark.parametrize('replacement', ['https://other.example/', 'http://127.0.0.1:8002; proxy_pass http://127.0.0.1:8100/'])
def test_unexpected_or_duplicate_upstream_rejected(replacement):
    original = fixture_content(routes.SPECS[0]).replace('http://127.0.0.1:8100/', replacement)
    with pytest.raises(ValueError):
        routes.render(original, routes.SPECS[0], helper)


def test_missing_location_rejected():
    with pytest.raises(ValueError, match='location is missing'):
        routes.render('location /mcp/ { proxy_pass http://127.0.0.1:8002; }', routes.SPECS[0], helper)


def test_sse_endpoint_filter_is_unchanged():
    content = fixture_content(routes.SPECS[0]).replace('proxy_buffering off;',
        "proxy_buffering off; sub_filter 'data: /messages?' 'data: /inventory-mcp/messages?';", 1)
    candidate = routes.render(content, routes.SPECS[0], helper)
    assert "sub_filter 'data: /messages?' 'data: /inventory-mcp/messages?';" in candidate


def test_base64_helper_load_does_not_run_helper_main():
    source = Path(helper.__file__).read_bytes()
    loaded = routes.helper_from({'helper_source_b64': base64.b64encode(source).decode()})
    assert loaded.digest(b'test') == helper.digest(b'test')
    assert loaded.__name__ == 'agent_cloud_nginx'


def test_server_proxy_headers_are_preserved_when_setting_location_host():
    content = '''server {
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Authorization $http_authorization;
    location /ws { proxy_pass http://deputy_relay; }
}'''
    spec = {'/ws': routes.SPECS[2]['/ws']}
    candidate = routes.render(content, spec, helper)
    assert routes.render(candidate, spec, helper) == candidate
    block = candidate[candidate.index('location /ws'):]
    assert 'proxy_set_header Host leshine.cloud;' in block
    assert 'proxy_set_header Upgrade $http_upgrade;' in block
    assert 'proxy_set_header Connection "upgrade";' in block
    assert 'proxy_set_header Authorization $http_authorization;' in block
    assert 'access_log off;' in block


@pytest.mark.parametrize('path,spec', [('/ws', routes.SPECS[2]), ('/relay/ws', routes.SPECS[1])])
def test_websocket_access_logging_disabled_even_if_originally_explicit(path, spec):
    selected = {path: spec[path]}
    original = fixture_content(selected).replace('proxy_buffering off;', 'proxy_buffering off; access_log /var/log/relay.log;')
    candidate = routes.render(original, selected, helper)
    assert candidate.count('access_log off;') == 1
    assert '/var/log/relay.log' not in candidate
    assert routes.render(candidate, selected, helper) == candidate


def test_explicit_host_only_keeps_original_header_inheritance_boundary():
    content = '''server {
    proxy_set_header X-Parent custom;
    location /ws { proxy_pass http://deputy_relay; proxy_set_header Host $host; }
}'''
    spec = {'/ws': routes.SPECS[2]['/ws']}
    candidate = routes.render(content, spec, helper)
    assert routes.render(candidate, spec, helper) == candidate
    assert 'X-Parent' not in candidate[candidate.index('location /ws'):]
