"""Routing preparation and failure safety; no production data or services."""

import importlib.util
import io
import json
from pathlib import Path
import re
from unittest.mock import Mock

import pytest

DEPLOY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("colorwork_remote", DEPLOY / "colorwork_routing_remote.py")
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


def snippet(region):
    return (DEPLOY / "nginx" / f"colorwork-{region}.conf").read_text()


def config(region):
    _, port, count = routing.SPECS[region]
    return ("server {\n    location /api/ {\n        proxy_pass http://127.0.0.1:"
            + port + ";\n    }\n}\n") * count


@pytest.mark.parametrize("region", ["office", "cloud"])
def test_routing_changes_only_colorwork_paths_and_is_repeatable(region):
    original = config(region)
    candidate = routing.render(original, snippet(region), region)
    assert routing.render(candidate, snippet(region), region) == candidate
    prefix = re.search(r"location \^~ (.+) \{", snippet(region)).group(1)
    for path in ["/api/colorwork/sso", "/api/colorwork/workbench/api/auth/ark",
                 "/api/colorwork/workbench/assets/index.js", "/api/colorwork/workbench/file.html"]:
        assert path.startswith(prefix)
    for path in ["/api/domestic/orders", "/api/auth/login", "/api/colorwork-other/sso"]:
        assert not path.startswith(prefix)
    assert candidate.count("proxy_pass http://127.0.0.1:" + routing.SPECS[region][1]) >= routing.SPECS[region][2]
    assert "proxy_next_upstream off;" in candidate
    assert "proxy_set_header Authorization $http_authorization;" in candidate
    assert "proxy_cache off;" in candidate
    if region == "office":
        assert "proxy_pass https://154.8.205.162;" in snippet(region)
        assert "proxy_ssl_verify on;" in snippet(region)
        assert "proxy_set_header Host leshine.cloud;" in snippet(region)
        assert "set $colorwork_origin $http_origin;" in snippet(region)
        assert 'if ($http_origin = "https://leshine.work")' in snippet(region)
        assert 'if ($http_origin = "https://www.leshine.work")' in snippet(region)
    else:
        assert "proxy_pass http://127.0.0.1:8001;" in snippet(region)


@pytest.mark.parametrize("bad", ["", "location ^~ /api/ { proxy_pass http://127.0.0.1:8001; }",
                                    "# /api/colorwork/ already managed elsewhere"])
def test_unknown_or_conflicting_layout_is_rejected(bad):
    with pytest.raises(ValueError):
        routing.render(bad, snippet("cloud"), "cloud")


@pytest.mark.parametrize("region", ["office", "cloud"])
def test_managed_storage_deny_is_preserved_without_masking_conflicts(region):
    storage = "# BEGIN ARK STORAGE PUBLIC ROUTING\nlocation ^~ /api/colorwork/storage/ { return 404; }\n# END ARK STORAGE PUBLIC ROUTING\n"
    original = config(region).replace("    location /api/", storage + "    location /api/")
    candidate = routing.render(original, snippet(region), region)
    assert candidate.count(storage) == routing.SPECS[region][2]
    assert routing.render(candidate, snippet(region), region) == candidate
    for unsafe in [
        storage.replace("return 404;", "proxy_pass http://127.0.0.1:8001;"),
        storage.replace("/api/colorwork/storage/", "/api/colorwork/"),
        storage.replace("# END ARK STORAGE PUBLIC ROUTING", ""),
        storage.replace("# BEGIN ARK STORAGE PUBLIC ROUTING", ""),
        storage.replace("# END ARK STORAGE PUBLIC ROUTING", "location /api/colorwork/sso { return 200; }\n# END ARK STORAGE PUBLIC ROUTING"),
        "location ^~ /api/colorwork/storage/ { return 404; }\n",
    ]:
        with pytest.raises(ValueError, match="Conflicting colorwork"):
            routing.render(config(region).replace("    location /api/", unsafe + "    location /api/"), snippet(region), region)


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


@pytest.mark.parametrize("payload,status,valid", [
    ({"status": "ok", "module": "colorwork"}, 200, True),
    ({"code": 401, "message": "unauthorized"}, 401, False),
    ({"status": "ok"}, 200, False),
])
def test_readiness_identifies_module_not_just_http_success(monkeypatch, payload, status, valid):
    response = io.BytesIO(json.dumps(payload).encode())
    response.status = status
    probe = Mock(return_value=response)
    monkeypatch.setattr(routing.urllib.request, "urlopen", probe)
    if valid:
        routing.healthy("office")
    else:
        with pytest.raises(RuntimeError, match="readiness failed"):
            routing.healthy("office")
    assert probe.call_args.args[0] == "https://leshine.work/api/colorwork/workbench/api/health"
