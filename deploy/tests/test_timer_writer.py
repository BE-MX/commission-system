"""Timer migration safety with no SSH or database effects."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import schema_release
import timer_writer as timer


WRITER = {"kind": "systemd_timer", "host": "ubuntu@154.8.205.162",
          "service": "ark-okki-outbound-poller", "timer": "ark-okki-outbound-poller.timer"}


def pair(active=True, busy=False):
    return [{"ActiveState": "active" if active else "inactive"},
            {"ActiveState": "activating" if busy else "inactive", "MainPID": "12" if busy else "0"}]


def test_stop_drains_without_killing_service(monkeypatch):
    monkeypatch.setattr(timer, "state", Mock(side_effect=[pair(), pair(False, True), pair(False)]))
    command = Mock(); monkeypatch.setattr(timer, "run", command)
    monkeypatch.setattr(timer.time, "sleep", Mock())
    assert timer.control(WRITER, "stop") is True
    assert command.call_count == 1
    assert command.call_args.args[0][-1] == "sudo -n systemctl stop ark-okki-outbound-poller.timer"


def test_drain_timeout_blocks_and_allows_baseline_timer_restore(monkeypatch):
    monkeypatch.setattr(timer, "state", Mock(side_effect=[pair(), pair(False, True), pair(False, True), pair(True, True)]))
    monkeypatch.setattr(timer, "DRAIN_SECONDS", 0)
    command = Mock(); monkeypatch.setattr(timer, "run", command)
    with pytest.raises(RuntimeError, match="no DDL"):
        timer.control(WRITER, "stop")
    assert timer.control(WRITER, "start") is True
    assert [c.args[0][-1] for c in command.call_args_list] == [
        "sudo -n systemctl stop ark-okki-outbound-poller.timer", "sudo -n systemctl start ark-okki-outbound-poller.timer"]


def test_inactive_schedule_is_not_resumed(monkeypatch):
    monkeypatch.setattr(timer, "state", Mock(return_value=pair(False)))
    command = Mock(); monkeypatch.setattr(timer, "run", command)
    assert timer.control(WRITER, "stop") is False
    command.assert_not_called()


@pytest.mark.parametrize("status,pid", [("activating", "20"), ("inactive", "20"), ("failed", "0")])
def test_stopped_requires_no_inflight_process(monkeypatch, status, pid):
    monkeypatch.setattr(timer, "state", lambda _: [{"ActiveState": "inactive"}, {"ActiveState": status, "MainPID": pid}])
    with pytest.raises(RuntimeError, match="no DDL"):
        schema_release.writer_state(WRITER, "unused")


def test_missing_unit_and_unregistered_target_fail_closed(monkeypatch):
    monkeypatch.setattr(timer, "run", Mock(return_value="LoadState=not-found\nActiveState=inactive"))
    with pytest.raises(RuntimeError, match="missing"):
        timer.state(WRITER)
    with pytest.raises(ValueError):
        timer.state({**WRITER, "timer": "other.timer"})


def test_inventory_requires_registered_external_writer():
    inventory = json.loads((Path(__file__).resolve().parents[1] / "platforms.json").read_text())
    inventory["migration_writers_verified"] = True
    inventory["migration_writers"] = [w for w in inventory["migration_writers"] if w["kind"] != "systemd_timer"]
    with pytest.raises(ValueError, match="timer writer missing"):
        schema_release.validate(inventory, ["155_announcements"])
    inventory["migration_writers"].append(WRITER)
    assert schema_release.validate(inventory, ["155_announcements"]) == inventory["migration_writers"]


@pytest.mark.parametrize("writers", [[], [WRITER, WRITER], [{**WRITER, "host": "root@119.28.107.92"}],
                                    [{**WRITER, "timer": "other.timer"}]])
def test_invalid_candidate_registration_is_rejected(tmp_path, writers):
    (tmp_path / "platforms.json").write_text(json.dumps({"migration_writers": writers}))
    with pytest.raises(ValueError):
        timer.registered_writer("ark-okki-outbound-poller", tmp_path)


def test_uses_candidate_registration(tmp_path):
    (tmp_path / "platforms.json").write_text(json.dumps({"migration_writers": [WRITER]}))
    assert timer.registered_writer("ark-okki-outbound-poller", tmp_path) == WRITER
