"""Scoped Singapore Nginx transaction; stdin supplies a fixed template and verifier."""

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time

CONFIG = Path('/etc/nginx/conf.d/leshine.conf')
STATE = Path('/etc/nginx/.ark-backups/teamrouter-chat')
ROUTE = '/_ark/teamrouter/v1/messages'
BEGIN = '# BEGIN ARK TEAMROUTER CHAT'
END = '# END ARK TEAMROUTER CHAT'
TEMPLATE_SHA256 = '526bcc30b718205583c46c0045a602ec135425b4f14aa562e21db1732302263e'
STAGE = 'validation'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snippet(verifier, template):
    if not re.fullmatch(r'[A-Za-z0-9_-]{22}', verifier):
        raise ValueError('Invalid verifier')
    if not isinstance(template, str) or digest(template.encode()) != TEMPLATE_SHA256:
        raise ValueError('Unrecognized fixed routing template')
    return template.replace('__ARK_VERIFIER__', verifier)


def render(original, verifier, template):
    text = original.decode('utf-8')
    if BEGIN in text or END in text or ROUTE in text:
        raise ValueError('Existing or conflicting TeamRouter route')
    # Only the registered, singular HTTPS vhost. Brace matching ignores strings/comments.
    tokens = list(re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|#[^\n]*|[{}]|\bserver\b', text))
    targets = []
    for i, token in enumerate(tokens):
        if token.group() != 'server' or i + 1 == len(tokens) or tokens[i + 1].group() != '{':
            continue
        depth = 0
        for end in tokens[i + 1:]:
            if end.group() == '{':
                depth += 1
            elif end.group() == '}':
                depth -= 1
                if depth == 0:
                    block = text[tokens[i + 1].end():end.start()]
                    if re.search(r'(?m)^\s*listen\s+443\s+ssl\s*;', block) and re.search(r'(?m)^\s*server_name\s+leshine\.work\s+www\.leshine\.work\s*;', block):
                        targets.append(end.start())
                    break
    if len(targets) != 1:
        raise ValueError('Expected one registered HTTPS vhost')
    pos = targets[0]
    return (text[:pos] + snippet(verifier, template) + text[pos:]).encode()


def run(args):
    # Never echo Nginx source or arbitrary stderr (it may contain credentials).
    result = subprocess.run(args, capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise RuntimeError('Command failed: ' + args[0])
    return result.stdout


def atomic(path, data, mode=0o600, owner=None):
    fd, name = tempfile.mkstemp(prefix='.teamrouter-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
            if owner:
                os.fchown(stream.fileno(), *owner)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def syntax(candidate, scratch):
    # Owned location in a standalone HTTP context, with runtime writes isolated.
    prefix = scratch.as_posix()
    paths = ''.join(f'{key}_temp_path "{prefix}/{key}";\n' for key in ('client_body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'))
    # Included snippets may depend on deployment-specific maps defined in nginx.conf.
    # Syntax-check the owned location independently; full nginx -t gates activation.
    owned = candidate.decode().split(BEGIN, 1)[1].split(END, 1)[0]
    config = (f'pid "{prefix}/nginx.pid";\nerror_log stderr;\nevents {{}}\nhttp {{\n'
              + paths + 'access_log off; server { listen 127.0.0.1:18979;\n' + owned + '\n} }\n')
    check = scratch / 'check.conf'
    atomic(check, config.encode())
    run(['nginx', '-t', '-c', str(check), '-e', 'stderr'])


def healthy(check_denied=True):
    common = ['curl', '--silent', '--show-error', '--noproxy', '*', '--connect-timeout', '2',
              '--max-time', '3', '--resolve', 'leshine.work:443:119.28.107.92',
              '--output', '/dev/null', '--write-out', '%{http_code}']
    # Existing workers may briefly serve the old location after a successful reload.
    for attempt in range(5):
        try:
            denied_ok = not check_denied or run(common + ['--request', 'POST', 'https://leshine.work' + ROUTE]) == '403'
            main_ok = run(common + ['https://leshine.work/']) == '200'
            if denied_ok and main_ok:
                return
        except RuntimeError:
            pass
        if attempt != 4:
            time.sleep(0.5)
    raise RuntimeError('Expected post-reload health state not observed')


@contextlib.contextmanager
def lock():
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def execute(request):
    global STAGE
    STAGE = 'validation'
    action = request['action']
    snippet(request['verifier'], request['template'])
    if action not in {'prepare', 'activate', 'rollback'}:
        raise ValueError('Unknown action')
    with lock():
        if CONFIG.is_symlink() or not CONFIG.is_file():
            raise ValueError('Expected regular registered vhost')
        original = CONFIG.read_bytes()
        if action == 'prepare':
            STAGE = 'prepare'
            if 'expected_baseline' in request:
                expected_baseline = request['expected_baseline']
                if not isinstance(expected_baseline, str) or not re.fullmatch('[a-f0-9]{64}', expected_baseline):
                    raise ValueError('Invalid expected baseline')
                if digest(original) != expected_baseline:
                    raise RuntimeError('Live configuration differs from expected baseline')
            candidate = render(original, request['verifier'], request['template'])
            baseline, sha = digest(original), digest(candidate)
            folder = STATE / sha
            folder.mkdir(mode=0o700, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='syntax-', dir=STATE) as temporary:
                STAGE = 'syntax_check'
                syntax(candidate, Path(temporary))
            STAGE = 'save_prepared_state'
            metadata = CONFIG.stat()
            saved = {'baseline': baseline, 'candidate': sha, 'mode': stat.S_IMODE(metadata.st_mode),
                     'uid': metadata.st_uid, 'gid': metadata.st_gid}
            for name, data in [('original', original), ('candidate', candidate), ('metadata.json', json.dumps(saved).encode())]:
                path = folder / name
                if path.exists() and path.read_bytes() != data:
                    raise RuntimeError('Prepared state conflicts')
                if not path.exists():
                    atomic(path, data)
            return dict(saved, status='prepared')
        for key in ('baseline', 'candidate'):
            if not re.fullmatch('[a-f0-9]{64}', request.get(key, '')):
                raise ValueError('Invalid ' + key)
        STAGE = 'validate_prepared_state'
        folder = STATE / request['candidate']
        saved = json.loads((folder / 'metadata.json').read_text())
        backup, candidate = (folder / 'original').read_bytes(), (folder / 'candidate').read_bytes()
        if (digest(backup) != request['baseline'] or digest(candidate) != request['candidate']
                or saved['baseline'] != request['baseline'] or saved['candidate'] != request['candidate']
                or render(backup, request['verifier'], request['template']) != candidate):
            raise RuntimeError('Prepared state mismatch')
        expected, target = (backup, candidate) if action == 'activate' else (candidate, backup)
        if original != expected:
            raise RuntimeError('Live configuration drifted; refusing overwrite')
        current = CONFIG.stat()
        if (stat.S_IMODE(current.st_mode), current.st_uid, current.st_gid) != (saved['mode'], saved['uid'], saved['gid']):
            raise RuntimeError('Live permissions drifted')
        # Recheck immediately before atomic switch; all task transactions hold flock.
        if CONFIG.read_bytes() != expected:
            raise RuntimeError('Concurrent configuration change')
        STAGE = 'switch_configuration'
        atomic(CONFIG, target, saved['mode'], (saved['uid'], saved['gid']))
        try:
            STAGE = 'nginx_validate'
            run(['nginx', '-t'])
            STAGE = 'nginx_reload'
            run(['systemctl', 'reload', 'nginx'])
            STAGE = 'health_probe'
            if action == 'activate':
                healthy()
            else:
                healthy(check_denied=False)
        except Exception:
            if CONFIG.read_bytes() != target:
                raise RuntimeError('Failure with concurrent drift; recovery preserved')
            failed_stage = STAGE
            STAGE = 'restore_previous_configuration'
            atomic(CONFIG, expected, saved['mode'], (saved['uid'], saved['gid']))
            run(['nginx', '-t'])
            run(['systemctl', 'reload', 'nginx'])
            STAGE = failed_stage
            raise
        return {'status': 'activated' if action == 'activate' else 'rolled_back',
                'baseline': request['baseline'], 'candidate': request['candidate']}


if __name__ == '__main__':
    try:
        print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__, 'stage': STAGE}))
        sys.exit(1)
