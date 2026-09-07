"""Default desktop deployment uses a separately provisioned local DBA file."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schema_release


@pytest.mark.parametrize("action", ["check", "apply"])
def test_no_argument_deployment_uses_live_state_credentials(tmp_path, monkeypatch, action):
    live_state = tmp_path / "live" / ".deploy_state"
    credentials = live_state / "credentials" / "migration.env"
    credentials.parent.mkdir(parents=True)
    credentials.write_text("COMMISSION_DB_USER=isolated\nCOMMISSION_DB_PASSWORD=test-only\n")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    monkeypatch.chdir(candidate)
    monkeypatch.setattr(schema_release, "STATE", live_state)
    command = Mock(return_value=SimpleNamespace(returncode=0, stdout='{"status":"ready"}'))
    monkeypatch.setattr(schema_release.subprocess, "run", command)
    prepared = {"python": "isolated-python", "nssm": "mock", "schema": "140", "pending": ["140"]}
    assert schema_release.invoke(prepared, [], None, action) == {"status": "ready"}
    request = json.loads(command.call_args.kwargs["input"])
    assert request["credential_file"] == str(credentials.resolve())
    assert request["action"] == action
    assert "test-only" not in command.call_args.kwargs["input"]


def test_explicit_credential_path_is_never_silently_replaced(tmp_path, monkeypatch):
    credentials = tmp_path / "credentials" / "migration.env"
    credentials.parent.mkdir()
    credentials.write_text("default")
    monkeypatch.setattr(schema_release, "STATE", tmp_path)
    with pytest.raises(RuntimeError, match="credential"):
        schema_release.invoke({}, [], str(tmp_path / "missing.env"), "check")


def test_missing_default_reports_the_provisioning_path(tmp_path, monkeypatch):
    monkeypatch.setattr(schema_release, "STATE", tmp_path)
    with pytest.raises(RuntimeError, match="credentials.*migration.env"):
        schema_release.invoke({}, [], None, "check")
