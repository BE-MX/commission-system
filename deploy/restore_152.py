"""Restore the reviewed pre-151 applications after the additive FK failure; no DDL."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import publish
import schema_release
from remote_backend import database_lock
from static_sync import SSH_OPTIONS

REVISION = "ba491dfece056ca14e0e6cf1a848eacfcfca1ef2"
DATABASE = "152_shipping_media_recall"
PENDING = ["151_customer_media_tags", "153_shipping_station", "154_okki_outbound_tasks"]
BJ = "ubuntu@154.8.205.162"


def validate_journal(record):
    if record.get("status") != "failed-after-ddl" or record.get("database") != DATABASE or record.get("pending") != PENDING:
        raise RuntimeError("Not the reviewed 152 -> 151 incident")
    if record.get("schema") != PENDING[-1] or len(record.get("writers", [])) != 4:
        raise RuntimeError("Unexpected migration target or writer baseline")
    writers = [entry["writer"] for entry in record["writers"]]
    if any(entry.get("before") != "running" for entry in record["writers"]) or record.get("stopped") != writers:
        raise RuntimeError("Original running/stopped writer evidence is incomplete")
    schema_release.validate({"migration_writers_verified": True, "migration_writers": writers}, PENDING)
    return writers


def validate_schema(snapshot):
    if snapshot["revision"] != [DATABASE]:
        raise RuntimeError("Database has moved beyond the compatible application")
    if snapshot["future_tables"] or snapshot["customer_seed"]:
        raise RuntimeError("Unreviewed migration objects or data exist")
    column = snapshot["tag_scope"]
    if column != {"length": 16, "nullable": False, "default": "internal"}:
        raise RuntimeError("Unexpected partial tag_scope column")
    if snapshot["index"] != {"columns": ["tag_scope"], "unique": False}:
        raise RuntimeError("Unexpected partial tag_scope index")
    if snapshot["unsigned_ids"] != [True, True, False]:
        raise RuntimeError("Referenced key types differ from the reviewed incident")


SCHEMA_CHECK = r'''import json
from sqlalchemy import create_engine, inspect, text
from app.core.config import get_settings
engine=create_engine(get_settings().commission_db_url)
with engine.connect() as c:
 i=inspect(c)
 tables=set(i.get_table_names())
 cols={x['name']:x for x in i.get_columns('ark_tag_dimensions')}
 col=cols.get('tag_scope', {})
 idx=next((x for x in i.get_indexes('ark_tag_dimensions') if x['name']=='idx_tag_dim_scope'), {})
 future=['ark_customer_media_asset_tags','ark_shipping_station_sessions','ark_shipping_operation_events','ark_okki_outbound_tasks']
 unsigned=[bool(getattr(next(x for x in i.get_columns(t) if x['name']=='id')['type'],'unsigned',False)) for t in ['ark_tag_dimensions','ark_tag_values','ark_customer_media_assets']]
 print(json.dumps({'revision':list(c.execute(text('SELECT version_num FROM alembic_version')).scalars()),
  'future_tables':sorted(tables.intersection(future)),
  'customer_seed':c.execute(text("SELECT COUNT(*) FROM ark_tag_dimensions WHERE name='customer_general'")).scalar(),
  'tag_scope':{'length':getattr(col.get('type'),'length',None),'nullable':col.get('nullable'),'default':str(col.get('default','')).strip("'")},
  'index':{'columns':idx.get('column_names'),'unique':bool(idx.get('unique'))},'unsigned_ids':unsigned}))
engine.dispose()
'''


def validate_beijing_untracked(paths):
    # Read-only inventory confirmed these historical backups and business storage.
    for path in paths:
        normalized = path.replace("\\", "/")
        if not path or path in {"backend/.env.bak-20260731", "backend/.env.bak-20260801-150359"}:
            continue
        if normalized.startswith(("backend/D:/WORKSOURCE/design-image/", "backend/D:/WORKSOURCE/domestic/")):
            continue
        raise RuntimeError("Beijing contains an unreviewed untracked file")


def execute(plan_path, prepare_only=False):
    if os.name != "nt":
        raise RuntimeError("Recovery must run on the installed office server")
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    live = Path(plan["live_root"]).resolve()
    state = live / ".deploy_state"
    journal = state / "schema-writers.json"
    nssm = shutil.which("nssm") or str(Path.home() / "AppData/Local/Microsoft/WinGet/Links/nssm.exe")
    python = live / "backend/.venv/Scripts/python.exe"
    def run(args, cwd=live):
        return subprocess.check_output([str(a) for a in args], cwd=cwd, text=True, timeout=90).strip()
    def ssh(command):
        return run(["ssh", *SSH_OPTIONS, BJ, command])
    publish.STATE = state
    with publish.deployment_lock(), database_lock(live, python):
        if Path(run([nssm, "get", "CommissionSystem", "AppDirectory"])).resolve() != live / "backend":
            raise RuntimeError("Live root is not the installed service")
        if Path(run([nssm, "get", "WhatsAppConnector", "AppDirectory"])).resolve() != live / "services/whatsapp-connector":
            raise RuntimeError("Connector belongs to a different installation")
        application = Path(run([nssm, "get", "CommissionSystem", "Application"])).resolve()
        if application.parent != python.parent or application.name.lower() not in {"python.exe", "uvicorn.exe"}:
            raise RuntimeError("Office service executable changed")
        if run(["git", "rev-parse", "HEAD"]) != REVISION or ssh("git -C /home/ubuntu/commission-system rev-parse HEAD") != REVISION:
            raise RuntimeError("Office or Beijing application is not the reviewed version")
        if run(["git", "status", "--porcelain"]) or ssh("git -C /home/ubuntu/commission-system status --porcelain --untracked-files=no"):
            raise RuntimeError("Application checkout has unreviewed changes")
        untracked = ssh("git -C /home/ubuntu/commission-system -c core.quotepath=false ls-files --others --exclude-standard -z").split("\x00")
        validate_beijing_untracked(untracked)
        unit = ssh("systemctl show ark-backend -p WorkingDirectory -p ExecStart")
        if "WorkingDirectory=/home/ubuntu/commission-system/backend" not in unit or "path=/home/ubuntu/commission-system/backend/.venv/bin/uvicorn" not in unit:
            raise RuntimeError("Beijing service ownership changed")
        raw = journal.read_bytes()
        if hashlib.sha256(raw).hexdigest() != plan["journal_sha256"]:
            raise RuntimeError("Migration evidence changed")
        record = json.loads(raw)
        writers = validate_journal(record)
        snapshot = json.loads(run([python, "-c", SCHEMA_CHECK], cwd=live / "backend"))
        validate_schema(snapshot)
        states = [schema_release.writer_state(writer, nssm) for writer in writers]
        if any(status not in {"running", "stopped"} for status in states):
            raise RuntimeError("A recorded writer is not stable")
        evidence = {"status": "prepared", "revision": REVISION, "database": DATABASE,
                    "journal_sha256": plan["journal_sha256"], "snapshot": snapshot, "observed_states": states, "started": []}
        output = state / "restore-152.json"
        if prepare_only:
            print(json.dumps(evidence))
            return
        publish.atomic_json(output, evidence)
        try:
            for writer in writers:
                if schema_release.control(writer, "start", nssm):
                    evidence["started"].append(writer)
                evidence["status"] = "starting"
                publish.atomic_json(output, evidence)
            from office_release import health
            for attempt in range(30):
                try:
                    health(8001)
                    cloud = json.loads(ssh("curl -fsS --max-time 8 http://127.0.0.1:8001/health"))
                    if cloud.get("status") != "ok" or cloud.get("database") != "connected":
                        raise RuntimeError("Beijing readiness failed")
                    break
                except Exception:
                    if attempt == 29:
                        raise
                    time.sleep(2)
            if any(schema_release.writer_state(writer, nssm) != "running" for writer in writers):
                raise RuntimeError("A restored writer is not running")
            if journal.read_bytes() != raw:
                raise RuntimeError("Migration journal changed during recovery")
            evidence["status"] = "restored-compatible-152"
            publish.atomic_json(output, evidence)
            print(json.dumps(evidence))
        except Exception:
            evidence["status"] = "recovery-required"
            publish.atomic_json(output, evidence)
            raise
