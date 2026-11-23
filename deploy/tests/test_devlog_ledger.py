"""Offline release ledger invocation contracts."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import devlog_ledger


@pytest.mark.parametrize("exit_code,expected", [(0, "recorded"), (1, "failed")])
def test_office_candidate_writes_with_pinned_identity(tmp_path, monkeypatch, exit_code, expected):
    run = Mock(return_value=Mock(returncode=exit_code))
    monkeypatch.setattr(devlog_ledger.subprocess, "run", run)
    result = devlog_ledger.record({"python": "office-python"}, tmp_path, "a" * 40, "rid", "office-and-cloud")
    assert result["status"] == expected
    assert run.call_args.args == (["office-python", "-m", "app.devlog.ledger_cli"],)
    args = run.call_args.kwargs
    assert args["cwd"] == tmp_path / "backend"
    assert json.loads(args["input"]) == {"revision": "a" * 40, "release_id": "rid", "scope": "office-and-cloud"}


def test_partial_release_skips_ledger(tmp_path, monkeypatch):
    run = Mock()
    monkeypatch.setattr(devlog_ledger.subprocess, "run", run)
    assert devlog_ledger.record({"python": "unused"}, tmp_path, "a" * 40, "rid", "cloud-only")["status"] == "skipped"
    run.assert_not_called()
