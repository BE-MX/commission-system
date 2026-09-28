"""Pause a registered timer and drain its oneshot without killing financial work."""
import json
from pathlib import Path
import re
import time

from publish import run
from static_sync import SSH_OPTIONS

DRAIN_SECONDS = 120


def registered_writer(service, root=None):
    """Read the candidate's exact Agent writer, never a launcher-host default."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    inventory = json.loads((root / "platforms.json").read_text(encoding="utf-8"))
    matches = [writer for writer in inventory.get("migration_writers", [])
               if writer.get("service") == service]
    if len(matches) != 1:
        raise ValueError("Agent writer registration is missing or ambiguous")
    writer = matches[0]
    if writer.get("host") != "ubuntu@154.8.205.162":
        raise ValueError("Agent writer must run on the leshine.cloud host")
    if service == "ark-okki-outbound-poller":
        if writer != {"kind": "systemd_timer", "host": writer["host"], "service": service,
                      "timer": "ark-okki-outbound-poller.timer"}:
            raise ValueError("Invalid outbound timer registration")
    elif service == "shipment-tracking-mcp":
        if (set(writer) != {"kind", "host", "service", "executable"}
                or writer.get("kind") != "pm2"
                or not re.fullmatch(r"/root/\.nvm/versions/node/v[0-9.]+/bin/pm2", writer.get("executable", ""))):
            raise ValueError("Invalid root PM2 writer registration")
    else:
        raise ValueError("Unknown Agent database writer")
    return writer


def validate(writer):
    if writer != registered_writer("ark-okki-outbound-poller"):
        raise ValueError("Unregistered timer writer")


def state(writer):
    validate(writer)
    results = []
    for unit in (writer["timer"], writer["service"] + ".service"):
        output = run(["ssh", *SSH_OPTIONS, writer["host"],
                      "systemctl show -p LoadState -p ActiveState -p MainPID " + unit], capture=True)
        info = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if info.get("LoadState") != "loaded":
            raise RuntimeError("Registered timer/service is missing")
        results.append(info)
    return results


def idle(service):
    return service.get("ActiveState") == "inactive" and service.get("MainPID") == "0"


def writer_state(writer):
    timer, service = state(writer)
    if timer.get("ActiveState") == "active":
        return "running"
    if timer.get("ActiveState") == "inactive" and idle(service):
        return "stopped"
    raise RuntimeError("Timer writer is not quiescent; no DDL permitted")


def control(writer, operation):
    timer, service = state(writer)
    if timer.get("ActiveState") not in {"active", "inactive"}:
        raise RuntimeError("Timer is not in a stable state")
    was_running = timer["ActiveState"] == "active"
    if operation == "start":
        if not was_running:
            run(["ssh", *SSH_OPTIONS, writer["host"], "sudo -n systemctl start " + writer["timer"]])
        if writer_state(writer) != "running":
            raise RuntimeError("Timer did not restart")
        return not was_running
    if operation != "stop":
        raise ValueError("Unsupported timer operation")
    if was_running:
        run(["ssh", *SSH_OPTIONS, writer["host"], "sudo -n systemctl stop " + writer["timer"]])
    deadline = time.monotonic() + DRAIN_SECONDS
    while True:
        timer, service = state(writer)
        if timer.get("ActiveState") != "inactive":
            raise RuntimeError("Timer restarted while draining; no DDL permitted")
        if idle(service):
            return was_running
        if service.get("ActiveState") == "failed" or time.monotonic() >= deadline:
            raise RuntimeError("Timer service did not drain; no DDL permitted")
        time.sleep(1)
