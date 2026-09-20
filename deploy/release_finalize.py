"""Finish static/routes only after verified successful post-DDL backend activation."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys


def validate(journal, migration, office, revision, current, cloud, office_dirty='', cloud_dirty=''):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Expected reviewed full revision')
    if office_dirty or cloud_dirty:
        raise RuntimeError('Tracked runtime source differs from reviewed release')
    if journal.get('status') != 'failed' or journal.get('revision') != revision:
        raise RuntimeError('Only the inspected failed release may be finalized')
    if not {'office', 'beijing-backend'} <= set(journal.get('completed', [])):
        raise RuntimeError('Both backend activations must already be recorded')
    if migration.get('status') != 'upgraded' or migration.get('schema') != '159_storage_transfers':
        raise RuntimeError('Expected inspected successful schema 159 migration')
    if current != revision or cloud != revision or office.get('revision') != revision or office.get('schema') != migration['schema']:
        raise RuntimeError('Runtime versions differ from the activated release')


def execute(request):
    root = Path('D:/commission-system')
    git = shutil.which('git')
    ssh_folder = Path(git).parent.parent / 'usr/bin' if git else None
    if ssh_folder is None or not (ssh_folder / 'ssh.exe').is_file():
        raise RuntimeError('Verified Git SSH runtime is unavailable')
    os.environ['PATH'] = str(ssh_folder) + os.pathsep + os.environ.get('PATH', '')
    sys.path.insert(0, str(root / 'deploy'))
    import publish as p
    import schema_release as schema
    import office_release
    import colorwork_routing
    import static_sync
    with p.deployment_lock():
        journal = p.marker('publish-current')
        migration = p.marker('schema-writers')
        office = p.marker('office-success')
        revision = request['revision']
        current = p.run(['git', 'rev-parse', 'HEAD'], capture=True)
        cloud = p.run(['ssh', *static_sync.SSH_OPTIONS, p.BJ,
                       'git -C /home/ubuntu/commission-system rev-parse HEAD'], capture=True)
        dirty = p.run(['git', 'status', '--porcelain', '--untracked-files=no'], capture=True)
        cloud_dirty = p.run(['ssh', *static_sync.SSH_OPTIONS, p.BJ,
                       'git -C /home/ubuntu/commission-system status --porcelain --untracked-files=no'], capture=True)
        validate(journal, migration, office, revision, current, cloud, dirty, cloud_dirty)
        nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
        python = p.run([nssm, 'get', 'CommissionSystem', 'Application'], capture=True)
        if Path(python).name.lower() != 'python.exe':
            raise RuntimeError('Unexpected runtime executable')
        checked = schema.schema_check(root, python)
        office_release.health(8001)
        for writer in migration['writers']:
            if schema.writer_state(writer['writer'], nssm) != writer['before']:
                raise RuntimeError('Writer baseline has not recovered')
        if request.get('prepare_only'):
            return {'status': 'prepared', 'revision': revision, 'schema': checked}
        backup = p.STATE / ('finalize-original-' + revision + '.json')
        if not backup.exists():
            p.atomic_json(backup, {'publish': journal, 'migration': migration})
        candidate = root / '.deploy_state/sources' / revision
        if p.run(['git', 'rev-parse', 'HEAD'], cwd=candidate, capture=True) != revision or p.run(
                ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=candidate, capture=True):
            raise RuntimeError('Prepared candidate source drift')
        # The installed checkout intentionally keeps its original node_modules;
        # build/cache preparation belongs to the reviewed candidate, as in publish.
        p.ROOT = candidate
        outputs = p.build_frontends()
        if p.run(['git', 'status', '--porcelain', '--untracked-files=no'], capture=True):
            raise RuntimeError('Source changed while preparing finalization')
        for item in colorwork_routing.prepare():
            result = colorwork_routing.activate(item)
            journal['completed'].append('colorwork-routing:' + result['region'])
            p.atomic_json(p.STATE / 'publish-current.json', journal)
        with schema.database_lock(root, python):
            schema.schema_check(root, python)
            p.run([python, 'scripts/seed_pm.py'], cwd=root / 'backend')
            p.run([python, 'scripts/import_pantone.py'], cwd=root / 'backend')
        inventory = json.loads((root / 'deploy/platforms.json').read_text(encoding='utf-8-sig'))
        outputs['customer-media'] = outputs['frontend'] / 'customer-media'
        transferred = 0
        for target in inventory['static_targets']:
            item = static_sync.prepare(outputs[target['component']], target['host'], target['root'],
                                       p.STATE / 'transfers', target['domain'])
            result = static_sync.activate(item)
            print(json.dumps(result), flush=True)
            transferred += item['bytes']
            journal['completed'].append(item['target'] + ':' + item['request']['root'])
            p.atomic_json(p.STATE / 'publish-current.json', journal)
        schema.complete({'schema_changed': True, 'schema': migration['schema']})
        p.atomic_json(p.STATE / 'publish-success.json', {'revision': revision,
            'scope': 'office-and-cloud', 'schema': checked, 'transfer_bytes': transferred, 'deferred': []})
        journal.update(status='succeeded', recovered_from='colorwork-health-maintenance-503')
        p.atomic_json(p.STATE / 'publish-current.json', journal)
        return {'status': 'succeeded', 'revision': revision, 'schema': checked}


if __name__ == '__main__':
    print(json.dumps(execute(json.load(sys.stdin))))
