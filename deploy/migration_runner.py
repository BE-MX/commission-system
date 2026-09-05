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
        if request["action"] == "check":
            return {"status": "ready", "database": runtime.COMMISSION_DB_NAME}
        if connection.execute(text("SELECT GET_LOCK('leshine-schema-release',0)")).scalar() != 1:
            raise RuntimeError("Another database release owns the lock; no writer stopped")
        from schema_release import control
        stopped = []
        ddl_started = False
        try:
            for writer in request["writers"]:
                if control(writer, "stop", request["nssm"]):
                    stopped.append(writer)
            # Alembic imports Settings in this isolated process after the override.
            config.get_settings = lambda: settings
            from alembic import command
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            alembic = Config("alembic.ini")
            script = ScriptDirectory.from_config(alembic)
            ddl_started = True
            command.upgrade(alembic, "head")
            connection.commit()
            current = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
            if current != script.get_heads():
                raise RuntimeError("Schema verification failed after DDL")
            return {"schema": current[0], "stopped": stopped}
        except Exception:
            if not ddl_started:
                for writer in reversed(stopped):
                    control(writer, "start", request["nssm"])
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
