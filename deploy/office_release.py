"""Office release: prepare dependencies first; keep all business storage in place."""

import json
import os
from pathlib import Path
import re
import shutil
import time
import urllib.request

from publish import ROOT, STATE, atomic_json, input_digest, marker, npm_command, run
from remote_backend import schema_check, database_lock
from static_sync import manifest
from remote_static import retain_assets


def health(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=8) as response:
        result = json.load(response)
    if result.get("status") != "ok" or result.get("database") != "connected":
        raise RuntimeError("Office HTTP/database readiness failed")


def prepare(live, previous, revision):
    if os.name != "nt":
        raise RuntimeError("Full release runs on the office Windows server")
    nssm = shutil.which("nssm") or str(Path.home() / "AppData/Local/Microsoft/WinGet/Links/nssm.exe")
    if not Path(nssm).exists():
        raise RuntimeError("Office NSSM unavailable; use --cloud-only for an explicitly partial release")
    def get(service, key):
        return run([nssm, "get", service, key], capture=True)
    directory = Path(get("CommissionSystem", "AppDirectory"))
    if directory.resolve() != (live / "backend").resolve():
        raise RuntimeError("Run full deployment from the installed office service checkout")
    application = Path(get("CommissionSystem", "Application"))
    parameters = get("CommissionSystem", "AppParameters")
    port = re.search(r"--port[ =]+(\d+)", parameters)
    if not port or application.name.lower() not in {"python.exe", "uvicorn.exe"}:
        raise RuntimeError("Unrecognized office service command/port")
    current_python = application.parent / "python.exe"
    if not current_python.exists():
        raise RuntimeError("Office Python executable missing")
    health(int(port.group(1)))
    requirements = ROOT / "backend/requirements.txt"
    stamp = input_digest([requirements], run([current_python, "--version"], capture=True))
    candidate = STATE / "python-envs" / stamp
    python = current_python
    requirements_changed = requirements.read_bytes() != (live / "backend/requirements.txt").read_bytes()
    if requirements_changed:
        ready = candidate / ".ark-ready"
        if not ready.exists():
            if not candidate.exists():
                candidate.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(current_python.parent.parent, candidate)
            python = candidate / "Scripts/python.exe"
            prefix = run([python, "-c", "import sys;print(sys.prefix)"], capture=True)
            if Path(prefix).resolve() != candidate.resolve():
                raise RuntimeError("Candidate Python is not isolated")
            run([python, "-m", "pip", "install", "-r", requirements], cwd=ROOT / "backend")
            run([python, "-m", "pip", "check"], cwd=ROOT / "backend")
            ready.write_text(stamp)
        python = candidate / "Scripts/python.exe"
    schema = schema_check(ROOT, python, allow_pending=True)
    run([python, "-m", "app.invoice.pdf_font"], cwd=ROOT / "backend")
    run([python, "-m", "scripts.check_design_image_document_render"], cwd=ROOT / "backend")
    run([python, "-c", "import app.routers"], cwd=ROOT / "backend")
    changes = run(["git", "diff", "--name-only", previous, revision], cwd=live, capture=True).splitlines()
    connector_changed = any(name.startswith("services/whatsapp-connector/") for name in changes)
    connector = ROOT / "services/whatsapp-connector"
    if Path(get("WhatsAppConnector", "AppDirectory")).resolve() != (live / "services/whatsapp-connector").resolve():
        raise RuntimeError("Connector service directory differs from registered checkout")
    if connector_changed:
        run([npm_command(), "ci", "--no-audit", "--no-fund"], cwd=connector)
        run([npm_command(), "run", "check"], cwd=connector)
    return {"nssm": nssm, "python": python, "application": application, "parameters": parameters,
            "port": int(port.group(1)), "schema": schema["schema"], "pending": schema["pending"], "live": live,
            "previous": previous, "revision": revision, "connector_changed": connector_changed,
            "backend_changed": any(n.startswith(("backend/", "config/")) for n in changes)}


def stage_static(outputs, prepared):
    changes = []
    for name, dist in outputs.items():
        folder, leaf = ("frontend-pm", "dist-lan") if name == "pm-lan" else (name, "dist")
        destination = prepared["live"] / folder / leaf
        files = manifest(dist)
        current = manifest(destination) if (destination / "index.html").exists() else {}
        if all(current.get(k) == v for k, v in files.items()) and marker("office-" + name).get("files") == files:
            continue
        staged = STATE / ("office-next-" + name + "-" + str(time.time_ns()))
        shutil.copytree(dist, staged)
        retain_assets(destination, staged)
        changes.append((name, destination, staged, files))
    prepared["static"] = changes


def activate(prepared):
    with database_lock(ROOT, prepared["python"]):
        schema_check(ROOT, prepared["python"])
        return activate_locked(prepared)


def activate_locked(prepared):
    nssm, live = prepared["nssm"], prepared["live"]
    revision, previous = prepared["revision"], prepared["previous"]
    if run(["git", "rev-parse", "HEAD"], cwd=live, capture=True) != previous:
        raise RuntimeError("Office checkout changed after preparation")
    backend_changed = prepared["backend_changed"] or bool(prepared["static"]) or prepared.get("schema_changed", False)
    connector_changed = prepared["connector_changed"]
    if not backend_changed and not connector_changed:
        health(prepared["port"])
        run(["git", "merge", "--ff-only", revision], cwd=live)
        return {"status": "unchanged", "revision": revision}
    backups = []
    services = (["CommissionSystem"] if backend_changed else []) + (["WhatsAppConnector"] if connector_changed or prepared.get("schema_changed") else [])
    # Stopping is inside the recovery block: a partial stop must not strand services.
    try:
        for service in services:
            if run([nssm, "status", service], capture=True) != "SERVICE_STOPPED":
                run([nssm, "stop", service])
        if connector_changed:
            destination = live / "services/whatsapp-connector/node_modules"
            staged = ROOT / "services/whatsapp-connector/node_modules"
            backup = STATE / ("connector-deps-" + str(time.time_ns()))
            if destination.exists():
                destination.rename(backup)
            backups.append((destination, backup))
            staged.rename(destination)
        for name, destination, staged, files in prepared["static"]:
            backup = STATE / ("office-previous-" + name + "-" + str(time.time_ns()))
            if destination.exists():
                destination.rename(backup)
            backups.append((destination, backup))
            staged.rename(destination)
        run(["git", "merge", "--ff-only", revision], cwd=live)
        if backend_changed:
            parameters = prepared["parameters"]
            if prepared["application"].name.lower() == "uvicorn.exe":
                parameters = "-m uvicorn " + parameters
            run([nssm, "set", "CommissionSystem", "Application", prepared["python"]])
            run([nssm, "set", "CommissionSystem", "AppParameters", parameters])
        for service in services:
            run([nssm, "start", service])
        for attempt in range(15):
            try:
                health(prepared["port"])
                if any(run([nssm, "status", s], capture=True) != "SERVICE_RUNNING" for s in services):
                    raise RuntimeError("Office service not running")
                break
            except Exception as error:
                print("Office readiness retry:", type(error).__name__, flush=True)
                if attempt == 14:
                    raise
                time.sleep(2)
    except Exception:
        for service in services:
            if run([nssm, "status", service], capture=True) != "SERVICE_STOPPED":
                run([nssm, "stop", service])
        if prepared.get("schema_changed"):
            raise RuntimeError("Office activation failed after schema change; writers held stopped, no automatic code downgrade") from None
        run(["git", "reset", "--keep", previous], cwd=live)
        for destination, backup in reversed(backups):
            if destination.exists():
                destination.rename(STATE / ("office-failed-" + str(time.time_ns())))
            if backup.exists():
                backup.rename(destination)
        run([nssm, "set", "CommissionSystem", "Application", prepared["application"]])
        run([nssm, "set", "CommissionSystem", "AppParameters", prepared["parameters"]])
        for service in services:
            run([nssm, "start", service])
        raise
    for name, _, _, files in prepared["static"]:
        atomic_json(STATE / ("office-" + name + ".json"), {"files": files})
    atomic_json(STATE / "office-success.json", {"revision": revision, "previous": previous,
                "schema": prepared["schema"], "backups": [[str(a), str(b)] for a, b in backups]})
    return {"status": "updated", "revision": revision}
