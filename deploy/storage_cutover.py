"""Explicit, journalled COS steps; final receipts are collected while stopped."""
import json
from pathlib import Path
import re
import subprocess
from static_sync import SSH_OPTIONS

HOSTS = {
    'office': ('office-prod', 'D:/commission-system', 'backend/.venv/Scripts/python.exe'),
    'beijing': ('ubuntu@154.8.205.162', '/home/ubuntu/commission-system', 'backend/.venv/bin/python'),
}


def validate(plan):
    if plan.get('action') not in {'prepare', 'stop', 'configure', 'register', 'start'}:
        raise ValueError('Unknown COS phase')
    if not re.fullmatch(r'[0-9a-f]{40}', plan.get('revision', '')):
        raise ValueError('A full reviewed revision is required')
    for key in ['attempt', 'maintenance_attempt']:
        if not re.fullmatch(r'[a-z0-9-]{1,64}', plan.get(key, '')):
            raise ValueError('Invalid attempt identity')
    if plan['action'] in {'configure', 'register', 'start'} and not re.fullmatch(r'[0-9a-f]{64}', plan.get('receipts_sha256', '')):
        raise ValueError('Final immutable receipts are required')
    if plan['action'] in {'configure', 'register', 'start'} and not isinstance(plan.get('required_sources'), dict):
        raise ValueError('Reviewed domain and source matrix is required')


def host(instance, request):
    target, root, python = HOSTS[instance]
    script = root + '/.deploy_state/storage-cutover-host.py'
    subprocess.run(['scp', *SSH_OPTIONS, str(Path(__file__).with_name('storage_cutover_host.py')),
                    target + ':' + script], check=True, timeout=60)
    command = root + '/' + python + ' ' + script
    if instance == 'beijing':
        command = 'sudo -n ' + command
    result = subprocess.run(['ssh', *SSH_OPTIONS, target, command],
                            input=json.dumps(request), text=True, capture_output=True, timeout=900)
    if result.returncode:
        raise RuntimeError(instance + ': ' + result.stderr[-1000:])
    return json.loads(result.stdout.splitlines()[-1])


def execute(plan_path, prepare_only=False):
    import publish
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    validate(plan)
    if prepare_only:
        plan['action'] = 'prepare'
    with publish.deployment_lock():
        # No database/configuration changes while either file writer is active.
        if plan['action'] in {'configure', 'register'}:
            for instance in HOSTS:
                host(instance, {**plan, 'action': 'assert-stopped'})
        if plan['action'] == 'start':
            proof = host('office', {**plan, 'action': 'inspect'})
            if proof.get('status') not in {'registered', 'starting', 'started'} or proof.get('receipts_sha256') != plan['receipts_sha256']:
                raise RuntimeError('Shared reference transaction is not confirmed')
            for instance in HOSTS:
                host(instance, {**plan, 'action': 'validate-start'})
        order = ['beijing', 'office']
        if plan['action'] == 'register':
            order = ['office']
        for instance in order:
            result = host(instance, plan)
            print(json.dumps({'instance': instance, **result}), flush=True)
            publish.atomic_json(publish.STATE / ('storage-cutover-' + instance + '.json'),
                                {'attempt': plan['attempt'], 'phase': plan['action'], 'result': result})
