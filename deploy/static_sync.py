"""Prepare and activate only changed static bytes on registered cloud targets."""

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
               "-o", "ConnectionAttempts=3",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
HERE = Path(__file__).resolve().parent


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def remote(target, request):
    result = remote_python(target, HERE / "remote_static.py", request, sudo=True)
    result.check_returncode()
    return json.loads(result.stdout)


def remote_python(target, script, request, *, sudo=False, timeout=300):
    # Windows SSH launchers truncate long command arguments. Stream the source
    # separately from JSON; the executed script continues reading the same stdin.
    command = ("sudo -n " if sudo else "") + "python3 -c 'import base64,sys;exec(base64.b64decode(sys.stdin.readline()))'"
    payload = base64.b64encode(script.read_bytes()).decode() + "\n" + json.dumps(request)
    return subprocess.run(["ssh", *SSH_OPTIONS, target, command], input=payload,
                          text=True, capture_output=True, timeout=timeout)


def manifest(source, require_index=True):
    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in build artifacts")
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            if any(part.startswith(".") for part in path.relative_to(source).parts):
                raise ValueError("Hidden files cannot be published")
            with path.open("rb") as stream:
                files[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
    if require_index and "index.html" not in files:
        raise ValueError("Build is missing index.html")
    return files


def prepare(source, target, root, state, host):
    files = manifest(source)
    common = {"root": root, "manifest": files, "host": host}
    result = remote(target, {**common, "action": "plan"})
    transferred = 0
    if not result.get("staged") and (result["missing"] or not result["initialized"] or result["active_artifact"] != result["artifact"]):
        archive = state / (result["artifact"] + ".tar.gz")
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz") as bundle:
            for name in result["missing"]:
                bundle.add(source / name, arcname=name, recursive=False)
        transferred = archive.stat().st_size
        remote_archive = "/tmp/ark-static-" + result["artifact"] + ".tar.gz"
        run(["scp", *SSH_OPTIONS, str(archive), target + ":" + remote_archive], timeout=300)
        remote(target, {**common, "action": "stage", "archive": remote_archive})
    print(f"  {target}:{root}: {len(result['missing'])} changed files, {transferred} transfer bytes, staged={result.get('staged', False)}", flush=True)
    common["expected"] = result["active_artifact"]
    return {"target": target, "request": common, "bytes": transferred}


def activate(prepared):
    return remote(prepared["target"], {**prepared["request"], "action": "activate"})
