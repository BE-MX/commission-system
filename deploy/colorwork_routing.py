"""Route both public Ark sites to the single Beijing workbench owner."""

import json
from pathlib import Path

from static_sync import remote_python

HERE = Path(__file__).resolve().parent
TARGETS = [("cloud", "ubuntu@154.8.205.162"), ("office", "root@119.28.107.92")]


def remote(host, request, source=HERE):
    result = remote_python(host, source / "colorwork_routing_remote.py", request, sudo=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Colorwork routing failed")
    return json.loads(result.stdout)


def prepare(source=HERE):
    prepared = []
    for region, host in TARGETS:
        snippet = (source / "nginx" / f"colorwork-{region}.conf").read_text()
        payload = {"region": region, "snippet": snippet, "action": "prepare"}
        result = remote(host, payload, source)
        prepared.append({"host": host, "payload": {**payload, **result}})
    return prepared


def activate(item, source=HERE):
    return remote(item["host"], {**item["payload"], "action": "activate"}, source)


def execute(prepare_only):
    import publish

    with publish.deployment_lock():
        journal = {"status": "preparing", "completed": []}
        record = publish.STATE / "colorwork-routing.json"
        publish.atomic_json(record, journal)
        try:
            prepared = prepare()
            journal.update(status="prepared", prepared=prepared)
            publish.atomic_json(record, journal)
            if not prepare_only:
                for item in prepared:
                    journal["completed"].append(activate(item))
                    publish.atomic_json(record, journal)
                journal["status"] = "activated"
                publish.atomic_json(record, journal)
        except Exception:
            journal["status"] = "failed"
            publish.atomic_json(record, journal)
            raise
        print(json.dumps(journal))
