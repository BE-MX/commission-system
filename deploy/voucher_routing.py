"""Publish only the two voucher routes through deploy.bat."""

import json
from pathlib import Path

from static_sync import remote_python

HERE = Path(__file__).resolve().parent
TARGETS = [("office", "root@119.28.107.92"), ("cloud", "ubuntu@154.8.205.162")]


def remote(host, request):
    result = remote_python(host, HERE / "voucher_routing_remote.py", request, sudo=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Voucher routing failed")
    return json.loads(result.stdout)


def execute(prepare_only):
    import publish

    with publish.deployment_lock():
        journal = {"status": "preparing", "completed": []}
        record = publish.STATE / "voucher-routing.json"
        publish.atomic_json(record, journal)
        try:
            prepared = []
            for region, host in TARGETS:
                snippet = (HERE / "nginx" / f"domestic-voucher-{region}.conf").read_text()
                payload = {"region": region, "snippet": snippet, "action": "prepare"}
                result = remote(host, payload)
                prepared.append((host, payload, result))
            journal.update(status="prepared", prepared=[item[2] for item in prepared])
            publish.atomic_json(record, journal)
            if not prepare_only:
                # Office first: its unchanged file ownership is also safe if Beijing fails.
                for host, payload, result in prepared:
                    activated = remote(host, {**payload, **result, "action": "activate"})
                    journal["completed"].append(activated)
                    publish.atomic_json(record, journal)
                journal["status"] = "activated"
                publish.atomic_json(record, journal)
        except Exception:
            journal["status"] = "failed"
            publish.atomic_json(record, journal)
            raise
        print(json.dumps(journal))
