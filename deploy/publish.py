"""One release entry for office and cloud; explicit partial scope for cloud-only."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import cloud_backend
import static_sync

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".deploy_state"
SG = "root@119.28.107.92"
BJ = "ubuntu@154.8.205.162"


def run(args, cwd=ROOT, capture=False):
    print("  " + " ".join(str(a) for a in args[:4]), flush=True)
    result = subprocess.run([str(a) for a in args], cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None, timeout=1200)
    return result.stdout.strip() if capture else ""


def atomic_json(path, data):
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def deployment_lock():
    STATE.mkdir(exist_ok=True)
    lock = STATE / "publish.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Deployment locked; inspect the running/previous process before retrying") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink()


def input_digest(paths, extra=""):
    digest = hashlib.sha256(extra.encode())
    ignored = {"node_modules", "dist", "dist-lan", ".venv", "__pycache__", ".pytest_cache", ".git", ".deploy_state", "release"}
    for path in paths:
        files = []
        if path.is_dir():
            for directory, folders, names in os.walk(path):
                folders[:] = sorted(n for n in folders if n not in ignored)
                files.extend(Path(directory) / n for n in sorted(names))
        else:
            files = [path]
        for file in files:
            if not file.is_file() or any(part in ignored for part in file.relative_to(ROOT).parts):
                continue
            digest.update(file.relative_to(ROOT).as_posix().encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def marker(name):
    path = STATE / (name + ".json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def npm_command():
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not executable:
        raise RuntimeError("Node.js/npm is required on the publishing machine")
    return executable


def npm_install(folder):
    stamp = input_digest([folder / "package.json", folder / "package-lock.json"],
                         run(["node", "--version"], capture=True))
    name = "deps-" + folder.name
    if marker(name).get("digest") != stamp or not (folder / "node_modules").exists():
        run([npm_command(), "ci", "--no-audit", "--no-fund"], cwd=folder)
        atomic_json(STATE / (name + ".json"), {"digest": stamp})


def build_frontends():
    extension = ROOT / "extensions/whatsapp-translation"
    downloads = ROOT / "frontend/public/downloads/whatsapp-translation"
    stamp = input_digest([extension])
    packaged = STATE / "builds" / ("extension-" + stamp)
    if marker("extension").get("digest") != stamp or not (packaged / "latest.json").exists():
        npm_install(extension)
        run([npm_command(), "run", "package", "--", "--output", downloads], cwd=extension)
        shutil.copytree(downloads, packaged, dirs_exist_ok=True)
        atomic_json(STATE / "extension.json", {"digest": stamp, "files": static_sync.manifest(packaged, False)})
    elif static_sync.manifest(packaged, False) != marker("extension")["files"]:
        raise RuntimeError("Cached extension package is corrupt")
    shutil.copytree(packaged, downloads, dirs_exist_ok=True)
    outputs = {}
    node = run(["node", "--version"], capture=True)
    for name in ["frontend", "frontend-pm"]:
        folder = ROOT / name
        stamp = input_digest([folder], node)
        dist = STATE / "builds" / (name + "-" + stamp)
        if not (dist / "index.html").exists() or marker("build-" + name).get("digest") != stamp:
            npm_install(folder)
            run([npm_command(), "run", "build", "--", "--outDir", dist], cwd=folder)
            atomic_json(STATE / ("build-" + name + ".json"), {"digest": stamp, "files": static_sync.manifest(dist)})
        elif static_sync.manifest(dist) != marker("build-" + name)["files"]:
            raise RuntimeError("Cached build is corrupt: " + name)
        else:
            print(f"  {name}: unchanged, build skipped", flush=True)
        outputs[name] = dist
    return outputs


def build_lan():
    folder = ROOT / "frontend-pm"
    stamp = input_digest([folder], run(["node", "--version"], capture=True) + ":base=/pm/")
    dist = STATE / "builds" / ("pm-lan-" + stamp)
    if not (dist / "index.html").exists() or marker("build-pm-lan").get("digest") != stamp:
        npm_install(folder)
        run([npm_command(), "run", "build", "--", "--base=/pm/", "--outDir", dist], cwd=folder)
        atomic_json(STATE / "build-pm-lan.json", {"digest": stamp, "files": static_sync.manifest(dist)})
    elif static_sync.manifest(dist) != marker("build-pm-lan")["files"]:
        raise RuntimeError("Cached LAN build is corrupt")
    return dist


def publish(args):
    global ROOT
    import source_release
    live = ROOT
    with deployment_lock():
        ROOT, revision, previous = source_release.prepare(live, STATE, not args.no_pull)
        from office_release import prepare as office_prepare, activate as office_activate, stage_static
        office = None if args.cloud_only else office_prepare(live, previous, revision)
        inventory = json.loads((ROOT / "deploy/platforms.json").read_text(encoding="utf-8-sig"))
        if office:
            import schema_release
            schema_release.preflight(office, inventory, args.migration_credentials)
        journal = {"revision": revision, "scope": "cloud-only" if args.cloud_only else "office-and-cloud", "status": "preparing", "completed": [], "deferred": []}
        atomic_json(STATE / "publish-current.json", journal)
        outputs = build_frontends()
        if office:
            stage_static({**outputs, "pm-lan": build_lan()}, office)
        backend = cloud_backend.prepare(ROOT, revision, allow_pending=bool(office))
        prepared = []
        outputs["customer-media"] = outputs["frontend"] / "customer-media"
        for target in inventory["static_targets"]:
            if args.cloud_only and target.get("backend_owner") == "office":
                files = static_sync.manifest(outputs[target["component"]])
                comparison = static_sync.remote(target["host"], {"action": "plan", "root": target["root"], "manifest": files})
                if comparison["missing"]:
                    journal["deferred"].append(target["domain"] + ": changed frontend waits for matching office backend")
                    print("DEFERRED " + journal["deferred"][-1], flush=True)
                    atomic_json(STATE / "publish-current.json", journal)
                    continue
            prepared.append(static_sync.prepare(outputs[target["component"]], target["host"], target["root"],
                            STATE / "transfers", target["domain"]))
        if args.prepare_only:
            print("Prepared and verified; no service or live static pointer activated.")
            return
        journal["status"] = "activating"
        atomic_json(STATE / "publish-current.json", journal)
        stopped = schema_release.migrate(office, inventory, args.migration_credentials) if office else []
        if office:
            print(json.dumps(office_activate(office)), flush=True)
            journal["completed"].append("office")
            atomic_json(STATE / "publish-current.json", journal)
        print(json.dumps(cloud_backend.activate(revision)), flush=True)
        journal["completed"].append("beijing-backend")
        atomic_json(STATE / "publish-current.json", journal)
        if stopped:
            schema_release.resume_external(stopped, office)
        if office:
            with schema_release.database_lock(ROOT, office["python"]):
                schema_release.schema_check(ROOT, office["python"])
                run([office["python"], "scripts/seed_pm.py"], cwd=ROOT / "backend")
                run([office["python"], "scripts/import_pantone.py"], cwd=ROOT / "backend")
        for item in prepared:
            print(json.dumps(static_sync.activate(item)), flush=True)
            journal["completed"].append(item["target"] + ":" + item["request"]["root"])
            atomic_json(STATE / "publish-current.json", journal)
        summary = {"revision": revision, "scope": "cloud-only" if args.cloud_only else "office-and-cloud",
                   "schema": backend["schema"], "transfer_bytes": sum(item["bytes"] for item in prepared), "deferred": journal["deferred"]}
        atomic_json(STATE / "publish-success.json", summary)
        journal["status"] = "succeeded"
        atomic_json(STATE / "publish-current.json", journal)
        print("CLOUD RELEASE COMPLETED (office not included)" if args.cloud_only else "MANAGED APPLICATION RELEASE COMPLETED")
        print(json.dumps(summary), flush=True)
        print("Independent service and terminal installation coverage: deploy/platforms.json")
        for item in inventory["pending_targets"]:
            print("PENDING " + item["component"] + ": " + item["reason"])


if __name__ == "__main__":
    sys.modules["publish"] = sys.modules[__name__]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-only", action="store_true")
    parser.add_argument("--no-pull", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--migration-credentials", help="Protected file containing only DBA user/password; required only for pending DDL")
    try:
        publish(parser.parse_args())
    except Exception as error:
        if STATE.exists():
            journal = marker("publish-current")
            journal.update(status="failed", error_type=type(error).__name__)
            atomic_json(STATE / "publish-current.json", journal)
        print("DEPLOY FAILED: " + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
