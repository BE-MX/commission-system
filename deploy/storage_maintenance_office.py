"""Block direct LAN entry without interrupting backend daemon work."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

RULE = 'ArkStorageMaintenance8001'
STATE = Path('D:/commission-system/.deploy_state/storage-maintenance')


def run(args):
    return subprocess.check_output(args, text=True, errors='replace').strip()


def ps(code):
    return run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                "$ErrorActionPreference='Stop'; " + code])


def check_rule():
    code = f"$r=Get-NetFirewallRule -Name '{RULE}' -ErrorAction SilentlyContinue; if ($r) {{ $p=$r | Get-NetFirewallPortFilter; if ($r.Direction -ne 'Inbound' -or $r.Action -ne 'Block' -or $r.Enabled -ne 'True' -or $r.Profile -ne 'Any' -or $p.Protocol -ne 'TCP' -or $p.LocalPort -ne '8001') {{ throw 'Maintenance firewall rule drift' }}; 'True' }} else {{ 'False' }}"
    return ps(code) == 'True'


def execute(plan):
    if plan['action'] not in {'prepare', 'freeze', 'restore'} or not re.fullmatch(r'[a-z0-9-]{1,64}', plan['attempt']):
        raise ValueError('Invalid maintenance operation')
    nssm = shutil.which('nssm') or str(Path.home() / 'AppData/Local/Microsoft/WinGet/Links/nssm.exe')
    state = STATE / plan['attempt']
    record = state / 'office.json'
    before = run([nssm, 'status', 'ArkOfficeHttps'])
    if before not in {'SERVICE_RUNNING', 'SERVICE_STOPPED'}:
        raise RuntimeError('LAN proxy is not stable')
    present = check_rule()
    if plan['action'] == 'prepare':
        if present or record.exists():
            raise RuntimeError('Existing maintenance must be inspected')
        return {'status': 'prepared', 'office_https': before}
    if plan['action'] == 'freeze':
        if present or record.exists():
            raise RuntimeError('Existing maintenance must be inspected')
        state.mkdir(parents=True, exist_ok=True)
        data = {'status': 'freezing', 'https_before': before}
        record.write_text(json.dumps(data))
        try:
            ps(f"New-NetFirewallRule -Name '{RULE}' -DisplayName '{RULE}' -Direction Inbound -Action Block -Protocol TCP -LocalPort 8001 -Profile Any | Out-Null")
            if before == 'SERVICE_RUNNING':
                run([nssm, 'stop', 'ArkOfficeHttps'])
            if run([nssm, 'status', 'ArkOfficeHttps']) != 'SERVICE_STOPPED' or not check_rule():
                raise RuntimeError('LAN ingress freeze incomplete')
            data['status'] = 'frozen'
            record.write_text(json.dumps(data))
        except Exception:
            # The saved baseline authorizes recovery even if a command changed
            # state but failed before it could report success.
            execute({**plan, 'action': 'restore'})
            raise
    else:
        data = json.loads(record.read_text())
        if data['status'] not in {'freezing', 'frozen', 'restoring'}:
            raise RuntimeError('Maintenance state differs; inspect before restoring')
        data['status'] = 'restoring'
        record.write_text(json.dumps(data))
        if data['https_before'] == 'SERVICE_RUNNING':
            if before != 'SERVICE_RUNNING':
                run([nssm, 'start', 'ArkOfficeHttps'])
        if run([nssm, 'status', 'ArkOfficeHttps']) != data['https_before']:
            raise RuntimeError('LAN proxy baseline was not restored')
        if present:
            ps(f"Remove-NetFirewallRule -Name '{RULE}'")
        data['status'] = 'restored'
    record.write_text(json.dumps(data))
    return {'status': data['status'], 'region': 'office-lan'}


if __name__ == '__main__':
    print(json.dumps(execute(json.load(sys.stdin))))
