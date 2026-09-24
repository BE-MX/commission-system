"""Repair the 164 -> 166 -> 167 schema gap without publishing application code."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import time

import publish
import schema_release
from office_release import health
from static_sync import SSH_OPTIONS

PARENT = "164_battle_posters"
TARGET = "167_invoice_merchandiser"
PENDING = ["166_presale_settlement", TARGET]
MIGRATIONS = {
    "166_presale_settlement.py": "ab2211b9188087a2fd9a2eeffea1d75af7350b8029b9455b0896dbfca290cc93",
    "167_invoice_merchandiser.py": "ef393948c17b55814f74b7b9c00641329b314cdfbde4be0ee60b73bcc357ca18",
}
COMPATIBLE_REVISIONS = {
    "office": "491f5a621d037a411e8821d46b469b1ab3d1919c",
    "beijing": "8939da1be6fc794a2fe0739f3550c4e92db8315c",
}
BEIJING = "ubuntu@154.8.205.162"


def writer_key(writer):
    return ":".join(writer[key] for key in ("kind", "host", "service"))


def check_migration_files(source):
    for name, expected in MIGRATIONS.items():
        digest = hashlib.sha256((source / "backend/alembic/versions" / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if digest != expected:
            raise RuntimeError("Migration differs from the reviewed 166/167 chain: " + name)


def check_applications(plan):
    office = publish.run(["git", "-C", plan["live_root"], "rev-parse", "HEAD"], capture=True)
    beijing = publish.run(["ssh", *SSH_OPTIONS, BEIJING,
                          "git -C /home/ubuntu/commission-system rev-parse HEAD"], capture=True)
    for name, actual in (("office", office), ("beijing", beijing)):
        if actual != plan["application_revisions"][name] or actual != COMPATIBLE_REVISIONS[name]:
            raise RuntimeError("Application revision changed or was not reviewed: " + name)


def load_plan(path, credential_file):
    if os.name != "nt":
        raise RuntimeError("Migration-only release runs on the office Windows server")
    plan = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    live = Path(plan["live_root"]).resolve(strict=True)
    state = live / ".deploy_state"
    source = Path(plan["source"]).resolve(strict=True)
    revision = plan["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or source != state / "sources" / revision:
        raise RuntimeError("Expected a pinned candidate under the installed checkout")
    publish.ROOT = source
    publish.STATE = state
    schema_release.ROOT = source
    schema_release.STATE = state
    if publish.run(["git", "-C", source, "rev-parse", "HEAD"], capture=True) != revision:
        raise RuntimeError("Candidate revision mismatch")
    if publish.run(["git", "-C", source, "status", "--porcelain", "--untracked-files=no"], capture=True):
        raise RuntimeError("Candidate contains unreviewed tracked changes")
    check_migration_files(source)
    nssm = Path(plan["nssm"]).resolve(strict=True)
    directory = publish.run([nssm, "get", "CommissionSystem", "AppDirectory"], capture=True)
    if Path(directory).resolve() != live / "backend":
        raise RuntimeError("Live root differs from the installed office service")
    application = Path(publish.run([nssm, "get", "CommissionSystem", "Application"], capture=True))
    python = application.parent / "python.exe"
    if application.name.lower() not in {"python.exe", "uvicorn.exe"} or not python.is_file():
        raise RuntimeError("Unrecognized office Python runtime")
    parameters = publish.run([nssm, "get", "CommissionSystem", "AppParameters"], capture=True)
    port = re.search(r"--port[ =]+(\d+)", parameters)
    if not port:
        raise RuntimeError("Unrecognized office HTTP port")
    current = schema_release.schema_check(source, python, allow_pending=True)
    if current["schema"] != TARGET or current["database"] not in {PARENT, TARGET}:
        raise RuntimeError("Invoice schema repair accepts only the reviewed 164 -> 167 transition")
    if current["pending"] not in ([], PENDING):
        raise RuntimeError("Unexpected pending migration chain")
    schema_release.validate(plan, current["pending"])
    events = plan.get("reviewed_unaffected_events", [])
    if not isinstance(events, list) or any(not re.fullmatch(r"[A-Za-z0-9_]+", e) for e in events):
        raise RuntimeError("Invalid database event inventory")
    return plan, source, {"python": python, "nssm": nssm, "port": int(port[1]),
                          "pending": current["pending"], "schema": current["schema"],
                          "runner": Path(__file__).with_name("migration_runner.py")}


def snapshot_writers(plan, prepared):
    return {writer_key(w): schema_release.writer_state(w, prepared["nssm"])
            for w in plan["migration_writers"]}


def check_health(plan, prepared, baseline):
    office = "nssm:office:CommissionSystem"
    beijing = "systemd:" + BEIJING + ":ark-backend"
    health_code = ("import json,urllib.request;"
            "r=json.load(urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=8));"
            "assert r.get('status')=='ok' and r.get('database')=='connected'")
    business_code = ("from sqlalchemy import text;"
                     "from app.core.database import engine;"
                     "c=engine.connect();"
                     "c.execute(text('SELECT 1 FROM lsordertest.user_rel_team LIMIT 1')).first();"
                     "c.close()")
    for attempt in range(10):
        try:
            if snapshot_writers(plan, prepared) != baseline:
                raise RuntimeError("Writer state does not match its pre-migration state")
            if baseline.get(office) == "running":
                health(prepared["port"])
                publish.run([prepared["python"], "-c", business_code],
                            cwd=Path(plan["source"]) / "backend", capture=True)
            if baseline.get(beijing) == "running":
                publish.run(["ssh", *SSH_OPTIONS, BEIJING, "python3 -c " + shlex.quote(health_code)], capture=True)
                publish.run(["ssh", *SSH_OPTIONS, BEIJING,
                             "cd /home/ubuntu/commission-system/backend && .venv/bin/python -c "
                             + shlex.quote(business_code)], capture=True)
            return
        except Exception:
            if attempt == 9:
                raise
            time.sleep(2)


def verify_invoice_columns(source, prepared):
    code = ("from sqlalchemy import text;"
            "from app.core.database import engine;"
            "c=engine.connect();"
            "c.execute(text('SELECT merchandiser_id, merchandiser_name FROM ark_invoices LIMIT 1')).first();"
            "c.close()")
    publish.run([prepared["python"], "-c", code], cwd=source / "backend", capture=True)


def execute(plan_path, credential_file, prepare_only=False):
    plan, source, prepared = load_plan(plan_path, credential_file)
    record = {"scope": "migration-only", "source_revision": plan["revision"],
              "target": TARGET, "status": "preflight", "stopped": []}
    journal = publish.STATE / "migration-167-current.json"
    with publish.deployment_lock():
        if journal.exists():
            previous = json.loads(journal.read_text(encoding="utf-8"))
            recovery_phases = {"migrating", "verifying", "restoring"}
            if previous.get("status") in recovery_phases or (
                previous.get("status") == "failed" and previous.get("failed_phase") in recovery_phases
            ):
                raise RuntimeError("Recovery required: inspect the preserved migration journal and restore its original writer baseline before rerunning")
        schema_release.check_recovery()
        publish.atomic_json(journal, record)
        try:
            check_applications(plan)
            baseline = snapshot_writers(plan, prepared)
            record["writer_states_before"] = baseline
            record["reviewed_unaffected_events"] = plan.get("reviewed_unaffected_events", [])
            publish.atomic_json(journal, record)
            check_health(plan, prepared, baseline)
            if not prepared["pending"]:
                record["status"] = "already-current"
                publish.atomic_json(journal, record)
                print("MIGRATION ALREADY CURRENT; no application version changed", flush=True)
                return
            schema_release.preflight(prepared, plan, credential_file)
            if prepare_only:
                record["status"] = "prepared"
                publish.atomic_json(journal, record)
                print("MIGRATION PREPARED; no writers stopped and no DDL executed", flush=True)
                return
            check_applications(plan)
            if snapshot_writers(plan, prepared) != baseline:
                raise RuntimeError("Writer state changed after preflight")
            record["status"] = "migrating"
            publish.atomic_json(journal, record)
            stopped = schema_release.migrate(prepared, plan, credential_file)
            record.update(status="verifying", stopped=stopped)
            publish.atomic_json(journal, record)
            with schema_release.database_lock(source, prepared["python"]):
                schema_release.schema_check(source, prepared["python"])
                verify_invoice_columns(source, prepared)
                check_applications(plan)
                record["status"] = "restoring"
                publish.atomic_json(journal, record)
                failures = []
                for writer in reversed(stopped):
                    if baseline.get(writer_key(writer)) != "running":
                        failures.append(writer_key(writer))
                        continue
                    try:
                        schema_release.control(writer, "start", prepared["nssm"])
                    except Exception:
                        failures.append(writer_key(writer))
                if failures:
                    raise RuntimeError("Writer restore incomplete: " + ", ".join(failures))
                check_health(plan, prepared, baseline)
                schema_release.complete(prepared)
            record["status"] = "succeeded"
            publish.atomic_json(journal, record)
            print("MIGRATION COMPLETED: " + TARGET + "; application versions unchanged", flush=True)
        except Exception as error:
            record.update(status="failed", failed_phase=record["status"], error_type=type(error).__name__)
            publish.atomic_json(journal, record)
            raise


def recover_execute(plan_path, credential_file, prepare_only=False):
    """Resume only the inspected failed 166 DDL while keeping its writer baseline."""
    plan, source, prepared = load_plan(plan_path, credential_file)
    prepared["recover_166"] = True
    journal = publish.STATE / "migration-167-current.json"
    with publish.deployment_lock():
        original = json.loads(journal.read_text(encoding="utf-8"))
        if (original.get("status") != "failed"
                or original.get("failed_phase") != "migrating"
                or original.get("target") != TARGET
                or original.get("source_revision") != "0426a760bae8ea097b1812480b7c03f3f7a0e9a8"):
            raise RuntimeError("Dedicated recovery record differs from the inspected incident")
        baseline = original.get("writer_states_before", {})
        if (set(baseline) != {writer_key(writer) for writer in plan["migration_writers"]}
                or any(state != "running" for state in baseline.values())):
            raise RuntimeError("Original writer baseline differs from the inspected incident")
        check_applications(plan)
        schema_release.invoke(prepared, plan["migration_writers"], credential_file, "check")
        if prepare_only:
            print("RECOVERY PREPARED; partial 166 structures and stopped writers verified", flush=True)
            return
        record = {**original, "status": "recovering",
                  "recovery_source_revision": plan["revision"], "recovery_original": original}
        publish.atomic_json(journal, record)
        try:
            result = schema_release.invoke(prepared, plan["migration_writers"], credential_file, "apply")
            record.update(status="verifying", stopped=result["stopped"])
            publish.atomic_json(journal, record)
            with schema_release.database_lock(source, prepared["python"]):
                schema_release.schema_check(source, prepared["python"])
                verify_invoice_columns(source, prepared)
                check_applications(plan)
                record["status"] = "restoring"
                publish.atomic_json(journal, record)
                failures = []
                for writer in reversed(result["stopped"]):
                    try:
                        schema_release.control(writer, "start", prepared["nssm"])
                    except Exception:
                        failures.append(writer_key(writer))
                if failures:
                    raise RuntimeError("Writer restore incomplete: " + ", ".join(failures))
                check_health(plan, prepared, baseline)
                prepared["schema_changed"] = True
                schema_release.complete(prepared)
            record["status"] = "succeeded"
            publish.atomic_json(journal, record)
            print("INVOICE SCHEMA RECOVERED: " + TARGET + "; application versions unchanged", flush=True)
        except Exception as error:
            record.update(status="failed", failed_phase=record["status"], error_type=type(error).__name__)
            publish.atomic_json(journal, record)
            raise
