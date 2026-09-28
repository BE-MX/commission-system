"""PM2 inventory and targeted lifecycle checks, with SSH fully mocked."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schema_release


WRITER = {"kind": "pm2", "host": "ubuntu@154.8.205.162", "service": "shipment-tracking-mcp",
          "executable": "/root/.nvm/versions/node/v22.22.1/bin/pm2"}


def test_known_pm2_writer_cannot_be_omitted_from_verified_inventory():
    inventory = {"migration_writers_verified": True, "migration_writers": [
        {"kind": "nssm", "host": "office", "service": "CommissionSystem"},
        {"kind": "nssm", "host": "office", "service": "WhatsAppConnector"},
        {"kind": "systemd", "host": "ubuntu@154.8.205.162", "service": "ark-backend"},
    ]}
    with pytest.raises(ValueError, match="Required application writers"):
        schema_release.validate(inventory, ["139_expo_prompt_versions"])
    inventory["migration_writers"].append(WRITER)
    assert schema_release.validate(inventory, ["139_expo_prompt_versions"]) == inventory["migration_writers"]


def test_stops_only_registered_process(monkeypatch):
    run = Mock(side_effect=[json.dumps([
        {"name": "shipment-tracking-mcp", "pm2_env": {"status": "online"}},
        {"name": "unrelated-service", "pm2_env": {"status": "online"}},
    ]), "", json.dumps([
        {"name": "shipment-tracking-mcp", "pm2_env": {"status": "stopped"}},
    ])])
    monkeypatch.setattr(schema_release, "run", run)
    assert schema_release.control(WRITER, "stop", "unused") is True
    command = run.call_args_list[1].args[0][-1]
    assert command.endswith("/bin/pm2 stop shipment-tracking-mcp")
    assert command.startswith("sudo -n -H -u root env HOME=/root PM2_HOME=/root/.pm2 PATH=/root/.nvm/versions/node/v22.22.1/bin:")
    assert all(call.args[0][-2] == "ubuntu@154.8.205.162" for call in run.call_args_list)


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


def test_stop_must_be_verified_before_reporting_success(monkeypatch):
    online = json.dumps([{"name": WRITER["service"], "pm2_env": {"status": "online"}}])
    monkeypatch.setattr(schema_release, "run", Mock(side_effect=[online, "", online]))
    with pytest.raises(RuntimeError, match="did not reach stopped"):
        schema_release.control(WRITER, "stop", "unused")


def test_start_must_be_verified_before_reporting_success(monkeypatch):
    stopped = json.dumps([{"name": WRITER["service"], "pm2_env": {"status": "stopped"}}])
    monkeypatch.setattr(schema_release, "run", Mock(side_effect=[stopped, "", stopped]))
    with pytest.raises(RuntimeError, match="did not reach running"):
        schema_release.control(WRITER, "start", "unused")


@pytest.mark.parametrize("change", [{"host": "root@119.28.107.92"},
                                   {"executable": "/home/ubuntu/.nvm/versions/node/v22.22.1/bin/pm2"}])
def test_wrong_host_or_pm2_owner_rejected(change):
    inventory = json.loads((Path(__file__).resolve().parents[1] / "platforms.json").read_text())
    inventory["migration_writers_verified"] = True
    inventory["migration_writers"] = [{**writer, **change} if writer["kind"] == "pm2" else writer
                                      for writer in inventory["migration_writers"]]
    with pytest.raises(ValueError, match="Unregistered PM2"):
        schema_release.validate(inventory, ["139_expo_prompt_versions"])
