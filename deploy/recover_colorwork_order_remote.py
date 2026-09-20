"""Narrow, journal-preserving recovery of the inspected schema-160 release."""
import json
from pathlib import Path
import sys
import time

REVISION = "d021ece8b5fbe261fe95cb6f48ef87def85fedfc"
PREVIOUS = "fea48d6c22937f3064a40546292ea4e03927d2b9"
SCHEMA = "160_domestic_price_review"


def validate(info, original, source, head, dirty):
    if dirty or head not in {PREVIOUS, REVISION}:
        raise RuntimeError("Beijing source drift")
    if any(info.get(k) != v for k, v in {"revision": REVISION, "previous": PREVIOUS,
            "schema": SCHEMA, "schema_changed": True, "environment": None}.items()):
        raise RuntimeError("Unrecognized backend preparation")
    if original.get("status") != "failed" or original.get("source") != str(source):
        raise RuntimeError("Unrecognized colorwork failure")


def execute(request):
    if request.get("revision") != REVISION:
        raise ValueError("Recovery is pinned to the inspected release")
    root = Path("/home/ubuntu/commission-system")
    state = root / ".deploy_state"
    source = state / "checkouts" / REVISION
    sys.path.insert(0, str(source / "deploy"))
    import remote_backend as backend
    import colorwork_release as color
    import fcntl
    with (state / "backend.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        python = root / "backend/.venv/bin/python"
        with backend.database_lock(source, python):
            info = json.loads((state / ("backend-prepared-" + REVISION + ".json")).read_text())
            cs = state / "colorwork"
            current = json.loads((cs / "current.json").read_text())
            archive = cs / ("start-order-original-" + REVISION + ".json")
            original = json.loads(archive.read_text()) if archive.exists() else current
            validate(info, original, source,
                     backend.run(["git", "rev-parse", "HEAD"], capture=True),
                     backend.run(["git", "status", "--porcelain", "--untracked-files=no"], capture=True))
            if backend.run(["git", "rev-parse", "HEAD"], cwd=source, capture=True) != REVISION or backend.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, capture=True):
                raise RuntimeError("Candidate source drift")
            checked = backend.schema_check(source, python)
            if checked != {"schema": SCHEMA, "database": SCHEMA, "pending": []}:
                raise RuntimeError("Unexpected database schema")
            prepared = json.loads((cs / ("prepared-" + REVISION + ".json")).read_text())
            for key in ("source", "unit", "node", "migrations"):
                if current.get(key) != original.get(key) or prepared.get(key) != original.get(key):
                    raise RuntimeError("Colorwork preparation drift")
            unit = cs / ("unit-" + REVISION + ".service")
            installed = color.UNIT_DIRECTORY / "ark-colorwork.service"
            if Path(original["unit"]) != unit or not installed.read_text().startswith(color.MANAGED) or installed.read_bytes() != unit.read_bytes():
                raise RuntimeError("Installed colorwork unit differs from failed candidate")
            backup = Path(original["backup"])
            if backup.parent != cs / "backups" or not backup.is_dir():
                raise RuntimeError("Original colorwork backup is missing")
            files = color.migration_files(source / "colorwork-workbench")
            if files != original["migrations"]:
                raise RuntimeError("Colorwork migrations changed")
            color.verify_checksums(cs, files)
            color.verify_history(cs / "data", files)
            if request.get("prepare_only"):
                return {"status": "prepared", "revision": REVISION, "schema": SCHEMA}
            if not archive.exists():
                color.atomic_json(archive, original)
            # No migrations, unit replacement, environment switch or code downgrade.
            already_active = backend.run(["git", "rev-parse", "HEAD"], capture=True) == REVISION
            success = state / "backend-success.json"
            already_active = already_active and success.exists() and json.loads(success.read_text()).get("revision") == REVISION
            if already_active:
                backend.healthy()
            else:
                backend.run(["sudo", "-n", "systemctl", "stop", "ark-backend"])
                backend.run(["git", "checkout", "--detach", REVISION])
                backend.run(["sudo", "-n", "systemctl", "start", "ark-backend"])
                for attempt in range(30):
                    try:
                        backend.healthy()
                        break
                    except Exception:
                        if attempt == 29:
                            backend.run(["sudo", "-n", "systemctl", "stop", "ark-backend"])
                            raise
                        time.sleep(2)
            info["status"] = "updated"
            color.atomic_json(state / "backend-success.json", info)
            backend.run(["sudo", "-n", "systemctl", "start", "ark-colorwork"])
            for attempt in range(30):
                try:
                    color.healthy()
                    break
                except Exception:
                    if attempt == 29:
                        backend.run(["sudo", "-n", "systemctl", "stop", "ark-colorwork"])
                        raise
                    time.sleep(2)
            current.update(status="succeeded", recovered_from=str(archive))
            color.atomic_json(cs / "current.json", current)
            color.atomic_json(cs / "success.json", current)
            return {"status": "recovered", "revision": REVISION, "schema": SCHEMA}


if __name__ == "__main__":
    print(json.dumps(execute(json.load(sys.stdin))))
