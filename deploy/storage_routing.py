"""Prepare public file routes; activate only after COS application readiness."""

import json
from pathlib import Path

from static_sync import remote_python
from storage_upload_routes import snippet as upload_snippet

HERE = Path(__file__).resolve().parent
TARGETS = [("cloud", "ubuntu@154.8.205.162"), ("office", "root@119.28.107.92"), ("hair", "root@119.28.107.92"), ("video", "root@119.28.107.92")]
TARGETS.insert(1, ('cloud-ip', 'ubuntu@154.8.205.162'))


def remote(host, request, source=HERE):
    result = remote_python(host, source / "storage_routing_remote.py", request, sudo=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Storage routing failed")
    return json.loads(result.stdout)


def prepare(source=HERE):
    prepared = []
    for region, host in TARGETS:
        template = 'cloud' if region == 'cloud-ip' else region
        snippet = (source / "nginx" / f"storage-public-{template}.conf").read_text()
        snippet += '\n' + upload_snippet(region)
        payload = {"region": region, "snippet": snippet, "action": "prepare"}
        result = remote(host, payload, source)
        prepared.append({"host": host, "payload": {**payload, **result}})
    return prepared


def activate(item, source=HERE):
    return remote(item["host"], {**item["payload"], "action": "activate"}, source)


def execute(prepare_only, probe_plan):
    import publish

    with publish.deployment_lock():
        probes = json.loads(Path(probe_plan).read_text(encoding='utf-8'))
        if not isinstance(probes, list) or not all(isinstance(value, str) for value in probes):
            raise ValueError('Readiness probes must be a JSON string list')
        journal = {"status": "preparing", "completed": []}
        record = publish.STATE / "storage-routing.json"
        publish.atomic_json(record, journal)
        try:
            prepared = prepare()
            for item in prepared:
                item['payload']['probes'] = probes
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
        print(json.dumps({'status': journal['status'], 'prepared_regions': [item['payload']['region'] for item in prepared],
                          'completed': journal['completed']}))
