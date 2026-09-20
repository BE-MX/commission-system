"""Transport the inspected finalization through the unified deployment entry."""
import json
from pathlib import Path
import subprocess
from static_sync import SSH_OPTIONS


def execute(plan_path, prepare_only):
    request = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    if set(request) != {'revision'}:
        raise ValueError('Finalize requires one reviewed revision')
    request['prepare_only'] = prepare_only
    target = 'D:/commission-system/.deploy_state/release_finalize.py'
    subprocess.run(['scp', *SSH_OPTIONS, str(Path(__file__).with_name('release_finalize.py')),
                    'office-prod:' + target], check=True, timeout=60)
    result = subprocess.run(['ssh', *SSH_OPTIONS, 'office-prod',
        'D:/commission-system/backend/.venv/Scripts/python.exe ' + target], input=json.dumps(request),
        text=True, timeout=1200)
    result.check_returncode()
