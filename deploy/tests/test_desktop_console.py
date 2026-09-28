"""Desktop protocol and remote worker tests; never connect to real servers."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
from unittest.mock import Mock

import pytest

DEPLOY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(DEPLOY), str(DEPLOY / "desktop")]
import desktop_events
import desktop_checks as checks
import desktop_host as host

RUN = "a" * 32
REVISION = "b" * 40


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "office folder (test)"
    (root / "deploy").mkdir(parents=True)
    (root / "deploy/deploy.bat").write_text("echo harmless fixture")
    (root / "deploy/desktop_events.py").write_text("PROTOCOL = 1")
    (root / "deploy/publish.py").write_text("from desktop_events import emit")
    return root


def record(root, status="prepared", run_id=RUN, **extra):
    path = host.run_path(root, run_id)
    path.mkdir(parents=True)
    host.atomic(path / "operation.json", dict(run_id=run_id, mode="prepare", status=status, revision=REVISION, **extra))
    return path


def test_events_are_opt_in_and_correlated(monkeypatch, capsys):
    monkeypatch.delenv("ARK_DESKTOP_RUN_ID", raising=False)
    desktop_events.step("stage", "stage", lambda: 42)
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("ARK_DESKTOP_RUN_ID", RUN)
    with pytest.raises(ValueError):
        desktop_events.step("stage", "stage", lambda: (_ for _ in ()).throw(ValueError("password=do-not-log")))
    output = capsys.readouterr().out
    rows = [json.loads(line[len(desktop_events.PREFIX):]) for line in output.splitlines()]
    assert [row["status"] for row in rows] == ["running", "failed"]
    assert all(row["run_id"] == RUN for row in rows)
    assert "do-not-log" not in output


@pytest.mark.parametrize("value", ["../anything", "A" * 32, "", "a" * 31])
def test_run_path_rejects_traversal(root, value):
    with pytest.raises(ValueError):
        host.run_path(root, value)


@pytest.mark.parametrize("suffix", ['%PATH%', '" & whoami', '\n', '!bad!'])
def test_root_rejects_command_expansion(root, suffix):
    with pytest.raises(ValueError):
        host.root_path(str(root) + suffix)


def test_reading_old_publish_success_cannot_create_desktop_success(root):
    path = record(root, "failed")
    host.atomic(root / ".deploy_state/publish-success.json", {"revision": REVISION})
    assert host.summarize(path)["status"] == "failed"


@pytest.mark.parametrize("expected,actual", [(123, None), (123, 456), (None, None)])
def test_dead_or_reused_worker_is_unknown(root, monkeypatch, expected, actual):
    path = record(root, "running", pid=44, process_identity=expected)
    monkeypatch.setattr(host, "process_identity", lambda _: actual)
    assert host.summarize(path)["status"] == "unknown"
    assert host.read(path / "operation.json")["status"] == "running"  # read-only query


def test_stale_start_is_unknown(root):
    path = record(root, "starting")
    os.utime(path / "operation.json", (time.time() - 100, time.time() - 100))
    assert host.summarize(path)["status"] == "unknown"


def test_summary_ignores_other_run_and_partial_event(root):
    path = record(root)
    events = [dict(protocol=1, run_id=RUN, kind="step", label="office", status="succeeded"),
              dict(protocol=1, run_id="c" * 32, kind="result", status="succeeded")]
    (path / "events.jsonl").write_text("\n".join(map(json.dumps, events)) + '\n{"unfinished":', encoding="utf-8")
    assert host.summarize(path)["events"] == events[:1]


def test_duplicate_start_is_idempotent_and_changed_mode_rejected(root, monkeypatch):
    record(root)
    spawn = Mock()
    monkeypatch.setattr(host.subprocess, "Popen", spawn)
    assert host.start(root, {"run_id": RUN, "mode": "prepare"}, {})["status"] == "prepared"
    spawn.assert_not_called()
    with pytest.raises(ValueError, match="different request"):
        host.start(root, {"run_id": RUN, "mode": "deploy"}, {})


def test_deploy_requires_successfully_prepared_run(root):
    record(root, "failed")
    with pytest.raises(ValueError, match="成功准备"):
        host.start(root, {"run_id": "d" * 32, "mode": "deploy", "prepared_run": RUN}, {})


def test_active_lock_blocks_other_clients(root):
    state = root / ".deploy_state/desktop"
    state.mkdir(parents=True)
    (state / "active.lock").write_text("original")
    with pytest.raises(RuntimeError, match="已有桌面任务"):
        host.start(root, {"run_id": RUN, "mode": "prepare"}, {})
    assert (state / "active.lock").read_text() == "original"


def test_dead_worker_does_not_delete_active_lock(root, monkeypatch):
    path = record(root, "running", pid=44, process_identity=123)
    lock = root / ".deploy_state/desktop/active.lock"
    lock.write_text(RUN)
    monkeypatch.setattr(host, "process_identity", lambda _: None)
    assert host.summarize(path)["status"] == "unknown"
    assert lock.exists()


@pytest.mark.parametrize("exit_code,result,status", [(0, "prepared", "prepared"), (1, "prepared", "failed"), (0, None, "unknown"), (0, "succeeded", "unknown")])
def test_worker_requires_exit_code_and_current_terminal_receipt(root, monkeypatch, exit_code, result, status):
    path = record(root, "starting")
    lock = root / ".deploy_state/desktop/active.lock"
    lock.write_text(RUN)
    event = dict(protocol=1, run_id=RUN, kind="result", status=result, revision=REVISION)
    process = Mock(stdout=io.StringIO(host.PREFIX + json.dumps(event) + "\n" if result else "old success log\n"))
    process.wait.return_value = exit_code
    monkeypatch.setattr(host.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(host, "configure_path", lambda: None)
    monkeypatch.setattr(host, "process_identity", lambda _: 123)
    host.worker(root, RUN)
    assert host.read(path / "operation.json")["status"] == status
    assert lock.exists() == (status == "unknown")


def test_failed_activation_precheck_does_not_start_engine(root, monkeypatch):
    path = record(root, "starting")
    data = host.read(path / "operation.json")
    data["mode"] = "deploy"
    host.atomic(path / "operation.json", data)
    monkeypatch.setattr(host, "configure_path", lambda: None)
    monkeypatch.setattr(host, "process_identity", lambda _: 123)
    monkeypatch.setattr(host, "probe", lambda _: {"ready": False, "checks": []})
    spawn = Mock()
    monkeypatch.setattr(host.subprocess, "Popen", spawn)
    host.worker(root, RUN)
    spawn.assert_not_called()
    assert host.read(path / "operation.json")["status"] == "failed"


def test_redacts_credentials_without_erasing_error_evidence():
    value = checks.redact('Permission denied https://user:pw@example.test password="one two" token=xyz Authorization: Bearer abc')
    assert "Permission denied" in value
    for secret in ("user:pw", "one two", "xyz", "abc"):
        assert secret not in value


def test_service_probe_rejects_stopped_and_pid_zero():
    with pytest.raises(RuntimeError, match="当前未运行"):
        checks.service_detail("ActiveState=inactive\nSubState=dead")
    with pytest.raises(RuntimeError, match="未发现"):
        checks.positive_pid("0")


@pytest.mark.parametrize("target,sudo", [("ubuntu@154.8.205.162", True), ("root@119.28.107.92", False)])
def test_pm2_probe_uses_registered_root_context(monkeypatch, root, target, sudo):
    command = Mock(return_value="3124")
    monkeypatch.setattr(checks, "command", command)
    writer = {"host": target, "executable": "/root/.nvm/versions/node/v22.22.1/bin/pm2"}
    assert "3124" in checks.pm2_pid(root, writer, "shipment-tracking-mcp")
    remote = command.call_args.args[0][-1]
    assert remote.startswith("sudo -n -H -u root ") == sudo
    assert "HOME=/root PM2_HOME=/root/.pm2" in remote
    assert remote.endswith(" pid shipment-tracking-mcp")
    assert " jlist" not in remote  # Never return service environment/secrets.


@pytest.mark.parametrize("target,binary,service", [("attacker.test", "/root/.nvm/versions/node/v22.22.1/bin/pm2", "safe"),
                                                  ("ubuntu@154.8.205.162", "/tmp/pm2", "safe"),
                                                  ("ubuntu@154.8.205.162", "/root/.nvm/versions/node/v22.22.1/bin/pm2", "bad;reboot")])
def test_pm2_probe_rejects_unregistered_commands(root, target, binary, service):
    with pytest.raises(ValueError):
        checks.pm2_pid(root, {"host": target, "executable": binary}, service)


def test_root_user_service_probe_is_read_only_and_validates_unit(monkeypatch, root):
    command = Mock(return_value="ActiveState=active\nSubState=running")
    monkeypatch.setattr(checks, "command", command)
    item = {"host": "beijing", "unit": "openclaw-gateway.service"}
    assert "active" in checks.user_service(root, item)
    assert "systemctl --user show openclaw-gateway.service" in command.call_args.args[0][-1]
    with pytest.raises(ValueError):
        checks.user_service(root, {**item, "unit": "x.service;reboot"})


def test_singapore_health_checks_real_office_tunnel(monkeypatch, root):
    command = Mock(return_value='{"status":"ok","database":"connected"}')
    monkeypatch.setattr(checks, "command", command)
    checks.cloud_health(root, "singapore", 8002)
    args = command.call_args.args[0]
    assert checks.HOSTS["singapore"] in args and args[-1].endswith("http://127.0.0.1:8002/health")
    command.return_value = '<html>SPA fallback</html>'
    with pytest.raises(ValueError):
        checks.cloud_health(root, "singapore", 8002)


@pytest.mark.parametrize("code,body,success", [(401, b'{"detail":"Not authenticated"}', True),
                                              (403, b'{"message":"Not authenticated"}', True),
                                              (502, b'bad gateway', False), (403, b'<html>WAF</html>', False)])
def test_public_api_requires_real_auth_contract(monkeypatch, code, body, success):
    error = urllib.error.HTTPError("https://example.test/api/auth/me", code, "response", {}, io.BytesIO(body))
    monkeypatch.setattr(checks.urllib.request, "urlopen", Mock(side_effect=error))
    if success:
        assert "正确拒绝匿名" in checks.public_api("leshine.work")
    else:
        with pytest.raises((RuntimeError, ValueError)):
            checks.public_api("leshine.work")


@pytest.mark.skipif(os.name != "nt", reason="Windows detached process contract")
def test_detached_fake_deploy_persists_result_and_is_idempotent(root):
    fake = root / "fake.py"
    fake.write_text('import json,os\nprint("ARK_DEPLOY_EVENT " + json.dumps(dict(protocol=1,run_id=os.environ["ARK_DESKTOP_RUN_ID"],kind="result",status="prepared",revision="' + REVISION + '")),flush=True)\n')
    (root / "deploy/deploy.bat").write_text('@echo off\n"' + sys.executable + '" "' + str(fake) + '"\nexit /b %ERRORLEVEL%\n')
    sources = {name: base64.b64encode((DEPLOY / "desktop" / (name + ".py")).read_bytes()).decode() for name in ("desktop_host", "desktop_checks")}
    request = {"run_id": RUN, "mode": "prepare"}
    host.start(root, request, sources)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = host.summarize(host.run_path(root, RUN))
        if result["status"] not in ("starting", "running"):
            break
        time.sleep(0.1)
    assert result["status"] == "prepared", result
    assert result["revision"] == REVISION
    assert not (root / ".deploy_state/desktop/active.lock").exists()
    assert host.start(root, request, sources)["status"] == "prepared"
