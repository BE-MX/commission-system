"""Write a verified office-and-cloud release using the candidate backend and its office settings."""
import json
import subprocess


def record(office, root, revision, release_id, scope):
    if not office or scope != "office-and-cloud":
        return {"status": "skipped"}

    request = {"revision": revision, "release_id": release_id, "scope": scope}
    result = subprocess.run(
        [str(office["python"]), "-m", "app.devlog.ledger_cli"],
        cwd=root / "backend",
        input=json.dumps(request),
        text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
    )
    if result.returncode:
        # Do not forward backend stderr. It may contain protected connection settings.
        print(f"WARNING devlog ledger not recorded (exit {result.returncode})", flush=True)
        return {"status": "failed", "error": f"exit {result.returncode}"}
    return {"status": "recorded"}
