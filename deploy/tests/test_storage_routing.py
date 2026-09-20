"""Routing preparation and failure safety; no production data or services."""

import importlib.util
import io
import json
from pathlib import Path
import re
from unittest.mock import Mock

import pytest

PROBES = ['/uploads/' + name + '/sample.jpg' for name in ['avatars', 'card', 'festival', 'expo', 'assets', 'tag_images']] + ['/uploads/hair/assets/sample.jpg', '/uploads/video/videos/sample.mp4']

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("storage_remote", DEPLOY / "storage_routing_remote.py")
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


def snippet(region):
    template = "cloud" if region == "cloud-ip" else region
    return (DEPLOY / "nginx" / f"storage-public-{template}.conf").read_text()


def config(region):
    _, port, count = routing.SPECS[region]
    return ("server {\n    location /api/ {\n        proxy_pass http://127.0.0.1:"
            + port + ";\n    }\n}\n") * count


@pytest.mark.parametrize("region", list(routing.SPECS))
def test_repeatable_render_keeps_existing_business_routes(region):
    if region in {'hair', 'video'}:
        root = 'hair-styles' if region == 'hair' else 'video.leshine.work'
        original = 'server { root /var/www/' + root + '; index index.html; location / { try_files $uri =404; } }'
    else:
        original = config(region)
    candidate = routing.render(original, snippet(region), region)
    assert routing.render(candidate, snippet(region), region) == candidate
    assert candidate.count(routing.BEGIN) == routing.SPECS[region][2]
    assert 'proxy_cache off;' in candidate
    assert 'proxy_next_upstream off;' in candidate
    if region in {'cloud', 'office'}:
        assert 'location ^~ /api/colorwork/storage/ { return 404; }' in candidate
        assert candidate.index('expo/(pending|beautify_previews)') < candidate.index('(avatars|card|festival')


@pytest.mark.parametrize("bad", ["", "location ^~ /api/ { proxy_pass http://127.0.0.1:8001; }",
                                    "# X-Ark-Storage already managed elsewhere"])
def test_unknown_or_conflicting_layout_is_rejected(bad):
    with pytest.raises(ValueError):
        routing.render(bad, snippet("cloud"), "cloud")


@pytest.fixture
def site(tmp_path, monkeypatch):
    path = tmp_path / "site.conf"
    path.write_text(config("cloud"))
    monkeypatch.setitem(routing.SPECS, "cloud", (str(path), "8001", 2))
    monkeypatch.setattr(routing, "STATE", tmp_path / "backups")
    # Only the production allowlist check is replaced, not rendering/writes/rollback.
    original = Path.is_relative_to
    monkeypatch.setattr(Path, "is_relative_to", lambda self, other: (
        True if str(other) == "/etc/nginx" and self == path else original(self, other)))
    command = Mock()
    monkeypatch.setattr(routing, "run", command)
    monkeypatch.setattr(routing, "healthy", Mock())
    request = {"region": "cloud", "snippet": snippet("cloud"), "action": "prepare", "probes": PROBES}
    return path, command, request


def test_prepare_never_changes_live_config_or_reloads(site):
    path, command, request = site
    original = path.read_bytes()
    result = routing.execute(request)
    assert result["status"] == "prepared"
    assert path.read_bytes() == original
    assert command.call_count == 1
    assert command.call_args.args[0][:3] == ["nginx", "-t", "-c"]


@pytest.mark.parametrize("region", ["office", "cloud"])
def test_prepare_isolates_all_nginx_runtime_paths(site, region, monkeypatch):
    path, command, request = site
    # Both sites use the same scratch generator; exercise each region's paths.
    monkeypatch.setitem(routing.SPECS, region, (str(path), "8001", 2))
    request = {**request, "region": region, "snippet": snippet(region)}
    routing.execute(request)
    assert command.call_args.args[0][4:] == ["-e", "stderr"]
    config_path = Path(command.call_args.args[0][3])
    syntax = config_path.read_text()
    for directive in ("client_body_temp_path", "proxy_temp_path", "fastcgi_temp_path",
                      "uwsgi_temp_path", "scgi_temp_path", "pid"):
        match = re.search(r"(?m)^" + directive + r' "([^";]+)";', syntax)
        assert match, f"Missing isolated {directive}: nginx would use live defaults"
        target = Path(match.group(1))
        assert target.is_absolute()
        assert target.is_relative_to(routing.STATE)
    assert "error_log stderr;" in syntax
    assert "access_log off;" in syntax
    assert "/var/lib/nginx" not in syntax


def test_configuration_drift_blocks_activation(site):
    path, command, request = site
    prepared = routing.execute(request)
    changed = path.read_text() + "\n# Another operator's change\n"
    path.write_text(changed)
    command.reset_mock()
    with pytest.raises(RuntimeError, match="changed since preparation"):
        routing.execute({**request, **prepared, "action": "activate"})
    assert path.read_text() == changed
    command.assert_not_called()


@pytest.mark.parametrize("failure_index", [0, 1])
def test_validation_or_reload_failure_restores_exact_original(site, failure_index):
    path, command, request = site
    original = path.read_bytes()
    prepared = routing.execute(request)
    command.reset_mock()
    outcomes = [None, None, None, None]
    outcomes[failure_index] = RuntimeError("nginx failure")
    command.side_effect = outcomes
    with pytest.raises(RuntimeError, match="nginx failure"):
        routing.execute({**request, **prepared, "action": "activate"})
    assert path.read_bytes() == original
    assert list(routing.STATE.glob("cloud-*.conf"))


def test_success_and_repeat_activation(site):
    path, command, request = site
    prepared = routing.execute(request)
    assert routing.execute({**request, **prepared, "action": "activate"})["status"] == "activated"
    prepared = routing.execute(request)
    command.reset_mock()
    assert routing.execute({**request, **prepared, "action": "activate"})["status"] == "unchanged"
    command.assert_not_called()


def test_inactive_workbench_blocks_before_config_write(site, monkeypatch):
    path, command, request = site
    original = path.read_bytes()
    prepared = routing.execute(request)
    command.reset_mock()
    monkeypatch.setattr(routing, "healthy", Mock(side_effect=RuntimeError("unavailable")))
    with pytest.raises(RuntimeError, match="unavailable"):
        routing.execute({**request, **prepared, "action": "activate"})
    assert path.read_bytes() == original
    command.assert_not_called()


def test_bad_public_route_rolls_back(site, monkeypatch):
    path, command, request = site
    original = path.read_bytes()
    prepared = routing.execute(request)
    monkeypatch.setattr(routing, "healthy", Mock(side_effect=[None, RuntimeError("wrong service")]))
    with pytest.raises(RuntimeError, match="wrong service"):
        routing.execute({**request, **prepared, "action": "activate"})
    assert path.read_bytes() == original



@pytest.mark.parametrize('region,host', [('cloud','leshine.cloud'),('office','leshine.work'),('cloud-ip','154.8.205.162'),('hair','hair.leshine.work'),('video','video.leshine.work')])
def test_probe_uses_actual_public_site(region, host):
    urls = routing.probe_urls(PROBES, region)
    assert all(url.startswith('https://' + host + '/') for url in urls)
    if region in {'hair', 'video'}:
        assert all('/uploads/' not in url for url in urls)


@pytest.mark.parametrize('bad', [[], ['/uploads/expo/a.jpg'], PROBES + ['/uploads/expo/%2e%2e/a.jpg'], PROBES + ['/uploads/expo/pending/a.jpg'], PROBES + ['https://evil.test/a'], PROBES + ['/uploads/expo/%252e%252e/a']])
def test_incomplete_unsafe_or_temporary_probes_rejected(bad):
    with pytest.raises(ValueError):
        routing.probe_urls(bad)


def test_wrong_public_backend_marker_fails(monkeypatch):
    response = io.BytesIO(b'')
    response.status = 200
    response.headers = {'X-Ark-Storage': 'local'}
    monkeypatch.setattr(routing.urllib.request, 'build_opener', Mock(return_value=Mock(open=Mock(return_value=response))))
    with pytest.raises(RuntimeError, match='not ready'):
        routing.healthy(PROBES)


def test_redirect_is_not_followed():
    assert routing.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test') is None


def test_kiosk_uses_existing_certificate_without_disabling_verification(monkeypatch):
    context = Mock()
    create = Mock(return_value=context)
    monkeypatch.setattr(routing.ssl, 'create_default_context', create)
    opener = Mock()
    opener.open.side_effect = RuntimeError('stop before network')
    monkeypatch.setattr(routing.urllib.request, 'build_opener', Mock(return_value=opener))
    with pytest.raises(RuntimeError, match='stop before network'):
        routing.healthy(PROBES, 'cloud-ip')
    create.assert_called_once_with(cafile=str(routing.IP_CERTIFICATE))
    assert context.check_hostname is False
    assert 'verify_mode' not in context.__dict__


def test_certificate_drift_blocks_before_any_config_write(site, tmp_path, monkeypatch):
    path, command, request = site
    path.write_text('server { location /api/ { proxy_pass http://127.0.0.1:8001; } }')
    monkeypatch.setitem(routing.SPECS, 'cloud-ip', (str(path), '8001', 1))
    certificate = tmp_path / 'kiosk.crt'
    certificate.write_bytes(b'original certificate fixture')
    monkeypatch.setattr(routing, 'IP_CERTIFICATE', certificate)
    request = {**request, 'region':'cloud-ip'}
    prepared = routing.execute(request)
    original = path.read_bytes()
    certificate.write_bytes(b'replaced certificate fixture')
    command.reset_mock()
    with pytest.raises(RuntimeError, match='certificate changed'):
        routing.execute({**request, **prepared, 'action':'activate'})
    assert path.read_bytes() == original
    command.assert_not_called()


@pytest.mark.parametrize('path,minimum', [('/api/assets/upload',501),('/api/assets/7/version',501),('/api/customer-media/batches/2/assets',501),('/api/training/3/files',301),('/api/aftersales/cases/7/evidence',201),('/api/pm/materials/1/versions',51),('/api/design/requests/1/attachments',21),('/api/knowledge/libraries/2/assets',11),('/api/insight/cases/upload',6)])
def test_attachment_upload_budget_covers_business_limit(path,minimum):
    import sys
    sys.path.insert(0,str(DEPLOY))
    from storage_upload_routes import LIMITS,snippet
    matches=[limit for pattern,limit in LIMITS if re.fullmatch(pattern,path)]
    assert matches==[minimum]
    assert '127.0.0.1:8002' in snippet('office')
    assert '127.0.0.1:8001' in snippet('cloud')
    assert not any(re.fullmatch(pattern,'/api/receipts') for pattern,_ in LIMITS)
    assert not any(re.fullmatch(pattern,'/api/customer-media/batches/2/assets/unrelated') for pattern,_ in LIMITS)

@pytest.mark.parametrize('local_body,cloud_header,passes', [(b'same','cos',True),(b'changed','cos',False),(b'same',None,False)])
def test_office_durable_asset_requires_identical_cloud_bytes(monkeypatch,local_body,cloud_header,passes):
    class Response(io.BytesIO):
        status=200
        def __init__(self,data,header):
            super().__init__(data);self.headers={} if header is None else {'X-Ark-Storage':header}
    monkeypatch.setattr(routing,'probe_urls',lambda probes,region:['https://leshine.work/uploads/assets/probe.jpg'])
    opener=Mock()
    opener.open.side_effect=[Response(b'',None),Response(b'same',cloud_header),Response(local_body,None)]
    monkeypatch.setattr(routing.urllib.request,'build_opener',lambda *args:opener)
    if passes: routing.healthy(PROBES,'office')
    else:
        with pytest.raises(RuntimeError): routing.healthy(PROBES,'office')
