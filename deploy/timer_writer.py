"""Pause a registered timer and drain its oneshot without killing financial work."""
import time

from publish import run
from static_sync import SSH_OPTIONS

WRITER = {"kind": "systemd_timer", "host": "root@119.28.107.92",
          "service": "ark-okki-outbound-poller", "timer": "ark-okki-outbound-poller.timer"}
DRAIN_SECONDS = 120


def validate(writer):
    if writer != WRITER:
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
            run(["ssh", *SSH_OPTIONS, writer["host"], "systemctl start " + writer["timer"]])
        if writer_state(writer) != "running":
            raise RuntimeError("Timer did not restart")
        return not was_running
    if operation != "stop":
        raise ValueError("Unsupported timer operation")
    if was_running:
        run(["ssh", *SSH_OPTIONS, writer["host"], "systemctl stop " + writer["timer"]])
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
