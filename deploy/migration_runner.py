"""Run in the candidate backend Python; DBA settings live only in this process."""

import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path.cwd()))


def execute(request):
    from dotenv import dotenv_values
    from sqlalchemy import create_engine, text
    import app.core.config as config
    runtime = config.get_settings()
    if request["action"] not in {"check", "apply", "resume-maintenance"}:
        raise ValueError("Unsupported migration action")
    journal = Path(request["journal_path"])
    from schema_release import check_recovery
    if not request.get("recover_166") and request['action'] != 'resume-maintenance':
        check_recovery(journal, recover_149=request.get("recover_149", False), recover_151=request.get("recover_151", False), recover_168=request.get("recover_168", False))
    credentials = dotenv_values(request["credential_file"])
    allowed = {"COMMISSION_DB_USER", "COMMISSION_DB_PASSWORD"}
    if set(credentials) != allowed or not all(credentials.values()):
        raise RuntimeError("Migration credential file must contain only DB user and password")
    if credentials["COMMISSION_DB_USER"] == runtime.COMMISSION_DB_USER:
        raise RuntimeError("Migration must use a separate DBA identity")
    settings = runtime.model_copy(update=credentials)
    engine = create_engine(settings.commission_db_url)
    with engine.connect() as connection:
        grants = list(connection.execute(text("SHOW GRANTS")).scalars())
        privileges = set()
        for grant in grants:
            match = re.match(r"GRANT (.+) ON (.+) TO ", grant, re.IGNORECASE)
            if match and match[2].replace('`','').lower() in {"*.*", runtime.COMMISSION_DB_NAME.lower()+".*"}:
                privileges.update(item.strip().upper() for item in match[1].split(','))
        required = {"SELECT","INSERT","UPDATE","DELETE","CREATE","ALTER","DROP","INDEX","REFERENCES"}
        if "ALL PRIVILEGES" not in privileges and not required.issubset(privileges):
            raise RuntimeError("DBA identity lacks required migration privileges; no writer stopped")
        if request['action'] == 'resume-maintenance':
            from portal_maintenance import restore
            from publish import atomic_json
            record = json.loads(journal.read_text(encoding='utf-8'))
            if (record.get('status') != 'upgraded' or record.get('schema') != request['schema']
                    or connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all() != [request['schema']]):
                raise RuntimeError('Maintenance resume requires the verified upgraded schema')
            baseline = record.get('portal_maintenance')
            if baseline:
                if baseline['database_uuid'] != connection.scalar(text('SELECT @@server_uuid')):
                    raise RuntimeError('Maintenance resume database identity changed')
                restore(journal.resolve().parent, settings, baseline)
                atomic_json(journal, record)
            return {'status': 'maintenance-restored'}
        if request.get("recover_168"):
            from migration_recovery168 import execute as recover
            return recover(request, connection, settings)
        if request.get("recover_151"):
            from migration_recovery151 import execute as recover
            return recover(request, connection, settings)
        if request.get("recover_166"):
            from invoice_schema_recovery import execute as recover
            return recover(request, connection, settings)
        if request.get("recover_149"):
            from migration_recovery149 import execute as recover
            return recover(request, connection, settings)
        if request["action"] == "check":
            from customer_portal_backup import validate_proof, backup_privileges
            if '183_portal_password_login' in request['pending']:
                backup_privileges(grants, runtime.COMMISSION_DB_NAME)
            validate_proof(journal.resolve().parent, connection, request['pending'], request['schema'])
            if request['pending'] == ['183_portal_password_login']:
                from portal_maintenance import check
                check(journal.resolve().parent, settings, connection)
            return {"status": "ready", "database": runtime.COMMISSION_DB_NAME}
        if connection.execute(text("SELECT GET_LOCK('leshine-schema-release',0)")).scalar() != 1:
            raise RuntimeError("Another database release owns the lock; no writer stopped")
        from schema_release import control, writer_state
        from publish import atomic_json
        stopped = []
        ddl_started = False
        record = {"status": "checking", "writers": [], "stopped": []}
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            alembic = Config("alembic.ini")
            script = ScriptDirectory.from_config(alembic)
            current = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if len(current) != 1 or script.get_heads() != [request["schema"]]:
                raise RuntimeError("Database/code head changed since preflight; no writer stopped")
            pending = list(reversed([r.revision for r in script.iterate_revisions(request["schema"], current[0], implicit_base=True)]))
            if pending != request["pending"]:
                raise RuntimeError("Pending migration chain changed since preflight; no writer stopped")
            if '183_portal_password_login' in pending and pending != ['183_portal_password_login']:
                raise RuntimeError('Portal credential release requires the separately rehearsed unique 182-to-183 path')
            from customer_portal_backup import validate_proof
            validate_proof(journal.resolve().parent, connection, pending, request['schema'])
            record.update(status="stopping", schema=request["schema"], database=current[0], pending=pending,
                          writers=[{"writer": w, "before": writer_state(w, request["nssm"])} for w in request["writers"]])
            if pending == ['183_portal_password_login']:
                from portal_maintenance import check, freeze
                record['portal_maintenance'] = check(journal.resolve().parent, settings, connection)
            atomic_json(journal, record)
            if record.get('portal_maintenance'):
                freeze(journal.resolve().parent, settings, connection, record['portal_maintenance'], lambda: atomic_json(journal, record))
            for writer in request["writers"]:
                if control(writer, "stop", request["nssm"]):
                    stopped.append(writer)
                    record["stopped"] = stopped.copy()
                    atomic_json(journal, record)
            if any(writer_state(writer, request["nssm"]) != "stopped" for writer in request["writers"]):
                raise RuntimeError("A database writer is still running; no DDL executed")
            if pending == ['183_portal_password_login']:
                from portal_maintenance import verify_frozen
                verify_frozen(journal.resolve().parent, settings, connection, record['portal_maintenance'])
                from customer_portal_backup import snapshot
                record['backup'] = snapshot(journal.resolve().parent.parent, settings, connection)
                atomic_json(journal, record)
                verify_frozen(journal.resolve().parent, settings, connection, record['portal_maintenance'])
            # Alembic imports Settings in this isolated process after the override.
            config.get_settings = lambda: settings
            from alembic import command
            record["status"] = "running-ddl"
            atomic_json(journal, record)
            ddl_started = True
            command.upgrade(alembic, "head")
            connection.commit()
            current = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if current != script.get_heads():
                raise RuntimeError("Schema verification failed after DDL")
            record.update(status="upgraded", schema=current[0])
            atomic_json(journal, record)
            return {"schema": current[0], "stopped": stopped}
        except Exception:
            if not ddl_started:
                # A stop command can change state and then fail. Restore from the
                # persisted baseline, not only the commands that returned success.
                recovery_errors = []
                for entry in reversed(record["writers"]):
                    try:
                        if entry["before"] == "running":
                            control(entry["writer"], "start", request["nssm"])
                        if writer_state(entry["writer"], request["nssm"]) != entry["before"]:
                            raise RuntimeError("Writer baseline was not restored")
                    except Exception as error:
                        recovery_errors.append({"writer": entry["writer"], "error_type": type(error).__name__})
                if record.get('portal_maintenance'):
                    try:
                        from portal_maintenance import restore
                        restore(journal.resolve().parent, settings, record['portal_maintenance'])
                    except Exception as error:
                        recovery_errors.append({'writer': 'portal-event-and-mirror-maintenance', 'error_type': type(error).__name__})
                record.update(status="recovery-required" if recovery_errors else "restored-before-ddl",
                              recovery_errors=recovery_errors)
            else:
                record["status"] = "failed-after-ddl"
            atomic_json(journal, record)
            raise
        finally:
            connection.execute(text("SELECT RELEASE_LOCK('leshine-schema-release')"))
    engine.dispose()


if __name__ == "__main__":
    try:
        print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as error:
        # DB exceptions can contain connection strings; do not emit credentials.
        print("Migration runner failed: " + type(error).__name__ + "; inspect DBA access/schema state locally", file=sys.stderr)
        sys.exit(1)
