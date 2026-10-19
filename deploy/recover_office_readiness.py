"""Restore an inspected no-DDL rollback, then resume its original release binding."""
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil


def validate(plan, journal, success, current):
    if (set(plan) != {'previous', 'revision', 'release_id', 'schema', 'journal_sha256', 'service', 'service_state'}
            or any(not re.fullmatch(r'[0-9a-f]{40}', plan[k]) for k in ('previous', 'revision'))
            or not re.fullmatch(r'[0-9a-f]{32}', plan['release_id'])
            or not re.fullmatch(r'[0-9a-f]{64}', plan['journal_sha256'])
            or plan['service_state'] not in {'SERVICE_STOPPED', 'SERVICE_RUNNING'}
            or set(plan['service']) != {'Application', 'AppDirectory', 'AppParameters'}
            or current != plan['previous'] or success.get('revision') != current
            or success.get('schema') != plan['schema']
            or journal.get('status') != 'failed'
            or journal.get('completed') not in ([], ['office'], ['office', 'beijing-backend'])
            or (journal.get('completed') and (current != plan['revision'] or plan['service_state'] != 'SERVICE_RUNNING'))
            or journal.get('scope') != 'office-and-cloud'
            or journal.get('revision') != plan['revision'] or journal.get('release_id') != plan['release_id']):
        raise RuntimeError('Recovery does not match the inspected no-DDL rollback')
    outbound = journal.get('outbound', {})
    if (outbound.get('status') != 'installed_paused' or outbound.get('mode') != 'legacy'
            or outbound.get('revision') != plan['revision'] or outbound.get('release_id') != plan['release_id']):
        raise RuntimeError('Original paused outbound binding is required')


def execute(plan_path, args):
    import publish as p
    import office_release as office
    from remote_backend import database_lock, schema_check, protocol_observation, rollback_guard
    from static_sync import manifest
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8-sig'))
    live, state = p.ROOT, p.STATE
    receipt = state / ('office-readiness-recovery-' + plan['release_id'] + '-' + plan['journal_sha256'][:12] + '.json')
    restore_only = getattr(args, 'restore_service_only', False)
    if restore_only:
        receipt = receipt.with_name(receipt.stem + '-service-only.json')
    source = state / 'sources' / plan['revision']
    with p.deployment_lock():
        raw = (state / 'publish-current.json').read_bytes()
        journal = json.loads(raw)
        if hashlib.sha256(raw).hexdigest() != plan['journal_sha256']:
            raise RuntimeError('Failed release journal changed')
        validate(plan, journal, p.marker('office-success'),
            p.run(['git', 'rev-parse', 'HEAD'], cwd=live, capture=True))
        if receipt.exists():
            raise RuntimeError('Recovery already attempted; inspect its receipt before retrying')
        legacy_receipt = state / ('office-readiness-recovery-' + plan['release_id'] + '.json')
        if legacy_receipt.exists():
            old_hash = json.loads(legacy_receipt.read_text(encoding='utf-8'))['plan']['journal_sha256']
            if not re.fullmatch(r'[0-9a-f]{64}', old_hash) or old_hash == plan['journal_sha256']:
                raise RuntimeError('Recovery already attempted; inspect its legacy receipt before retrying')
        for root, revision in ((live, plan['previous']), (source, plan['revision'])):
            if (p.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture=True) != revision
                    or p.run(['git', 'status', '--porcelain'], cwd=root, capture=True)):
                raise RuntimeError('Recovery checkout drift')
        nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
        get = lambda key: p.run([nssm, 'get', 'CommissionSystem', key], capture=True)
        if {key: get(key) for key in plan['service']} != plan['service']:
            raise RuntimeError('Restored service command drift')
        if (Path(get('AppDirectory')).resolve() != (live / 'backend').resolve()
                or Path(get('Application')).name.lower() != 'python.exe'
                or get('AppParameters') != '-m uvicorn app.main:app --host 0.0.0.0 --port 8001'):
            raise RuntimeError('Unexpected office service command')
        python = get('Application')
        for name, folder in [('frontend', 'frontend/dist'), ('frontend-pm', 'frontend-pm/dist'), ('pm-lan', 'frontend-pm/dist-lan')]:
            expected = p.marker('office-' + name).get('files')
            actual = manifest(live / folder)
            if not expected or any(actual.get(k) != v for k, v in expected.items()):
                raise RuntimeError('Restored office static content drift')
        with database_lock(source, python):
            for root in (live, source):
                facts = schema_check(root, python)
                if facts['schema'] != plan['schema'] or facts['pending']:
                    raise RuntimeError('Recovery requires unchanged schema and no pending migration')
            observation = protocol_observation(source, python)
            if observation != {key: journal['outbound'][key] for key in ('mode', 'database_fingerprint')}:
                raise RuntimeError('Original database protocol changed')
            if p.run([nssm, 'status', 'CommissionSystem'], capture=True) != plan['service_state']:
                raise RuntimeError('Office service state drift')
            if args.prepare_only:
                return {'status': 'prepared', 'revision': plan['revision']}
            p.atomic_json(receipt, {'status': 'starting', 'original': journal, 'plan': plan})
            try:
                with rollback_guard(source, python, observation) as guard:
                    if plan['service_state'] == 'SERVICE_STOPPED':
                        p.run([nssm, 'start', 'CommissionSystem'])
                    office.wait_ready(8001, nssm, ['CommissionSystem'])
                    guard.check()
            except Exception:
                if plan['service_state'] == 'SERVICE_STOPPED':
                    p.run([nssm, 'stop', 'CommissionSystem'])
                    if p.run([nssm, 'status', 'CommissionSystem'], capture=True) != 'SERVICE_STOPPED':
                        raise RuntimeError('Office recovery stop unconfirmed') from None
                p.atomic_json(receipt, {'status': 'health_failed', 'original_state': plan['service_state'], 'original': journal, 'plan': plan})
                raise
            p.atomic_json(receipt, {'status': 'old_service_restored', 'original': journal, 'plan': plan})
        if restore_only:
            resume_plan = dict(plan, service_state='SERVICE_RUNNING')
            resume_path = state / ('resume-office-' + plan['release_id'] + '-' + plan['journal_sha256'][:12] + '.json')
            p.atomic_json(resume_path, resume_plan)
            return {'status': 'old_service_restored', 'revision': plan['previous'],
                    'release_status': 'pending', 'resume_plan': str(resume_path)}
    # Retain the original SHA and release_id so remote paused-stage journals keep
    # their pre-freeze baselines. The normal publisher performs every release step.
    resumed = copy.copy(args)
    resumed._readiness_checkpoint = plan
    resumed.recover_office_readiness = None
    resumed.revision, resumed.no_pull = plan['revision'], True
    office.ROOT = source
    result = p.publish(resumed)
    p.atomic_json(receipt, {'status': 'original_release_completed', 'original': journal, 'plan': plan})
    return result
