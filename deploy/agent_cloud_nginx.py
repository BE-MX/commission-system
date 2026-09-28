"""Prepare and activate only the Beijing Agent routes; run remotely as root."""

import fnmatch
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

NGINX_ROOT = Path('/etc/nginx')
MAIN = NGINX_ROOT / 'nginx.conf'
SITE = NGINX_ROOT / 'sites-enabled/ark-cloud.conf'
ZONE = NGINX_ROOT / 'conf.d/ark-agent-social-customer-limit.conf'
STATE = Path('/var/lib/ark-agent-migration/nginx')
MACHINE_ID = Path('/etc/machine-id')
TARGET = 'ubuntu@154.8.205.162'
BEGIN = '# BEGIN ARK AGENT CLOUD ROUTING'
END = '# END ARK AGENT CLOUD ROUTING'
ZONE_TEXT = 'limit_req_zone $binary_remote_addr zone=social_customer_mcp:10m rate=5r/s;\n'


def digest(body):
    return hashlib.sha256(body).hexdigest()


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode:
        # nginx -T / errors can disclose unrelated site configuration.
        raise RuntimeError(f'{args[0]} command failed with exit {result.returncode}; configuration output withheld')


def tokens(text):
    """Token positions, including quoted regexes; ignore comments and braces in quotes."""
    result = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
        elif char == '#':
            end = text.find('\n', index)
            index = len(text) if end == -1 else end + 1
        elif char in '{};':
            result.append((char, index, index + 1))
            index += 1
        else:
            start = index
            quote = char if char in "\"'" else None
            if quote:
                index += 1
            value = []
            while index < len(text):
                char = text[index]
                if char == '\\' and index + 1 < len(text):
                    value.extend(text[index:index + 2])
                    index += 2
                elif quote and char == quote:
                    index += 1
                    break
                elif not quote and (char.isspace() or char in '{};#'):
                    break
                else:
                    value.append(char)
                    index += 1
            else:
                if quote:
                    raise ValueError('Unterminated nginx string')
            result.append((''.join(value), start, index))
    return result


def blocks(text, name):
    parsed = tokens(text)
    result = []
    depth = 0
    for index, (value, start, _) in enumerate(parsed):
        if value == name and depth == 0 and index + 1 < len(parsed) and parsed[index + 1][0] == '{':
            level = 1
            for finish in range(index + 2, len(parsed)):
                level += (parsed[finish][0] == '{') - (parsed[finish][0] == '}')
                if level == 0:
                    result.append((start, parsed[index + 1][2], parsed[finish][1], parsed[finish][2]))
                    break
            else:
                raise ValueError('Unbalanced nginx block')
        depth += (value == '{') - (value == '}')
        if depth < 0:
            raise ValueError('Unbalanced nginx configuration')
    if depth:
        raise ValueError('Unbalanced nginx configuration')
    return result


def directives(text):
    """Return only direct directives, excluding nested location contents."""
    depth = 0
    current = []
    result = []
    for value, _, _ in tokens(text):
        if value == '{':
            depth += 1
            current = []
        elif value == '}':
            depth -= 1
        elif depth == 0 and value == ';':
            result.append(current)
            current = []
        elif depth == 0:
            current.append(value)
    return result


HEADERS = '''    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Origin $http_origin;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
'''


def snippet():
    routes = ['''location = /mcp/social-customer { return 308 /mcp/social-customer/; }
location ^~ /mcp/social-customer/ {
    limit_req zone=social_customer_mcp burst=10 nodelay;
    client_max_body_size 32k;
    proxy_pass http://127.0.0.1:8100/;
''' + HEADERS + '''    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
    limit_except GET POST DELETE { deny all; }
}''']
    for name, port in [('inventory-mcp', 3100), ('shipment-mcp', 3200)]:
        routes.append(f'''location = /{name}/sse {{
    proxy_pass http://127.0.0.1:{port}/sse;
''' + HEADERS + f'''    proxy_set_header Connection "";
    proxy_set_header Accept-Encoding "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    gzip off;
    sub_filter_types text/event-stream;
    sub_filter_once off;
    sub_filter 'data: /messages?' 'data: /{name}/messages?';
    add_header X-Accel-Buffering no always;
}}
location = /{name}/messages {{
    proxy_pass http://127.0.0.1:{port}/messages;
''' + HEADERS + '''    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_read_timeout 60s;
    proxy_send_timeout 60s;
}''')
    routes.append('''location = /relay/ws {
    access_log off;
    proxy_pass http://127.0.0.1:3800/ws;
''' + HEADERS + '''    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
location = /relay { return 308 /relay/; }
location ^~ /relay/ {
    proxy_pass http://127.0.0.1:3800/;
''' + HEADERS + '''    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
}''')
    return BEGIN + '\n' + '\n\n'.join(routes) + '\n' + END + '\n'


def render(original):
    # Own only a marked block. Unknown existing Agent routes require review.
    pattern = r'\n' + re.escape(BEGIN) + r'\n.*?' + re.escape(END) + r'\n'
    clean, count = re.subn(pattern, '', original, flags=re.S)
    if count > 1 or BEGIN in clean or END in clean:
        raise ValueError('Ambiguous managed Agent routing block')
    selected = []
    for start, opening, closing, end in blocks(clean, 'server'):
        direct = directives(clean[opening:closing])
        names = [d[1:] for d in direct if d and d[0] == 'server_name']
        listens = [d[1:] for d in direct if d and d[0] == 'listen']
        https = any('ssl' in d and any(re.search(r'(^|:)443$', item) for item in d) for d in listens)
        if https and any({'leshine.cloud', 'www.leshine.cloud'}.issubset(set(d)) for d in names):
            selected.append((start, opening, closing, end))
    if len(selected) != 1:
        raise ValueError('Expected exactly one HTTPS leshine.cloud/www server block')
    _, opening, closing, _ = selected[0]
    body = clean[opening:closing]
    locations = tokens(body)
    for index, (value, _, _) in enumerate(locations):
        if value == 'location':
            arguments = []
            for token, _, _ in locations[index + 1:]:
                if token == '{':
                    break
                arguments.append(token)
            if any(any(path in token for path in ('/mcp/social-customer', '/inventory-mcp', '/shipment-mcp', '/relay'))
                   for token in arguments):
                raise ValueError('Existing unowned Agent location requires explicit review')
    # Inserting directly after the server opening preserves all existing bytes,
    # including generic /mcp/, SSL and backend routing. Re-render is idempotent.
    return clean[:opening] + '\n' + snippet() + clean[opening:]


def expand(path, overrides=None, seen=None, stack=()):
    """Expand includes for nginx -t without changing any active configuration."""
    overrides = overrides or {}
    seen = seen if seen is not None else []
    path = path.resolve()
    if path in stack or len(stack) > 30:
        raise ValueError('Recursive nginx include')
    seen.append(path)
    content = overrides[path] if path in overrides else path.read_text(encoding='utf-8')
    parsed = tokens(content)
    replacements = []
    for index, (value, start, _) in enumerate(parsed):
        if value != 'include' or (index and parsed[index - 1][0] not in {';', '{', '}'}):
            continue
        if index + 2 >= len(parsed) or parsed[index + 2][0] != ';':
            raise ValueError('Unsupported nginx include syntax')
        pattern = parsed[index + 1][0]
        if not Path(pattern).is_absolute():
            pattern = str(NGINX_ROOT / pattern)
        # nginx glob ordering uses the include names, not symlink destinations.
        paths = {Path(item) for item in glob.glob(pattern)}
        paths.update(item for item in overrides if fnmatch.fnmatch(str(item), pattern))
        if not paths and not glob.has_magic(pattern):
            raise ValueError('Required nginx include missing')
        expanded = '\n'.join(expand(item, overrides, seen, (*stack, path)) for item in sorted(paths))
        replacements.append((start, parsed[index + 2][2], expanded))
    for start, end, expanded in reversed(replacements):
        content = content[:start] + expanded + content[end:]
    return content


def private_write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    atomic_write(path, body, 0o600)


def atomic_write(path, body, mode):
    temporary = path.with_name(path.name + '.ark-agent-' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as output:
            output.write(body)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_plan(directory, plan):
    private_write(directory / 'plan.json', json.dumps(plan, indent=2).encode())


def check_host(request):
    if request.get('target') != TARGET:
        raise ValueError('Explicit Beijing SSH target is required')
    expected = request.get('expected_machine_id', '')
    if not re.fullmatch(r'[a-f0-9]{32}', expected) or MACHINE_ID.read_text().strip() != expected:
        raise ValueError('Target machine identity mismatch')
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise ValueError('Run through remote_python with sudo=True')
    resolved = SITE.resolve(strict=True)
    if not resolved.is_relative_to(NGINX_ROOT.resolve()) or resolved == MAIN.resolve():
        raise ValueError('Unexpected nginx site target')
    return resolved


def test_candidate(directory, site, candidate, zone):
    overrides = {site: candidate.decode()}
    if zone is not None:
        overrides[ZONE.resolve()] = zone.decode()
    seen = []
    expanded = expand(MAIN, overrides, seen)
    if seen.count(site) != 1 or (zone is not None and seen.count(ZONE.resolve()) != 1):
        raise ValueError('Candidate site/zone is not included exactly once by nginx')
    test_path = directory / 'candidate-main.conf'
    private_write(test_path, expanded.encode())
    # Preserve nginx's compiled prefix (relative dynamic modules) and the
    # original conf-prefix (relative certificates/includes). A private temporary
    # main file beside nginx.conf is never included by the active configuration.
    check_path = NGINX_ROOT / ('.ark-agent-check-' + uuid.uuid4().hex)
    try:
        atomic_write(check_path, expanded.encode(), 0o600)
        run(['nginx', '-t', '-c', str(check_path)])
    finally:
        check_path.unlink(missing_ok=True)


def read_optional(path):
    if path.is_symlink():
        raise ValueError('Managed limit zone cannot be a symlink')
    return path.read_bytes() if path.exists() else None


def execute(request):
    site = check_host(request)
    action = request.get('action')
    if action == 'prepare':
        run(['nginx', '-t'])
        original = site.read_bytes()
        candidate = render(original.decode()).encode()
        expanded = expand(MAIN)
        parsed = tokens(expanded)
        zone_definitions = []
        for index, (value, _, _) in enumerate(parsed):
            if value == 'limit_req_zone':
                for argument, _, _ in parsed[index + 1:]:
                    if argument == ';':
                        break
                    if argument.startswith('zone=social_customer_mcp:'):
                        zone_definitions.append(argument)
        if len(zone_definitions) > 1:
            raise ValueError('Ambiguous social customer limit zone')
        zone_original = read_optional(ZONE)
        if zone_original is not None and zone_original != ZONE_TEXT.encode():
            raise ValueError('Existing managed zone file has unexpected content')
        zone_candidate = ZONE_TEXT.encode() if not zone_definitions or zone_original is not None else None
        identity = {'target': TARGET, 'machine_id': request['expected_machine_id'], 'site': str(site),
                    'original_sha256': digest(original), 'candidate_sha256': digest(candidate),
                    'zone_original_sha256': digest(zone_original) if zone_original is not None else None,
                    'zone_candidate_sha256': digest(zone_candidate) if zone_candidate is not None else None}
        plan_id = digest(json.dumps(identity, sort_keys=True).encode())
        directory = STATE / plan_id
        private_write(directory / 'original.conf', original)
        private_write(directory / 'candidate.conf', candidate)
        if zone_original is not None:
            private_write(directory / 'zone-original.conf', zone_original)
        if zone_candidate is not None:
            private_write(directory / 'zone-candidate.conf', zone_candidate)
        test_candidate(directory, site, candidate, zone_candidate)
        plan = {**identity, 'plan_id': plan_id, 'status': 'prepared', 'site_mode': stat.S_IMODE(site.stat().st_mode)}
        save_plan(directory, plan)
        return plan
    if action not in {'activate', 'verify'}:
        raise ValueError('Expected prepare, activate or verify')
    plan_id = request.get('plan_id', '')
    if not re.fullmatch(r'[a-f0-9]{64}', plan_id):
        raise ValueError('Prepared plan_id is required')
    directory = STATE / plan_id
    plan = json.loads((directory / 'plan.json').read_text())
    if (plan['machine_id'] != request['expected_machine_id'] or plan['site'] != str(site)
            or plan['target'] != TARGET or plan['original_sha256'] != request.get('original_sha256')):
        raise ValueError('Plan target or original digest mismatch')
    original = (directory / 'original.conf').read_bytes()
    candidate = (directory / 'candidate.conf').read_bytes()
    zone_original = (directory / 'zone-original.conf').read_bytes() if plan['zone_original_sha256'] else None
    zone_candidate = (directory / 'zone-candidate.conf').read_bytes() if plan['zone_candidate_sha256'] else None
    for body, key in [(original, 'original_sha256'), (candidate, 'candidate_sha256'),
                      (zone_original, 'zone_original_sha256'), (zone_candidate, 'zone_candidate_sha256')]:
        if (digest(body) if body is not None else None) != plan[key]:
            raise ValueError('Prepared artifact digest mismatch')
    current = site.read_bytes()
    zone_current = read_optional(ZONE)
    if current not in (original, candidate) or zone_current not in (zone_original, zone_candidate):
        raise ValueError('Active nginx configuration changed after preparation')
    if action == 'verify' or plan['status'] == 'active':
        if current != candidate or zone_current != zone_candidate or plan['status'] != 'active':
            raise ValueError('Agent routing activation is not verified')
        run(['nginx', '-t'])
        run(['systemctl', 'is-active', '--quiet', 'nginx'])
        return {**plan, 'status': 'verified' if action == 'verify' else 'active'}
    test_candidate(directory, site, candidate, zone_candidate)
    plan['status'] = 'activating'
    save_plan(directory, plan)
    try:
        # Recheck after candidate testing so concurrent external edits are never overwritten.
        if SITE.resolve(strict=True) != site or site.read_bytes() != current or read_optional(ZONE) != zone_current:
            raise ValueError('Nginx configuration changed during candidate testing')
        if zone_candidate is not None:
            atomic_write(ZONE, zone_candidate, 0o644)
        atomic_write(site, candidate, plan['site_mode'])
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        run(['systemctl', 'is-active', '--quiet', 'nginx'])
    except Exception:
        if site.read_bytes() not in (original, candidate) or read_optional(ZONE) not in (zone_original, zone_candidate):
            raise RuntimeError('Concurrent nginx edit detected; restore withheld, inspect private backup') from None
        atomic_write(site, original, plan['site_mode'])
        if zone_original is None:
            ZONE.unlink(missing_ok=True)
        else:
            atomic_write(ZONE, zone_original, 0o644)
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        plan['status'] = 'rolled-back'
        save_plan(directory, plan)
        raise RuntimeError('Agent routing activation failed; original nginx configuration restored') from None
    plan['status'] = 'active'
    save_plan(directory, plan)
    return plan


if __name__ == '__main__':
    try:
        import fcntl
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        STATE.chmod(0o700)
        with (STATE / 'activation.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as error:
        print('Agent nginx operation failed: ' + (str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
