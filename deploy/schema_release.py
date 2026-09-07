"""Single shared-schema coordinator; validate writers and DBA access before stopping."""

import json
from pathlib import Path
import re
import shlex
import subprocess

from publish import ROOT, STATE, atomic_json, run
from static_sync import SSH_OPTIONS
from remote_backend import database_lock, schema_check


def check_recovery(path=None):
    journal = Path(path) if path else STATE / "schema-writers.json"
    if journal.exists():
        previous = json.loads(journal.read_text(encoding="utf-8"))
        if previous.get("status") not in {"completed", "restored-before-ddl"}:
            raise RuntimeError("Previous migration requires inspection before retrying: " + str(journal))


def complete(prepared):
    if prepared.get("schema_changed"):
        journal = STATE / "schema-writers.json"
        record = json.loads(journal.read_text(encoding="utf-8"))
        if record.get("status") != "upgraded" or record.get("schema") != prepared["schema"]:
            raise RuntimeError("Migration journal does not match the verified release")
        record["status"] = "completed"
        atomic_json(journal, record)


def validate(inventory, pending):
    if not pending:
        return []
    writers = inventory.get("migration_writers", [])
    if not inventory.get("migration_writers_verified") or not writers:
        raise RuntimeError("Database migration pending: verify every office/cloud writer in deploy/platforms.json first; no services stopped and no DDL executed")
    for writer in writers:
        if writer.get("kind") not in {"nssm", "systemd", "pm2"} or not re.fullmatch(r"[A-Za-z0-9_-]+", writer.get("service", "")):
            raise ValueError("Invalid registered database writer")
        if writer["kind"] == "systemd" and writer.get("host") not in {"ubuntu@154.8.205.162", "root@119.28.107.92"}:
            raise ValueError("Unregistered writer host")
        if writer["kind"] == "nssm" and writer.get("host") != "office":
            raise ValueError("NSSM writer must belong to the office host")
        if writer["kind"] == "pm2":
            if writer.get("host") != "root@119.28.107.92" or not re.fullmatch(r"/root/\.nvm/versions/node/v[0-9.]+/bin/pm2", writer.get("executable", "")):
                raise ValueError("Unregistered PM2 writer executable or host")
    required = {("nssm", "office", "CommissionSystem"), ("nssm", "office", "WhatsAppConnector"),
                ("systemd", "ubuntu@154.8.205.162", "ark-backend"),
                ("pm2", "root@119.28.107.92", "shipment-tracking-mcp")}
    if not required.issubset({(w["kind"],w.get("host"),w["service"]) for w in writers}):
        raise ValueError("Required application writers missing from migration inventory")
    return writers


def pm2_command(writer):
    binary = writer["executable"]
    directory = binary.rsplit("/", 1)[0]
    return "PATH=" + shlex.quote(directory) + ":$PATH " + shlex.quote(binary)


def writer_state(writer, nssm):
    if writer["kind"] == "nssm":
        state = run([nssm, "status", writer["service"]], capture=True)
        if state in {"SERVICE_RUNNING", "SERVICE_STOPPED"}:
            return "running" if state == "SERVICE_RUNNING" else "stopped"
    elif writer["kind"] == "pm2":
        # jlist contains environment values: capture and parse, never print it.
        data = json.loads(run(["ssh", *SSH_OPTIONS, writer["host"], pm2_command(writer) + " jlist"], capture=True))
        matching = [p for p in data if p.get("name") == writer["service"]]
        if len(matching) != 1:
            raise RuntimeError("Registered PM2 writer is missing or ambiguous")
        state = matching[0].get("pm2_env", {}).get("status")
        if state in {"online", "stopped"}:
            return "running" if state == "online" else "stopped"
    else:
        output = run(["ssh", *SSH_OPTIONS, writer["host"], "systemctl show -p LoadState -p ActiveState " + writer["service"]], capture=True)
        state = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        if state.get("LoadState") != "loaded":
            raise RuntimeError("Registered writer service is missing")
        if state.get("ActiveState") in {"active", "inactive"}:
            return "running" if state["ActiveState"] == "active" else "stopped"
    raise RuntimeError("Writer is not in a stable running/stopped state")


def control(writer, operation, nssm):
    if operation not in {"start", "stop"}:
        raise ValueError("Unsupported writer operation")
    state = writer_state(writer, nssm)
    if (operation == "stop" and state == "stopped") or (operation == "start" and state == "running"):
        return False
    if writer["kind"] == "nssm":
        run([nssm, operation, writer["service"]])
    elif writer["kind"] == "pm2":
        run(["ssh", *SSH_OPTIONS, writer["host"], pm2_command(writer) + " " + operation + " " + writer["service"]], capture=True)
    else:
        run(["ssh", *SSH_OPTIONS, writer["host"], "sudo -n systemctl " + operation + " " + writer["service"]])
    expected = "stopped" if operation == "stop" else "running"
    if writer_state(writer, nssm) != expected:
        raise RuntimeError("Writer did not reach " + expected + ": " + writer["service"])
    return True


def invoke(prepared, writers, credential_file, action):
    if not credential_file or not Path(credential_file).is_file():
        raise RuntimeError("Pending DDL requires --migration-credentials with a protected DBA file; runtime .env is never modified")
    request = {"action": action, "writers": writers, "nssm": str(prepared["nssm"]),
               "credential_file": str(Path(credential_file).resolve()),
               "journal_path": str(STATE / "schema-writers.json"),
               "schema": prepared["schema"], "pending": prepared["pending"]}
    runner = prepared.get("runner", ROOT / "deploy/migration_runner.py")
    result = subprocess.run([str(prepared["python"]), str(runner)],
        cwd=ROOT / "backend", input=json.dumps(request), text=True, capture_output=True, timeout=1200)
    if result.returncode:
        raise RuntimeError("Migration " + action + " failed; inspect DBA access and schema state locally. Writer restart is withheld if DDL began.")
    return json.loads(result.stdout.splitlines()[-1])


def preflight(prepared, inventory, credential_file):
    check_recovery()
    writers = validate(inventory, prepared["pending"])
    if writers:
        invoke(prepared, writers, credential_file, "check")


def migrate(prepared, inventory, credential_file=None):
    check_recovery()
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
