"""Maintenance through deploy.bat, under the same lock as application publication."""

import json
from pathlib import Path

import office_static_retention
import static_sync
from static_retention import atomic_json


def run(live, source, prepare_only=False, include_office=True):
    live, source = Path(live), Path(source)
    state = live / '.deploy_state'
    journal = json.loads((state / 'publish-current.json').read_text(encoding='utf-8'))
    if journal.get('status') != 'succeeded':
        raise RuntimeError('Static retention refuses an unfinished application release')
    inventory = json.loads((source / 'deploy/platforms.json').read_text(encoding='utf-8-sig'))
    targets = [target for target in inventory['static_targets'] if target['component'] == 'frontend']
    results = {'status': 'prepared', 'completed': [], 'targets': {}}
    if include_office:
        from office_release import health
        health(8001)
        results['targets']['office'] = office_static_retention.cleanup(live, True)
    rollback_hints = results['targets'].get('office', {}).get('rollback_artifacts', [])
    for target in targets:
        results['targets'][target['domain']] = static_sync.remote(target['host'], {
            'action': 'retention', 'root': target['root'], 'host': target['domain'],
            'prepare_only': True, 'rollback_hints': rollback_hints})
    receipt = state / 'static-retention-current.json'
    atomic_json(receipt, results)
    print(json.dumps(results), flush=True)
    if prepare_only:
        return results
    try:
        results['status'] = 'cleaning'
        atomic_json(receipt, results)
        if include_office:
            from office_release import health
            health(8001)
            results['targets']['office'] = office_static_retention.cleanup(live)
            results['completed'].append('office')
            atomic_json(receipt, results)
        for target in targets:
            results['targets'][target['domain']] = static_sync.remote(target['host'], {
                'action': 'retention', 'root': target['root'], 'host': target['domain'],
                'prepare_only': False, 'rollback_hints': rollback_hints})
            results['completed'].append(target['domain'])
            atomic_json(receipt, results)
        if include_office:
            health(8001)
        results['status'] = 'succeeded'
        atomic_json(receipt, results)
    except Exception as error:
        results.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        atomic_json(receipt, results)
        raise
    return results


def execute(args, live, source, deployment_lock):
    allowed = {'static_retention_only', 'prepare_only', 'revision', 'live_root', 'no_pull'}
    if any(value for key, value in vars(args).items() if key not in allowed):
        raise RuntimeError('Static retention only accepts a pinned candidate and --prepare-only')
    import subprocess
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip()
    if args.revision != actual or dirty:
        raise RuntimeError('Static retention requires the clean pinned candidate')
    with deployment_lock():
        from schema_release import check_recovery
        check_recovery()
        return run(live, source, args.prepare_only)
