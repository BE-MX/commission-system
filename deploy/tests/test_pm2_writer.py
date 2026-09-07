"""PM2 inventory and targeted lifecycle checks, with SSH fully mocked."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schema_release


WRITER = {"kind": "pm2", "host": "root@119.28.107.92", "service": "shipment-tracking-mcp",
          "executable": "/root/.nvm/versions/node/v22.22.1/bin/pm2"}


def test_stops_only_registered_process(monkeypatch):
    run = Mock(side_effect=[json.dumps([
        {"name": "shipment-tracking-mcp", "pm2_env": {"status": "online"}},
        {"name": "unrelated-service", "pm2_env": {"status": "online"}},
    ]), ""])
    monkeypatch.setattr(schema_release, "run", run)
    assert schema_release.control(WRITER, "stop", "unused") is True
    command = run.call_args_list[-1].args[0][-1]
    assert command.endswith("/bin/pm2 stop shipment-tracking-mcp")
    assert command.startswith("PATH=/root/.nvm/versions/node/v22.22.1/bin:$PATH ")


def test_already_stopped_does_not_mutate_pm2(monkeypatch):
    run = Mock(return_value=json.dumps([{"name": "shipment-tracking-mcp", "pm2_env": {"status": "stopped"}}]))
    monkeypatch.setattr(schema_release, "run", run)
    assert schema_release.control(WRITER, "stop", "unused") is False
    assert run.call_count == 1


@pytest.mark.parametrize("processes", [[], [
    {"name": "shipment-tracking-mcp", "pm2_env": {"status": "online"}},
    {"name": "shipment-tracking-mcp", "pm2_env": {"status": "online"}},
]])
def test_missing_or_ambiguous_process_is_rejected(monkeypatch, processes):
    monkeypatch.setattr(schema_release, "run", Mock(return_value=json.dumps(processes)))
    with pytest.raises(RuntimeError, match="missing or ambiguous"):
        schema_release.control(WRITER, "stop", "unused")
