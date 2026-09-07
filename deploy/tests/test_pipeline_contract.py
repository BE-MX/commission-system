"""Release contracts formerly asserted against BAT text; all effects are local/mocked."""

from contextlib import nullcontext
import base64
import json
from pathlib import Path
import sys
import subprocess
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import cloud_backend
import office_release
import publish
import schema_release
import source_release
import static_sync


def test_static_archive_includes_nested_public_artifacts_and_uses_ssh_retries(tmp_path, monkeypatch):
    source = tmp_path / "dist"
    for name in ["index.html", "festival/index.html", "downloads/extension.zip"]:
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(name)
    files = static_sync.manifest(source)
    remote = Mock(side_effect=[{"missing": list(files), "initialized": False,
                               "active_artifact": None, "artifact": "a" * 64}, {}])
    monkeypatch.setattr(static_sync, "remote", remote)
    command = Mock()
    monkeypatch.setattr(static_sync, "run", command)
    static_sync.prepare(source, "example.test", "/registered", tmp_path / "state", "example.test")
    args = command.call_args.args[0]
    assert args[:1] == ["scp"]
    assert ["-o", "ConnectionAttempts=3"] == args[args.index("ConnectionAttempts=3") - 1:args.index("ConnectionAttempts=3") + 1]
    assert "BatchMode=yes" in args and "StrictHostKeyChecking=yes" in args
    with tarfile.open(args[-2]) as archive:
        assert set(archive.getnames()) == set(files)
    assert remote.call_args.args[1]["action"] == "stage"


def test_remote_command_is_ascii_and_passes_payload_on_stdin(monkeypatch):
    command = Mock(return_value=subprocess.CompletedProcess([], 0, '{}', ''))
    monkeypatch.setattr(static_sync.subprocess, "run", command)
    payload = {"action": "plan", "host": "测试"}
    static_sync.remote("example.test", payload)
    args = command.call_args.args[0]
    assert args[0] == "ssh" and "ConnectionAttempts=3" in args
    assert args[-1].isascii()
    code, request = command.call_args.kwargs["input"].split("\n", 1)
    assert base64.b64decode(code) == (static_sync.HERE / "remote_static.py").read_bytes()
    assert json.loads(request) == payload


def test_backend_uses_streamed_script_and_rejects_remote_failure(monkeypatch):
    command = Mock(return_value=subprocess.CompletedProcess([], 0, '{}', ''))
    monkeypatch.setattr(static_sync.subprocess, "run", command)
    request = {"action": "prepare", "revision": "a" * 40}
    assert cloud_backend.invoke(request) == {}
    args = command.call_args.args[0]
    assert args[-1].startswith("python3 -c ") and len(args[-1]) < 200
    code, payload = command.call_args.kwargs["input"].split("\n", 1)
    assert base64.b64decode(code) == (static_sync.HERE / "remote_backend.py").read_bytes()
    assert json.loads(payload) == request
    assert command.call_args.kwargs["timeout"] == 1200
    command.return_value = subprocess.CompletedProcess([], 1, '', 'probe failure')
    with pytest.raises(RuntimeError, match="probe failure"):
        cloud_backend.invoke(request)


def test_unchanged_static_does_not_upload(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("ready")
    monkeypatch.setattr(static_sync, "remote", Mock(return_value={
        "missing": [], "initialized": True, "active_artifact": "same", "artifact": "same"}))
    command = Mock()
    monkeypatch.setattr(static_sync, "run", command)
    assert static_sync.prepare(tmp_path, "example.test", "/registered", tmp_path / "state", "example.test")["bytes"] == 0
    command.assert_not_called()


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy/platforms.json").write_text(json.dumps({
        "static_targets": [{"component": "frontend", "host": "example.test", "root": "/registered", "domain": "example.test"}],
        "pending_targets": [],
    }))
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(publish, "ROOT", tmp_path)
    monkeypatch.setattr(publish, "STATE", state)
    monkeypatch.setattr(schema_release, "STATE", state)
    monkeypatch.setattr(publish, "deployment_lock", nullcontext)
    monkeypatch.setattr(source_release, "prepare", Mock(return_value=(tmp_path, "new", "old")))
    office = {"python": "isolated-python", "pending": []}
    prepare = Mock(return_value=office)
    monkeypatch.setattr(office_release, "prepare", prepare)
    monkeypatch.setattr(office_release, "stage_static", Mock())
    office_activate = Mock(return_value={})
    monkeypatch.setattr(office_release, "activate", office_activate)
    monkeypatch.setattr(schema_release, "preflight", Mock())
    monkeypatch.setattr(schema_release, "migrate", Mock(return_value=[]))
    monkeypatch.setattr(schema_release, "database_lock", lambda *_: nullcontext())
    monkeypatch.setattr(schema_release, "schema_check", Mock())
    monkeypatch.setattr(publish, "build_frontends", Mock(return_value={"frontend": tmp_path / "dist"}))
    monkeypatch.setattr(publish, "build_lan", Mock(return_value=tmp_path / "lan"))
    monkeypatch.setattr(cloud_backend, "prepare", Mock(return_value={"schema": "head"}))
    monkeypatch.setattr(cloud_backend, "activate", Mock(return_value={}))
    monkeypatch.setattr(static_sync, "prepare", Mock(return_value={"target": "example.test", "request": {"root": "/registered"}, "bytes": 0}))
    activate = Mock(return_value={})
    monkeypatch.setattr(static_sync, "activate", activate)
    command = Mock()
    monkeypatch.setattr(publish, "run", command)
    return SimpleNamespace(args=SimpleNamespace(no_pull=True, cloud_only=False, migration_credentials=None, prepare_only=False, revision=None),
                           state=state, prepare=prepare, activate=activate, office_activate=office_activate, command=command)


def test_publish_preserves_pantone_seed_and_only_marks_success_after_activation(pipeline):
    publish.publish(pipeline.args)
    assert ["isolated-python", "scripts/import_pantone.py"] in [c.args[0] for c in pipeline.command.call_args_list]
    pipeline.activate.assert_called_once()
    assert json.loads((pipeline.state / "publish-success.json").read_text())["revision"] == "new"


def test_failed_static_activation_never_advances_success_marker(pipeline):
    pipeline.activate.side_effect = RuntimeError("activation failed")
    with pytest.raises(RuntimeError, match="activation failed"):
        publish.publish(pipeline.args)
    assert not (pipeline.state / "publish-success.json").exists()


def test_office_preflight_failure_prevents_all_activation(pipeline):
    pipeline.prepare.side_effect = RuntimeError("preflight failed")
    with pytest.raises(RuntimeError, match="preflight failed"):
        publish.publish(pipeline.args)
    pipeline.activate.assert_not_called()
    pipeline.office_activate.assert_not_called()
    pipeline.command.assert_not_called()
    schema_release.migrate.assert_not_called()


def test_prepare_only_never_stops_or_activates_writers(pipeline):
    pipeline.args.prepare_only = True
    publish.publish(pipeline.args)
    pipeline.activate.assert_not_called()
    pipeline.office_activate.assert_not_called()
    schema_release.migrate.assert_not_called()
    assert not (pipeline.state / "publish-success.json").exists()
    assert json.loads((pipeline.state / "publish-current.json").read_text())["status"] == "prepared"


def test_render_preflight_runs_as_module_before_connector_or_activation():
    # This invocation contract complements the executable failure boundary above.
    import inspect
    source = inspect.getsource(office_release.prepare)
    assert '[python, "-m", "scripts.check_design_image_document_render"]' in source
    assert source.index('schema_check(') < source.index('scripts.check_design_image_document_render') < source.index('connector_changed =')


@pytest.mark.parametrize("failure", ["chain", "stop", "partial-stop", "stop-not-verified", "ddl", "verification"])
def test_migration_failure_preserves_writer_boundary(failure, monkeypatch, tmp_path):
    import migration_runner
    from alembic import command
    from alembic.script import ScriptDirectory
    import app.core.config as config
    import dotenv
    import sqlalchemy

    runtime = config.get_settings()
    monkeypatch.setattr(dotenv, "dotenv_values", lambda _: {"COMMISSION_DB_USER": "isolated-dba", "COMMISSION_DB_PASSWORD": "test-only"})
    connection = Mock()
    def execute(sql):
        value = str(sql)
        result = Mock()
        if value == "SHOW GRANTS":
            result.scalars.return_value = ["GRANT ALL PRIVILEGES ON *.* TO isolated"]
        elif "GET_LOCK" in value:
            result.scalar.return_value = 1
        elif "version_num" in value:
            result.scalars.return_value = ["wrong"]
        return result
    connection.execute.side_effect = execute
    engine = Mock()
    engine.connect.return_value = nullcontext(connection)
    monkeypatch.setattr(sqlalchemy, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(config, "get_settings", lambda: runtime)
    states = {"first": "running", "second": "running", "inactive": "stopped"}
    journal = tmp_path / "schema-writers.json"
    def control_writer(writer, operation, _nssm):
        # The baseline must survive even a stop command with an uncertain outcome.
        assert json.loads(journal.read_text())["writers"][0]["before"] == "running"
        previous = states[writer["id"]]
        if not (failure == "stop-not-verified" and operation == "stop" and writer["id"] == "first"):
            states[writer["id"]] = "stopped" if operation == "stop" else "running"
        if operation == "stop" and (failure == "stop" or (failure == "partial-stop" and writer["id"] == "second")):
            raise RuntimeError("stop")
        return states[writer["id"]] != previous
    control = Mock(side_effect=control_writer)
    monkeypatch.setattr(schema_release, "control", control)
    monkeypatch.setattr(schema_release, "writer_state", lambda w, _: states[w["id"]])
    upgrade = Mock(side_effect=RuntimeError("ddl") if failure == "ddl" else None)
    monkeypatch.setattr(command, "upgrade", upgrade)
    monkeypatch.setattr(ScriptDirectory, "from_config", Mock(return_value=SimpleNamespace(
        get_heads=lambda: ["head"], iterate_revisions=lambda *_: [] if failure == "chain" else [SimpleNamespace(revision="head")])))
    with pytest.raises(RuntimeError):
        migration_runner.execute({"credential_file": "unused", "action": "apply",
                                  "journal_path": str(journal),
                                  "schema": "head", "pending": ["head"],
                                  "writers": [{"id": "first"}, {"id": "second"}, {"id": "inactive"}], "nssm": "mock"})
    restarted = [call.args[0]["id"] for call in control.call_args_list if call.args[1] == "start"]
    assert "inactive" not in restarted
    before_ddl = failure in ("chain", "stop", "partial-stop", "stop-not-verified")
    assert states == {"first": "running" if before_ddl else "stopped",
                      "second": "running" if before_ddl else "stopped", "inactive": "stopped"}
    assert json.loads(journal.read_text())["status"] == ("restored-before-ddl" if before_ddl else "failed-after-ddl")
    if not before_ddl:
        assert restarted == []
    assert upgrade.call_count == (0 if before_ddl else 1)
    if failure == "chain":
        control.assert_not_called()
    assert any("RELEASE_LOCK" in str(call.args[0]) for call in connection.execute.call_args_list)


@pytest.mark.parametrize("phase", ["stopping", "running-ddl", "failed-after-ddl", "recovery-required", "upgraded"])
def test_incomplete_migration_blocks_retry_before_credentials_or_writer_changes(phase, tmp_path, monkeypatch):
    import dotenv
    import migration_runner
    journal = tmp_path / "schema-writers.json"
    journal.write_text(json.dumps({"status": phase}))
    credentials = Mock()
    monkeypatch.setattr(dotenv, "dotenv_values", credentials)
    control = Mock()
    monkeypatch.setattr(schema_release, "control", control)
    with pytest.raises(RuntimeError, match="requires inspection"):
        migration_runner.execute({"action": "check", "journal_path": str(journal)})
    credentials.assert_not_called()
    control.assert_not_called()


@pytest.mark.parametrize("scope", ["office", "cloud-only"])
def test_database_at_head_does_not_bypass_an_unfinished_release(pipeline, scope):
    pipeline.args.cloud_only = scope == "cloud-only"
    (pipeline.state / "schema-writers.json").write_text(json.dumps({"status": "upgraded", "schema": "head"}))
    with pytest.raises(RuntimeError, match="requires inspection"):
        publish.publish(pipeline.args)
    pipeline.prepare.assert_not_called()
    pipeline.activate.assert_not_called()
    pipeline.office_activate.assert_not_called()


def test_verified_release_closes_migration_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(schema_release, "STATE", tmp_path)
    journal = tmp_path / "schema-writers.json"
    journal.write_text(json.dumps({"status": "upgraded", "schema": "head", "writers": []}))
    schema_release.complete({"schema_changed": True, "schema": "head"})
    schema_release.check_recovery()
    assert json.loads(journal.read_text())["status"] == "completed"


def test_extension_changes_rebuild_frontend_and_corrupt_cache_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "ROOT", tmp_path)
    monkeypatch.setattr(publish, "STATE", tmp_path / "state")
    (tmp_path / "state").mkdir()
    extension = tmp_path / "extensions/whatsapp-translation"
    extension.mkdir(parents=True)
    source = extension / "source.js"
    source.write_text("v1")
    (tmp_path / "frontend-pm").mkdir()
    monkeypatch.setattr(publish, "npm_install", Mock())
    monkeypatch.setattr(publish, "npm_command", lambda: "mock-npm")
    def run(args, **kwargs):
        if args[0] == "node":
            return "test-node"
        output = Path(args[-1])
        output.mkdir(parents=True, exist_ok=True)
        (output / ("latest.json" if "package" in args else "index.html")).write_text(source.read_text())
        return ""
    command = Mock(side_effect=run)
    monkeypatch.setattr(publish, "run", command)
    first = publish.build_frontends()
    command.reset_mock()
    assert publish.build_frontends() == first
    assert not any("build" in c.args[0] for c in command.call_args_list)
    source.write_text("v2")
    second = publish.build_frontends()
    assert first["frontend"] != second["frontend"]
    package = next((tmp_path / "state/builds").glob("extension-" + publish.marker("extension")["digest"]))
    (package / "latest.json").write_text("corrupt")
    with pytest.raises(RuntimeError, match="corrupt"):
        publish.build_frontends()
