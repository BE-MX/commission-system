"""Close deferred maintenance only for the current verified publication."""
import json
from pathlib import Path
from static_retention import atomic_json, no_links


def complete(state, component, result):
    path = Path(state) / 'maintenance-pending.json'
    no_links(path)
    if not path.exists() or result.get('status') != 'succeeded':
        return
    pending = json.loads(path.read_text(encoding='utf-8'))
    current = json.loads((Path(state) / 'publish-current.json').read_text(encoding='utf-8'))
    if (current.get('status') != 'succeeded' or pending.get('revision') != current.get('revision')
            or pending.get('release_id') != current.get('release_id')):
        raise RuntimeError('Maintenance completion does not match current publication')
    if pending.get(component) is None:
        return
    pending[component] = dict(status='succeeded')
    pending['status'] = ('succeeded' if all(pending.get(k) is None or pending[k].get('status') == 'succeeded'
                        for k in ('static_retention', 'candidate_retention')) else 'pending')
    atomic_json(path, pending)
