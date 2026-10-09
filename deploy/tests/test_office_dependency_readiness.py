"""A failed candidate install must not inherit the live environment's readiness."""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_release as office


@pytest.fixture
def dependencies(tmp_path, monkeypatch):
    live = tmp_path / "live"
    source = tmp_path / "source"
    state = tmp_path / "state"
    for root, contents in [(live, "old-dependencies"), (source, "new-dependencies")]:
        (root / "backend").mkdir(parents=True)
        (root / "backend/requirements.txt").write_text(contents)
    current_env = live / "python-env"
    (current_env / "Scripts").mkdir(parents=True)
    (current_env / "Scripts/python.exe").touch()
    (current_env / ".ark-ready").write_text("old-stamp")
    nssm = tmp_path / "nssm.exe"
    nssm.touch()
    stamp = "c" * 64
    candidate = state / "python-envs" / stamp
    calls = []
    fail = [False]

    def run(args, **_kwargs):
        args = [str(a) for a in args]
        if args[0] == str(nssm):
            return {"AppDirectory": str(live / ("backend" if args[2] == "CommissionSystem"
                                                else "services/whatsapp-connector")),
                    "Application": str(current_env / "Scripts/python.exe"),
                    "AppParameters": "-m uvicorn app.main:app --port 8001"}[args[3]]
        if args[-1] == "--version":
            return "Python 3.12"
        if args[-1] == "import sys;print(sys.prefix)":
            return str(candidate)
        if "pip" in args:
            calls.append(args[3])
            if args[3] == "install" and fail[0]:
                raise RuntimeError("package unavailable")
        return ""

    monkeypatch.setattr(office, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(office.shutil, "which", lambda _name: str(nssm))
    monkeypatch.setattr(office, "ROOT", source)
    monkeypatch.setattr(office, "STATE", state)
    monkeypatch.setattr(office, "input_digest", lambda *_args: stamp)
    monkeypatch.setattr(office, "run", run)
    monkeypatch.setattr(office, "health", Mock())
    monkeypatch.setattr(office, "schema_check", lambda *_args, **_kwargs: {"schema": "175", "pending": []})
    return SimpleNamespace(live=live, candidate=candidate, stamp=stamp, calls=calls, fail=fail)


def prepare(data):
    return office.prepare(data.live, "a" * 40, "b" * 40)


def test_failed_clone_install_retries_and_writes_only_current_stamp(dependencies):
    data = dependencies
    data.fail[0] = True
    with pytest.raises(RuntimeError, match="package unavailable"):
        prepare(data)
    assert not (data.candidate / ".ark-ready").exists()
    data.fail[0] = False
    prepare(data)
    assert data.calls == ["install", "install", "check"]
    assert (data.candidate / ".ark-ready").read_text() == data.stamp


@pytest.mark.parametrize("stored, installs", [("old-stamp", True), ("c" * 64, False)])
def test_only_matching_ready_stamp_can_skip_dependency_install(dependencies, stored, installs):
    data = dependencies
    data.candidate.mkdir(parents=True)
    (data.candidate / "Scripts").mkdir()
    (data.candidate / "Scripts/python.exe").touch()
    (data.candidate / ".ark-ready").write_text(stored)
    prepare(data)
    assert data.calls == (["install", "check"] if installs else [])
