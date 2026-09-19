"""Managed, loopback-only colorwork runtime on Beijing; invoked by deploy.bat.

Preparation builds and migrates an isolated validation store. Activation alone
stops the module and upgrades its persistent SQLite store. Never touch MySQL.
"""

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid

SERVICE = "ark-colorwork"
MANAGED = "# Managed by Ark deploy/colorwork_release.py"
PUBLIC_PATH = "/api/colorwork/workbench"
UNIT_DIRECTORY = Path("/etc/systemd/system")
NODE_VERSION = "v22.23.2"
# Official nodejs.org/dist/v22.23.2/SHASUMS256.txt (linux-x64.tar.xz).
NODE_SHA256 = "d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307"


def run(args, cwd, capture=False):
    environment = dict(os.environ)
    executable = Path(str(args[0]))
    if executable.is_absolute() and executable.name in {"node", "npx"}:
        environment["PATH"] = str(executable.parent) + os.pathsep + environment.get("PATH", "")
    result = subprocess.run([str(a) for a in args], cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else sys.stderr,
                            stderr=sys.stderr, timeout=900, env=environment)
    return result.stdout.strip() if capture else ""


def ensure_node(state):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise RuntimeError("Managed colorwork runtime currently targets Beijing Linux x64 only")
    runtimes = state / "runtimes"
    package = f"node-{NODE_VERSION}-linux-x64"
    node = runtimes / package / "bin/node"
    if node.is_file() and run([node, "--version"], state, True) == NODE_VERSION:
        return str(node)
    runtimes.mkdir(exist_ok=True)
    archive = runtimes / (package + ".tar.xz")
    if not archive.exists():
        partial = archive.with_suffix(".partial")
        with urllib.request.urlopen(f"https://nodejs.org/dist/{NODE_VERSION}/{archive.name}", timeout=60) as response:
            with partial.open("wb") as output:
                shutil.copyfileobj(response, output)
        partial.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != NODE_SHA256:
        raise RuntimeError("Managed Node archive checksum mismatch; no executable installed")
    with tarfile.open(archive, "r:xz") as package_file:
        package_file.extractall(runtimes, filter="data")
    if run([node, "--version"], state, True) != NODE_VERSION:
        raise RuntimeError("Managed Node runtime failed verification")
    return str(node)


def paths(root, source):
    root, source = Path(root).resolve(), Path(source).resolve()
    if not source.is_relative_to(root / ".deploy_state/checkouts"):
        raise ValueError("Colorwork source must be a prepared Beijing checkout")
    return root, source, root / ".deploy_state/colorwork", source / "colorwork-workbench"


def atomic_json(path, value):
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def migration_files(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((folder / "drizzle").glob("*.sql"))}


def verify_history(state, files):
    for db in state.glob("**/*.sqlite"):
        with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as connection:
            exists = connection.execute("SELECT name FROM sqlite_master WHERE name='d1_migrations'").fetchone()
            if exists:
                applied = {row[0] for row in connection.execute("SELECT name FROM d1_migrations")}
                if not applied.issubset(files):
                    raise RuntimeError("Colorwork data has migrations unknown to candidate; refusing downgrade")


def verify_checksums(state, files):
    previous = state / "success.json"
    if previous.exists():
        old = json.loads(previous.read_text()).get("migrations", {})
        if any(files.get(name) != checksum for name, checksum in old.items()):
            raise RuntimeError("Applied colorwork migration changed or disappeared")


def unit_text(folder, state, node, user):
    # Paths originate from fixed deployment roots; reject control/quote injection.
    for value in (str(folder), str(state), str(node), user):
        if any(c in value for c in '\n\r"%'):
            raise ValueError("Invalid systemd value")
    return f'''{MANAGED}
[Unit]
Description=Ark internal inventory colorwork runtime
After=network-online.target
[Service]
Type=simple
User={user}
WorkingDirectory={folder}
Environment=WRANGLER_SEND_METRICS=false
Environment=WRANGLER_LOG_PATH={state}/logs
Environment="PATH={Path(node).parent}:/usr/local/bin:/usr/bin:/bin"
ExecStart="{node}" "{folder}/node_modules/wrangler/bin/wrangler.js" dev --config wrangler.prod.jsonc --ip 127.0.0.1 --port 8787 --persist-to "{state}/data"
Restart=on-failure
RestartSec=3
KillMode=control-group
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
'''


def prepare(root, source, python):
    root, source, state, folder = paths(root, source)
    state.mkdir(parents=True, exist_ok=True)
    journal = state / "current.json"
    if journal.exists() and json.loads(journal.read_text()).get("status") in {"activating", "failed"}:
        raise RuntimeError("Colorwork activation needs recovery; inspect current.json before another release")
    node = ensure_node(state)
    version = tuple(int(v) for v in run([node, "--version"], folder, True).lstrip("v").split("."))
    if version < (22, 13, 0):
        raise RuntimeError("Colorwork requires Node >=22.13 on Beijing")
    # Pin the installer too; it is never downloaded as an unbounded latest version.
    pnpm = [str(Path(node).parent / "npx"), "--yes", "pnpm@10.33.2"]
    marker = state / ("build-" + source.name + ".json")
    if marker.exists():
        built = json.loads(marker.read_text())
        actual = {p.relative_to(folder / "dist").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (folder / "dist").rglob("*") if p.is_file()}
        if built["node"] != list(version) or built["files"] != actual:
            # Do not rebuild the same checkout while its live wrangler watches it.
            raise RuntimeError("Prepared colorwork build changed; use a fresh candidate")
    else:
        run([*pnpm, "install", "--frozen-lockfile"], folder)
        run([*pnpm, "build"], folder)
        built = {"node": list(version), "files": {
            p.relative_to(folder / "dist").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (folder / "dist").rglob("*") if p.is_file()}}
        atomic_json(marker, built)
    if not (folder / "dist/server/index.js").is_file():
        raise RuntimeError("Colorwork build output missing")
    files = migration_files(folder)
    if not files:
        raise RuntimeError("Colorwork migration files missing")
    verify_history(state / "data", files)
    verify_checksums(state, files)
    if not any((state / "data").glob("**/*.sqlite")):
        for legacy in (Path("/var/lib/colorwork-workbench/state"), root / "colorwork-workbench/.wrangler/state"):
            if any(legacy.glob("**/*.sqlite")):
                raise RuntimeError("Existing colorwork data found outside managed store; preserve and relocate it before activation")
    # Settings never leave the server or go into logs/build archives. Generated only
    # after compilation, into an ignored 0600 config consumed by the loopback worker.
    config_path = folder / ".dev.vars"
    code = '''
import json, os
from pathlib import Path
from app.colorwork.service import _sso_secret, sync_secret
from app.colorwork.storage_service import secret as storage_secret
from app.core.storage.files import managed
p = Path(__import__('sys').argv[1])
values = {'ARK_SSO_SECRET': _sso_secret(), 'ARK_SYNC_KEY': sync_secret(),
          'ARK_STATUS_ENDPOINT': 'http://127.0.0.1:8001/api/colorwork/inventory-status'}
if managed('colorwork'):
    values.update(ARK_STORAGE_ENDPOINT='http://127.0.0.1:8001/api/colorwork/storage',
                  ARK_STORAGE_SECRET=storage_secret())
content = ''.join(k+'='+json.dumps(v)+'\\n' for k,v in values.items())
if p.exists():
    if p.read_text() != content:
        raise RuntimeError('Runtime settings changed; prepare a fresh release candidate')
    raise SystemExit(0)
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write(content)
os.chmod(p, 0o600)
'''
    run([python, "-c", code, config_path], source / "backend")
    validation = state / "validation" / source.name
    wrangler = [node, folder / "node_modules/wrangler/bin/wrangler.js"]
    run([*wrangler, "d1", "migrations", "apply", "site-creator-d1", "--local",
         "--config", "wrangler.prod.jsonc", "--persist-to", validation], folder)
    user = run(["id", "-un"], folder, True)
    unit = state / ("unit-" + source.name + ".service")
    unit.write_text(unit_text(folder, state, node, user), encoding="utf-8")
    installed = UNIT_DIRECTORY / (SERVICE + ".service")
    if installed.exists() and not installed.read_text().startswith(MANAGED):
        raise RuntimeError("Existing colorwork service is not managed by this deploy entry")
    info = {"source": str(source), "unit": str(unit), "node": node, "migrations": files,
            "status": "prepared"}
    atomic_json(state / ("prepared-" + source.name + ".json"), info)
    return {"status": "prepared", "module": "colorwork", "path": PUBLIC_PATH}


def healthy():
    with urllib.request.urlopen("http://127.0.0.1:8787" + PUBLIC_PATH + "/api/health", timeout=4) as response:
        value = json.load(response)
        if response.status != 200 or value != {"status": "ok", "module": "colorwork"}:
            raise RuntimeError("Colorwork readiness failed")


def activate(root, source):
    root, source, state, folder = paths(root, source)
    info = json.loads((state / ("prepared-" + source.name + ".json")).read_text())
    if info["migrations"] != migration_files(folder):
        raise RuntimeError("Colorwork migration content changed after preparation")
    verify_checksums(state, info["migrations"])
    verify_history(state / "data", info["migrations"])
    journal = state / "current.json"
    if journal.exists() and json.loads(journal.read_text()).get("status") in {"activating", "failed"}:
        raise RuntimeError("Colorwork recovery required; refusing to overwrite prior failure evidence")
    success = state / "success.json"
    if success.exists() and json.loads(success.read_text()).get("source") == str(source):
        healthy()
        return {"status": "unchanged", "module": "colorwork", "path": PUBLIC_PATH}
    info["status"] = "activating"
    attempt = source.name + "-" + uuid.uuid4().hex
    info["backup"] = str(state / "backups" / attempt)
    atomic_json(journal, info)
    try:
        installed = UNIT_DIRECTORY / (SERVICE + ".service")
        if installed.exists():
            if not installed.read_text().startswith(MANAGED):
                raise RuntimeError("Refusing to replace an unmanaged colorwork service")
            shutil.copy2(installed, state / ("previous-unit-" + attempt + ".service"))
            run(["sudo", "-n", "systemctl", "stop", SERVICE], root)
        data = state / "data"
        data.mkdir(exist_ok=True)
        verify_history(data, info["migrations"])
        backup = Path(info["backup"])
        # Worker is stopped. Copy D1/R2 metadata and blobs together to preserve state.
        if any(data.iterdir()):
            shutil.copytree(data, backup)
        run([info["node"], folder / "node_modules/wrangler/bin/wrangler.js", "d1", "migrations", "apply",
             "site-creator-d1", "--local", "--config", "wrangler.prod.jsonc", "--persist-to", data], folder)
        run(["sudo", "-n", "install", "-m", "644", info["unit"], installed], root)
        run(["sudo", "-n", "systemctl", "daemon-reload"], root)
        run(["sudo", "-n", "systemctl", "enable", "--now", SERVICE], root)
        for attempt in range(30):
            try:
                healthy()
                break
            except Exception:
                if attempt == 29:
                    raise RuntimeError("Colorwork service did not become ready") from None
                time.sleep(1)
        info["status"] = "succeeded"
        atomic_json(journal, info)
        atomic_json(state / "success.json", info)
        return {"status": "updated", "module": "colorwork", "path": PUBLIC_PATH}
    except Exception:
        info["status"] = "failed"
        atomic_json(journal, info)
        if installed.exists() and installed.read_text().startswith(MANAGED):
            subprocess.run(["sudo", "-n", "systemctl", "stop", SERVICE], cwd=root,
                           stdout=sys.stderr, stderr=sys.stderr, timeout=30, check=False)
        # No automatic schema downgrade; journal/backups survive for explicit recovery.
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "activate"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--python")
    args = parser.parse_args()
    result = prepare(args.root, args.source, args.python) if args.action == "prepare" else activate(args.root, args.source)
    print(json.dumps(result))
