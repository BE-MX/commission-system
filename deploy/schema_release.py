"""Single shared-schema coordinator; validate writers and DBA access before stopping."""

import json
from pathlib import Path
import re
import subprocess

from publish import ROOT, STATE, atomic_json, run
from static_sync import SSH_OPTIONS
from remote_backend import database_lock, schema_check


def validate(inventory, pending):
    if not pending:
        return []
    writers = inventory.get("migration_writers", [])
    if not inventory.get("migration_writers_verified") or not writers:
        raise RuntimeError("Database migration pending: verify every office/cloud writer in deploy/platforms.json first; no services stopped and no DDL executed")
    for writer in writers:
        if writer.get("kind") not in {"nssm", "systemd"} or not re.fullmatch(r"[A-Za-z0-9_-]+", writer.get("service", "")):
            raise ValueError("Invalid registered database writer")
        if writer["kind"] == "systemd" and writer.get("host") not in {"ubuntu@154.8.205.162", "root@119.28.107.92"}:
            raise ValueError("Unregistered writer host")
        if writer["kind"] == "nssm" and writer.get("host") != "office":
            raise ValueError("NSSM writer must belong to the office host")
    required = {("nssm", "office", "CommissionSystem"), ("nssm", "office", "WhatsAppConnector"), ("systemd", "ubuntu@154.8.205.162", "ark-backend")}
    if not required.issubset({(w["kind"],w.get("host"),w["service"]) for w in writers}):
        raise ValueError("Required application writers missing from migration inventory")
    return writers


def control(writer, operation, nssm):
    if writer["kind"] == "nssm":
        state = run([nssm, "status", writer["service"]], capture=True)
        if (operation == "stop" and state == "SERVICE_STOPPED") or (operation == "start" and state == "SERVICE_RUNNING"):
            return False
        run([nssm, operation, writer["service"]])
    else:
        output = run(["ssh", *SSH_OPTIONS, writer["host"], "systemctl show -p LoadState -p ActiveState " + writer["service"]], capture=True)
        state = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if state.get("LoadState") != "loaded":
            raise RuntimeError("Registered writer service is missing")
        if operation == "stop" and state.get("ActiveState") in {"inactive", "failed"}:
            return False
        if operation == "start" and state.get("ActiveState") == "active":
            return False
        run(["ssh", *SSH_OPTIONS, writer["host"], "sudo -n systemctl " + operation + " " + writer["service"]])
    return True


def invoke(prepared, writers, credential_file, action):
    if not credential_file or not Path(credential_file).is_file():
        raise RuntimeError("Pending DDL requires --migration-credentials with a protected DBA file; runtime .env is never modified")
    request = {"action": action, "writers": writers, "nssm": prepared["nssm"], "credential_file": str(Path(credential_file).resolve())}
    result = subprocess.run([str(prepared["python"]), str(ROOT / "deploy/migration_runner.py")],
        cwd=ROOT / "backend", input=json.dumps(request), text=True, capture_output=True, timeout=1200)
    if result.returncode:
        raise RuntimeError("Migration " + action + " failed; inspect DBA access and schema state locally. Writer restart is withheld if DDL began.")
    return json.loads(result.stdout.splitlines()[-1])


def preflight(prepared, inventory, credential_file):
    writers = validate(inventory, prepared["pending"])
    if writers:
        invoke(prepared, writers, credential_file, "check")


def migrate(prepared, inventory, credential_file=None):
    writers = validate(inventory, prepared["pending"])
    if not writers:
        return []
    atomic_json(STATE / "schema-current.json", {"status": "migrating", "pending": prepared["pending"]})
    try:
        result = invoke(prepared, writers, credential_file, "apply")
    except Exception:
        atomic_json(STATE / "schema-current.json", {"status": "failed-inspect-before-restart", "pending": prepared["pending"]})
        raise
    atomic_json(STATE / "schema-current.json", {"status": "upgraded", "schema": result["schema"]})
    prepared["schema_changed"] = True
    return result["stopped"]


def resume_external(writers, prepared):
    owned = {("nssm", "office", "CommissionSystem"), ("nssm", "office", "WhatsAppConnector"), ("systemd", "ubuntu@154.8.205.162", "ark-backend")}
    with database_lock(ROOT, prepared["python"]):
        schema_check(ROOT, prepared["python"])
        for writer in writers:
            if (writer["kind"], writer.get("host"), writer["service"]) not in owned:
                control(writer, "start", prepared["nssm"])
