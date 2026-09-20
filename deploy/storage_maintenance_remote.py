"""Reversible ingress gate; preserve later reviewed Nginx edits on restoration."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MARKER = '# ARK STORAGE MAINTENANCE\n'
GATE = MARKER + 'if ($uri ~ "^/api/") { return 503; }\n'
SPECS = {
    'beijing': [('/etc/nginx/sites-available/ark-cloud.conf', 2),
                ('/etc/nginx/sites-available/ark-ip-ssl.conf', 1),
                ('/etc/nginx/conf.d/customer-media.leshine.cloud.conf', 1)],
    'singapore': [('/etc/nginx/conf.d/leshine.conf', 1),
                  ('/etc/nginx/conf.d/pm.leshine.conf', 1)],
}


def render(content, count, restore=False, api_prefix='/api/'):
    if restore:
        if content.count(GATE) != count:
            raise RuntimeError('Maintenance gate drift; inspect before restore')
        return content.replace(GATE, '')
    if MARKER in content:
        raise RuntimeError('Existing maintenance gate requires recovery')
    result, actual = re.subn(r'(?m)^([ \t]*location (?:\^~ )?' + re.escape(api_prefix) + r' \{)',
                             lambda m: GATE + m[0], content)
    if actual != count:
        raise RuntimeError('Unexpected API ingress layout')
    return result


def execute(request):
    region, action = request['region'], request['action']
    if region not in SPECS or action not in {'prepare', 'freeze', 'restore'}:
        raise ValueError('Unsupported maintenance operation')
    if not re.fullmatch(r'[a-z0-9-]{1,64}', request['attempt']):
        raise ValueError('Invalid attempt')
    state = Path('/etc/nginx/.ark-backups/storage-maintenance') / request['attempt']
    record = state / 'record.json'
    original = {name: Path(name).read_text() for name, _ in SPECS[region]}
    candidates = {name: render(original[name], count, action == 'restore',
                  '/api/customer-media/' if Path(name).name == 'customer-media.leshine.cloud.conf' else '/api/')
                  for name, count in SPECS[region]}
    if action == 'prepare':
        return {'status': 'prepared', 'region': region}
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if action == 'freeze':
        if record.exists():
            raise RuntimeError('Prior maintenance attempt must be inspected')
        for name, body in original.items():
            backup = state / Path(name).name
            backup.write_text(body)
            backup.chmod(0o600)
        data = {'status': 'prepared', 'region': region, 'files': list(original)}
    else:
        data = json.loads(record.read_text())
        if data['status'] != 'frozen' or data['region'] != region:
            raise RuntimeError('Maintenance record mismatch')
    def save(status):
        data['status'] = status
        record.write_text(json.dumps(data))
    save('applying-' + action)
    try:
        for name, body in candidates.items():
            Path(name).write_text(body)
        subprocess.run(['nginx', '-t'], check=True, stdout=sys.stderr, stderr=sys.stderr)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    except Exception:
        for name, body in original.items():
            Path(name).write_text(body)
        subprocess.run(['nginx', '-t'], check=True, stdout=sys.stderr, stderr=sys.stderr)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
        save('frozen' if action == 'restore' else 'restored-after-failure')
        raise
    save('restored' if action == 'restore' else 'frozen')
    return {'status': data['status'], 'region': region}


if __name__ == '__main__':
    print(json.dumps(execute(json.load(sys.stdin))))
