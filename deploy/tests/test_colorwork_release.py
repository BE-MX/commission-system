"""Release guards for the internal module; only temporary stores and fake commands."""
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import colorwork_release as release


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    source = tmp_path / ".deploy_state/checkouts" / ("a" * 40)
    folder = source / "colorwork-workbench"
    (folder / "drizzle").mkdir(parents=True)
    (folder / "drizzle/0000.sql").write_text("CREATE TABLE sample (id INTEGER);")
    state = tmp_path / ".deploy_state/colorwork"
    state.mkdir()
    units = tmp_path / "units"
    units.mkdir()
    monkeypatch.setattr(release, "UNIT_DIRECTORY", units)
    info = {"source": str(source), "node": "/usr/bin/node", "migrations": release.migration_files(folder),
            "unit": str(state / "candidate.service"), "status": "prepared"}
    (state / "candidate.service").write_text(release.MANAGED)
    (state / ("prepared-" + source.name + ".json")).write_text(json.dumps(info))
    monkeypatch.setattr(release, "healthy", Mock())
    return tmp_path, source, state, folder, info


def test_source_must_be_inside_prepared_checkout(tmp_path):
    with pytest.raises(ValueError):
        release.paths(tmp_path, tmp_path / "other")


def test_unknown_sqlite_migration_blocks_downgrade(tmp_path):
    with sqlite3.connect(tmp_path / "test.sqlite") as db:
        db.execute("CREATE TABLE d1_migrations(name TEXT)")
        db.execute("INSERT INTO d1_migrations VALUES ('future.sql')")
    with pytest.raises(RuntimeError, match="unknown"):
        release.verify_history(tmp_path, {"0000.sql": "digest"})


def test_stale_prepared_candidate_rechecks_latest_migration_checksum(candidate, monkeypatch):
    root, source, state, folder, info = candidate
    (state / "success.json").write_text(json.dumps({"migrations": {"0000.sql": "already-applied-other-content"}}))
    command = Mock()
    monkeypatch.setattr(release, "run", command)
    with pytest.raises(RuntimeError, match="changed"):
        release.activate(root, source)
    command.assert_not_called()
    assert not (state / "current.json").exists()


def test_repeat_success_is_noop_and_does_not_reuse_old_backup(candidate, monkeypatch):
    root, source, state, _, info = candidate
    (state / "success.json").write_text(json.dumps({**info, "status": "succeeded"}))
    command = Mock()
    monkeypatch.setattr(release, "run", command)
    assert release.activate(root, source)["status"] == "unchanged"
    command.assert_not_called()
    release.healthy.assert_called_once()


def test_failed_journal_blocks_retry_without_overwriting_evidence(candidate, monkeypatch):
    root, source, state, _, info = candidate
    original = json.dumps({**info, "status": "failed", "evidence": "preserve"})
    (state / "current.json").write_text(original)
    command = Mock()
    monkeypatch.setattr(release, "run", command)
    with pytest.raises(RuntimeError, match="recovery"):
        release.activate(root, source)
    assert (state / "current.json").read_text() == original
    command.assert_not_called()


def test_activation_stops_then_backs_up_data_before_migration(candidate, monkeypatch):
    root, source, state, folder, info = candidate
    data = state / "data"
    data.mkdir()
    (data / "retained-blob").write_bytes(b"user asset")
    (release.UNIT_DIRECTORY / (release.SERVICE + ".service")).write_text(release.MANAGED)
    commands = []

    def command(args, cwd, capture=False):
        commands.append([str(a) for a in args])
        if "migrations" in args:
            backup = Path(json.loads((state / "current.json").read_text())["backup"])
            assert (backup / "retained-blob").read_bytes() == b"user asset"
            assert commands[0][-2:] == ["stop", release.SERVICE]
        return ""

    monkeypatch.setattr(release, "run", command)
    assert release.activate(root, source)["status"] == "updated"
    assert (data / "retained-blob").read_bytes() == b"user asset"
    assert json.loads((state / "success.json").read_text())["status"] == "succeeded"


def test_returning_to_older_candidate_uses_new_backup(candidate, monkeypatch):
    root, source, state, _, info = candidate
    data = state / "data"
    data.mkdir()
    (data / "new-file").write_bytes(b"new user data")
    old = state / "backups" / source.name
    old.mkdir(parents=True)
    (old / "old-file").write_bytes(b"old data")
    (state / "success.json").write_text(json.dumps({**info, "source": str(source.parent / ("b" * 40))}))
    monkeypatch.setattr(release, "run", Mock(return_value=""))
    release.activate(root, source)
    latest = json.loads((state / "success.json").read_text())
    assert Path(latest["backup"]) != old
    assert (Path(latest["backup"]) / "new-file").read_bytes() == b"new user data"


def test_unit_has_no_public_listener_or_secret():
    unit = release.unit_text(Path('/candidate/workbench'), Path('/state'), '/usr/bin/node', 'ubuntu')
    assert "--ip 127.0.0.1 --port 8787" in unit
    assert "User=ubuntu" in unit and "KillMode=control-group" in unit
    assert "ARK_SSO_SECRET" not in unit
    with pytest.raises(ValueError):
        release.unit_text(Path('/candidate'), Path('/state'), '/usr/bin/node', 'ubuntu\nUser=root')


def test_prepare_only_never_uses_live_store_and_repeat_does_not_rebuild(candidate, monkeypatch):
    root, source, state, folder, _ = candidate
    commands = []
    monkeypatch.setattr(release, "ensure_node", lambda _: "/managed/bin/node")

    def command(args, cwd, capture=False):
        args = [str(a) for a in args]
        commands.append(args)
        if args[-1] == "--version":
            return release.NODE_VERSION
        if args[-1] == "build":
            output = folder / "dist/server/index.js"
            output.parent.mkdir(parents=True)
            output.write_text("built code")
        if args[:2] == ["id", "-un"]:
            return "ubuntu"
        return ""

    monkeypatch.setattr(release, "run", command)
    release.prepare(root, source, "/python")
    release.prepare(root, source, "/python")
    assert sum(cmd[-1] == "build" for cmd in commands) == 1
    migrations = [cmd for cmd in commands if "migrations" in cmd]
    assert all(str(state / "validation" / source.name) == cmd[-1] for cmd in migrations)
    assert not any("systemctl" in cmd for cmd in commands)
    assert not (state / "data").exists()


def test_downloaded_node_archive_must_match_pinned_digest(tmp_path, monkeypatch):
    runtimes = tmp_path / "runtimes"
    runtimes.mkdir()
    (runtimes / f"node-{release.NODE_VERSION}-linux-x64.tar.xz").write_bytes(b"untrusted content")
    monkeypatch.setattr(release.platform, "system", lambda: "Linux")
    monkeypatch.setattr(release.platform, "machine", lambda: "x86_64")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        release.ensure_node(tmp_path)
    assert not (runtimes / f"node-{release.NODE_VERSION}-linux-x64").exists()
