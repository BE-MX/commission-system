"""Explicit maintenance stages, invoked only via deploy.bat."""
import json
from pathlib import Path
import subprocess
from static_sync import remote_python, SSH_OPTIONS


def execute(plan_path, prepare_only=False):
    import publish
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    if set(plan) != {'attempt', 'action'} or plan['action'] not in {'freeze', 'restore'}:
        raise ValueError('Maintenance plan requires attempt and freeze/restore action')
    with publish.deployment_lock():
        for region, host in [('singapore', publish.SG), ('beijing', publish.BJ)]:
            result = remote_python(host, Path(__file__).with_name('storage_maintenance_remote.py'),
                {**plan, 'region': region, 'action': 'prepare' if prepare_only else plan['action']}, sudo=True)
            if result.returncode:
                raise RuntimeError('Maintenance failed for ' + region + ': ' + result.stderr[-1000:])
            print(result.stdout.strip(), flush=True)
        target = 'D:/commission-system/.deploy_state/storage-maintenance-office.py'
        subprocess.run(['scp', *SSH_OPTIONS, str(Path(__file__).with_name('storage_maintenance_office.py')),
                        'office-prod:' + target], check=True, timeout=60)
        result = subprocess.run(['ssh', *SSH_OPTIONS, 'office-prod',
            'D:/commission-system/backend/.venv/Scripts/python.exe ' + target],
            input=json.dumps({**plan, 'action': 'prepare' if prepare_only else plan['action']}),
            text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError('Office maintenance failed: ' + result.stderr[-1000:])
        print(result.stdout.strip(), flush=True)
