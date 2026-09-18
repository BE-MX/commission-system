"""Routing preparation and failure safety; no production data or services."""

import importlib.util
from pathlib import Path
import re
from unittest.mock import Mock

import pytest

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("voucher_remote", DEPLOY / "voucher_routing_remote.py")
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


def snippet(region):
    return (DEPLOY / "nginx" / f"domestic-voucher-{region}.conf").read_text()


def config(region):
    _, port, count = routing.SPECS[region]
    return ("server {\n    location /api/ {\n        proxy_pass http://127.0.0.1:"
            + port + ";\n    }\n}\n") * count


@pytest.mark.parametrize("region", ["office", "cloud"])
def test_receipts_route_only_receipt_api_to_office(region):
    source = (DEPLOY / "nginx" / f"receipt-{region}.conf").read_text()
    candidate = routing.render(config(region), source, region, "receipt")
    assert routing.render(candidate, source, region, "receipt") == candidate
    pattern = re.search(r"location ~ (.+) \{", source).group(1)
    for path in ["/api/receipts", "/api/receipts/attachments", "/api/receipts/attachments/abc", "/api/receipts/types"]:
        assert re.match(pattern, path)
    for path in ["/api/receipts-other", "/api/invoice", "/api/domestic/customers"]:
        assert not re.match(pattern, path)
    assert "client_max_body_size 11m;" in source
    assert "proxy_request_buffering off;" in source
    assert "proxy_send_timeout 300s;" in source
    assert "proxy_next_upstream off;" in source
    assert "proxy_set_header Authorization $http_authorization;" in source
    if region == "cloud":
        assert "proxy_ssl_verify on;" in source and "proxy_ssl_name leshine.work;" in source
    with pytest.raises(ValueError):
        routing.render(config(region) + "\nlocation /api/receipts {}", source, region, "receipt")


@pytest.mark.parametrize("region", ["office", "cloud"])
def test_routing_changes_only_voucher_paths_and_is_repeatable(region):
    original = config(region)
    candidate = routing.render(original, snippet(region), region)
    assert routing.render(candidate, snippet(region), region) == candidate
    pattern = re.search(r"location ~ (.+) \{", snippet(region)).group(1)
    for path in ["/api/domestic/customers/12/recharges", "/api/domestic/customer-requests/34/voucher"]:
        assert re.fullmatch(pattern, path)
    for path in ["/api/domestic/customer-requests", "/api/domestic/customer-requests/34/approve",
                 "/api/domestic/customer-requests/34/reject", "/api/domestic/customers/12/adjust",
                 "/api/domestic/orders", "/api/domestic/images/aa/test.png",
                 "/api/domestic/customer-requests/34/voucher/other"]:
        assert not re.fullmatch(pattern, path)
    assert candidate.count("proxy_pass http://127.0.0.1:" + routing.SPECS[region][1]) >= routing.SPECS[region][2]
    assert "proxy_next_upstream off;" in candidate
    assert "proxy_set_header Authorization $http_authorization;" in candidate
    assert "proxy_cache off;" in candidate


@pytest.mark.parametrize("bad", ["", "location ^~ /api/ { proxy_pass http://127.0.0.1:8001; }",
                                    "# /api/domestic/ already managed elsewhere"])
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
    request = {"region": "cloud", "snippet": snippet("cloud"), "action": "prepare"}
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


@pytest.mark.parametrize('region', ['office', 'cloud'])
def test_shipping_video_routing_coexists_with_vouchers_without_changing_ownership(region):
    video = (DEPLOY / 'nginx' / f'shipping-video-{region}.conf').read_text()
    original = config(region)
    vouchers = routing.render(original, snippet(region), region)
    candidate = routing.render(vouchers, video, region, 'shipping-video')
    assert routing.render(candidate, video, region, 'shipping-video') == candidate
    refreshed = routing.render(candidate, snippet(region), region)
    # Each renderer inserts its own block next to /api; ordering between the two
    # non-overlapping routes can change, but neither block may be removed/duplicated.
    assert snippet(region).strip() in refreshed and video.strip() in refreshed
    assert refreshed.count('# BEGIN ARK SHIPPING VIDEO ROUTING') == routing.SPECS[region][2]
    assert routing.render(refreshed, snippet(region), region) == refreshed
    assert 'location = /api/mini/shipping-inspection/videos {' in candidate
    assert 'client_max_body_size 101m;' in candidate
    assert 'proxy_next_upstream off;' in video
    assert 'proxy_set_header Authorization $http_authorization;' in video
    assert f'proxy_pass http://127.0.0.1:{routing.SPECS[region][1]};' in video
    assert 'proxy_read_timeout 300s;' in video
    assert 'proxy_request_buffering off;' in video


@pytest.mark.parametrize('region', ['office', 'cloud'])
def test_station_upload_routes_are_narrow_and_keep_host_ownership(region):
    content = (DEPLOY / 'nginx' / f'shipping-video-{region}.conf').read_text()
    patterns = re.findall(r'location ~ (\S+) \{', content)
    assert len(patterns) == 2
    for suffix in ['photos', 'videos']:
        path = '/api/shipping-inspection/station/sessions/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/' + suffix
        assert sum(bool(re.fullmatch(pattern, path)) for pattern in patterns) == 1
    for path in ['/api/shipping-inspection/station/scan', '/api/shipping-inspection/station/sessions/abc/submit', '/api/assets/upload']:
        assert not any(re.fullmatch(pattern, path) for pattern in patterns)
    assert 'client_max_body_size 21m;' in content
    assert content.count(f'proxy_pass http://127.0.0.1:{routing.SPECS[region][1]};') == 3
    with pytest.raises(ValueError):
        routing.render(config(region) + '\n# /api/shipping-inspection/station/ already managed', content, region, 'shipping-video')


def test_shipping_video_prepare_and_failed_activation_preserve_live_config(site):
    path, command, request = site
    request.update(feature='shipping-video', snippet=(DEPLOY / 'nginx/shipping-video-cloud.conf').read_text())
    original = path.read_bytes()
    prepared = routing.execute(request)
    assert path.read_bytes() == original
    command.reset_mock()
    command.side_effect = [None, RuntimeError('reload failed'), None, None]
    with pytest.raises(RuntimeError, match='reload failed'):
        routing.execute({**request, **prepared, 'action': 'activate'})
    assert path.read_bytes() == original
    assert list((routing.STATE.parent / 'shipping-video').glob('cloud-*.conf'))
