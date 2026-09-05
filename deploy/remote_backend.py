"""Run as ubuntu on the registered Beijing server. No secrets in responses."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path("/home/ubuntu/commission-system")
STATE = ROOT / ".deploy_state"
SERVICE = "ark-backend"


def run(args, cwd=ROOT, capture=False):
    result = subprocess.run(args, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else sys.stderr,
                            stderr=sys.stderr, timeout=900)
    return result.stdout.strip() if capture else ""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema_check(source, python, allow_pending=False):
    code = '''
import json
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from app.core.config import get_settings
script=ScriptDirectory('alembic')
heads=script.get_heads()
engine=create_engine(get_settings().commission_db_url)
with engine.connect() as c:
    current=list(c.execute(text('SELECT version_num FROM alembic_version')).scalars())
engine.dispose()
if len(heads)!=1 or len(current)!=1:
    raise RuntimeError('Expected one database revision and one code head')
script.get_revision(current[0])
pending=[r.revision for r in script.iterate_revisions(heads[0],current[0])]
print(json.dumps({'schema':heads[0], 'database':current[0], 'pending':list(reversed(pending))}))
'''
    result = json.loads(run([str(python), "-c", code], cwd=source / "backend", capture=True))
    if result["pending"] and not allow_pending:
        raise RuntimeError("Pending shared database migration; run verified full office release: " + json.dumps(result))
    return result


def prepare(revision, allow_pending=False):
    if run(["git", "status", "--porcelain", "--untracked-files=no"], capture=True):
        raise RuntimeError("Beijing checkout has tracked changes; refusing to overwrite")
    run(["git", "fetch", "/home/ubuntu/repo.git", revision])
    source = STATE / "checkouts" / revision
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "worktree", "add", "--detach", str(source), revision])
    env_file = source / "backend/.env"
    if not env_file.exists():
        env_file.symlink_to(ROOT / "backend/.env")
    requirements = source / "backend/requirements.txt"
    current_requirements = ROOT / "backend/requirements.txt"
    requirements_changed = digest(requirements) != digest(current_requirements)
    python = ROOT / "backend/.venv/bin/python"
    candidate_env = STATE / "python-envs" / digest(requirements)
    if requirements_changed:
        marker = candidate_env / ".ark-ready"
        if not marker.exists():
            if not candidate_env.exists():
                candidate_env.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(ROOT / "backend/.venv", candidate_env, symlinks=True)
            python = candidate_env / "bin/python"
            prefix = run([str(python), "-c", "import sys;print(sys.prefix)"], capture=True)
            if Path(prefix).resolve() != candidate_env.resolve():
                raise RuntimeError("Candidate environment is not isolated")
            run([str(python), "-m", "pip", "install", "-r", str(requirements)])
            run([str(python), "-m", "pip", "check"])
            marker.write_text(digest(requirements))
        python = candidate_env / "bin/python"
    checked = schema_check(source, python, allow_pending=allow_pending)
    run([str(python), "-m", "compileall", "-q", str(source / "backend/app")])
    # Import the new route graph without starting the application lifespan/seeds/jobs.
    run([str(python), "-c", "import app.routers"], cwd=source / "backend")
    previous = run(["git", "rev-parse", "HEAD"], capture=True)
    changes = run(["git", "diff", "--name-only", previous, revision, "--", "backend", "config"], capture=True)
    info = {"revision": revision, "previous": previous, "schema": checked["schema"],
            "schema_changed": bool(checked["pending"]),
            "changed": bool(changes), "environment": str(candidate_env) if requirements_changed else None}
    STATE.mkdir(exist_ok=True)
    (STATE / ("backend-prepared-" + revision + ".json")).write_text(json.dumps(info))
    return info


def healthy():
    with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=8) as response:
        result = json.load(response)
        if response.status != 200 or result.get("status") != "ok" or result.get("database") != "connected":
            raise RuntimeError("Beijing health check failed")


def activate(revision):
    record = STATE / ("backend-prepared-" + revision + ".json")
    info = json.loads(record.read_text())
    if run(["git", "rev-parse", "HEAD"], capture=True) not in {info["previous"], revision}:
        raise RuntimeError("Beijing code changed after preparation")
    source = STATE / "checkouts" / revision
    python = Path(info["environment"]) / "bin/python" if info["environment"] else ROOT / "backend/.venv/bin/python"
    schema_check(source, python)
    if not info["changed"] and not info.get("schema_changed"):
        healthy()
        return {"status": "unchanged", "schema": info["schema"]}
    run(["sudo", "-n", "systemctl", "stop", SERVICE])
    venv = ROOT / "backend/.venv"
    backup_env = STATE / ("previous-venv-" + info["previous"])
    switched_env = False
    try:
        if info["environment"]:
            if venv.is_symlink():
                previous_env = str(venv.resolve())
                venv.unlink()
            else:
                if backup_env.exists():
                    raise RuntimeError("Previous environment backup already exists")
                venv.rename(backup_env)
                previous_env = str(backup_env)
            switched_env = True
            info["previous_environment"] = previous_env
            venv.symlink_to(info["environment"], target_is_directory=True)
        run(["git", "checkout", "--detach", revision])
        run(["sudo", "-n", "systemctl", "start", SERVICE])
        for attempt in range(15):
            try:
                healthy()
                break
            except Exception as error:
                print("Beijing readiness retry: " + type(error).__name__, file=sys.stderr, flush=True)
                if attempt == 14:
                    raise
                time.sleep(2)
        info["status"] = "updated"
        (STATE / "backend-success.json").write_text(json.dumps(info))
        return {"status": "updated", "revision": revision, "schema": info["schema"]}
    except Exception:
        run(["sudo", "-n", "systemctl", "stop", SERVICE])
        if info.get("schema_changed"):
            raise RuntimeError("Beijing activation failed after schema change; service held stopped, no code downgrade") from None
        run(["git", "checkout", "--detach", info["previous"]])
        if switched_env:
            venv.unlink(missing_ok=True)
            venv.symlink_to(info["previous_environment"], target_is_directory=True)
        run(["sudo", "-n", "systemctl", "start", SERVICE])
        raise


def main():
    import fcntl
    STATE.mkdir(exist_ok=True)
    lock = (STATE / "backend.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    request = json.load(sys.stdin)
    revision = request["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected a complete commit SHA")
    if request["action"] == "prepare":
        result = prepare(revision, request.get("allow_pending", False))
    elif request["action"] == "activate":
        result = activate(revision)
    else:
        raise ValueError("Unknown backend action")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
