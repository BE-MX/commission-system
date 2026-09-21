"""Recover only the inspected schema-160 dependency-order interruption."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys


REVISION = 'd021ece8b5fbe261fe95cb6f48ef87def85fedfc'
SCHEMA = '160_domestic_price_review'


def validate(journal, migration, office, revision, current, cloud, office_dirty='', cloud_dirty=''):
    if revision != REVISION or current != revision or office_dirty or cloud_dirty:
        raise RuntimeError('Unrecognized or changed release source')
    if journal.get('status') != 'failed' or journal.get('revision') != revision or journal.get('completed') != ['office']:
        raise RuntimeError('Original release must have failed after office activation only')
    if migration.get('status') != 'upgraded' or migration.get('schema') != SCHEMA or migration.get('pending') != [SCHEMA] or migration.get('database') != '159_storage_transfers':
        raise RuntimeError('Unrecognized original schema-160 migration')
    if office.get('revision') != revision or office.get('schema') != SCHEMA:
        raise RuntimeError('Office is not the successfully activated candidate')
    if cloud not in {revision, 'fea48d6c22937f3064a40546292ea4e03927d2b9'}:
        raise RuntimeError('Unexpected Beijing source')


def execute(request):
    os.environ['PYTHONUTF8'] = '1'
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
        archive = p.STATE / ('start-order-original-' + revision + '.json')
        original = json.loads(archive.read_text()) if archive.exists() else {'publish': journal, 'migration': migration}
        validate(original['publish'], original['migration'], office, revision, current, cloud, dirty, cloud_dirty)
        if migration != original['migration'] or journal.get('revision') != revision or journal.get('status') != 'failed':
            raise RuntimeError('Current recovery evidence changed')
        inventory = json.loads((root / 'deploy/platforms.json').read_text(encoding='utf-8-sig'))
        writers = schema.validate(inventory, True)
        baseline = migration['writers']
        if [row['writer'] for row in baseline] != writers or migration['stopped'] != writers or any(row['before'] != 'running' for row in baseline):
            raise RuntimeError('Original writer inventory/baseline differs')
        nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
        python = p.run([nssm, 'get', 'CommissionSystem', 'Application'], capture=True)
        if Path(python).name.lower() != 'python.exe':
            raise RuntimeError('Unexpected runtime executable')
        checked = schema.schema_check(root, python)
        office_release.health(8001)
        if checked != {'schema': SCHEMA, 'database': SCHEMA, 'pending': []}:
            raise RuntimeError('Actual schema differs from the inspected successful migration')
        remote_script = Path(__file__).with_name('recover_colorwork_order_remote.py')
        result = static_sync.remote_python(p.BJ, remote_script, {'revision': revision, 'prepare_only': True}, timeout=180)
        if result.returncode:
            raise RuntimeError(result.stderr[-4000:])
        if request.get('prepare_only'):
            return {'status': 'prepared', 'revision': revision, 'schema': checked}
        if not archive.exists():
            p.atomic_json(archive, original)
        result = static_sync.remote_python(p.BJ, remote_script, {'revision': revision}, timeout=900)
        if result.returncode:
            raise RuntimeError(result.stderr[-4000:])
        if 'beijing-backend' not in journal['completed']:
            journal['completed'].append('beijing-backend')
        p.atomic_json(p.STATE / 'publish-current.json', journal)
        schema.resume_external(migration['stopped'], {'python': python, 'nssm': nssm})
        for writer in baseline:
            if schema.writer_state(writer['writer'], nssm) != writer['before']:
                raise RuntimeError('Writer baseline has not recovered')
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
        journal.update(status='succeeded', recovered_from=str(archive))
        p.atomic_json(p.STATE / 'publish-current.json', journal)
        return {'status': 'succeeded', 'revision': revision, 'schema': checked}


if __name__ == '__main__':
    print(json.dumps(execute(json.load(sys.stdin))))
