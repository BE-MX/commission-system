"""Keep existing Singapore Agent URLs forwarding to Beijing, without old workers.

For remote_python, include base64 of agent_cloud_nginx.py as helper_source_b64.
Only nginx configuration is changed; no Agent service is started.
"""

import base64
import json
import os
from pathlib import Path
import re
import stat
import sys
import types
import uuid

TARGET = 'root@119.28.107.92'
STATE = Path('/var/lib/ark-agent-migration/nginx-source-routes')
MACHINE_ID = Path('/etc/machine-id')
FILES = [Path('/etc/nginx/snippets/ark-main-mcp-location.conf'),
         Path('/etc/nginx/conf.d/leshine.conf'),
         Path('/etc/nginx/sites-enabled/deputy-relay.conf')]
BEGIN = '# BEGIN ARK AGENT CLOUD UPSTREAM TLS'
END = '# END ARK AGENT CLOUD UPSTREAM TLS'
TLS = BEGIN + '''
    proxy_set_header Host leshine.cloud;
    proxy_ssl_server_name on;
    proxy_ssl_name leshine.cloud;
    proxy_ssl_verify on;
    proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
    proxy_ssl_verify_depth 3;
    ''' + END + '\n'
SPECS = [
    {'/mcp/social-customer/': ('http://127.0.0.1:8100/', '/mcp/social-customer/'),
     '/inventory-mcp/sse': ('http://127.0.0.1:3100/sse', '/inventory-mcp/sse'),
     '/inventory-mcp/messages': ('http://127.0.0.1:3100/messages', '/inventory-mcp/messages'),
     '/shipment-mcp/sse': ('http://127.0.0.1:3200/sse', '/shipment-mcp/sse'),
     '/shipment-mcp/messages': ('http://127.0.0.1:3200/messages', '/shipment-mcp/messages')},
    {'/relay/ws': ('http://127.0.0.1:3800/ws', '/relay/ws'),
     '/relay/': ('http://127.0.0.1:3800/', '/relay/')},
    {'/ws': ('http://deputy_relay', '/relay/ws'),
     '/api/': ('http://deputy_relay', '/relay/api/'),
     '/health': ('http://deputy_relay', '/relay/health')},
]


def helper_from(request):
    if 'helper_source_b64' not in request:
        import agent_cloud_nginx
        return agent_cloud_nginx
    source = base64.b64decode(request['helper_source_b64'], validate=True)
    module = types.ModuleType('agent_cloud_nginx')
    exec(compile(source, 'agent_cloud_nginx.py', 'exec'), module.__dict__)
    return module


def locations(content, helper):
    parsed = helper.tokens(content)
    found = []
    for index, (token, _, _) in enumerate(parsed):
        if token != 'location':
            continue
        opening = index + 1
        while opening < len(parsed) and parsed[opening][0] != '{':
            opening += 1
        arguments = [item[0] for item in parsed[index + 1:opening]]
        if len(arguments) == 1:
            path = arguments[0]
        elif len(arguments) == 2 and arguments[0] in {'=', '^~'}:
            path = arguments[1]
        else:
            continue
        depth = 1
        for closing in range(opening + 1, len(parsed)):
            depth += (parsed[closing][0] == '{') - (parsed[closing][0] == '}')
            if depth == 0:
                found.append((path, parsed[opening][2], parsed[closing][1]))
                break
        else:
            raise ValueError('Unbalanced location block')
    return found


def inherited_headers(content, opening, helper):
    """Find the nearest ancestor proxy headers within this configuration file."""
    scopes = [[]]
    statement = []
    for token, start, end in helper.tokens(content):
        if start >= opening:
            break
        if token == '{':
            scopes.append([])
            statement = []
        elif token == '}':
            scopes.pop()
            statement = []
        elif token == ';':
            if statement and statement[0][0] == 'proxy_set_header':
                scopes[-1].append(content[statement[0][1]:end])
            statement = []
        else:
            statement.append((token, start))
    return next((scope for scope in reversed(scopes[:-1]) if scope), [])


def rewrite_location(body, upstream, cloud_path, helper, inherited=()):
    local_headers_marker = '# ARK AGENT ORIGINAL LOCAL HEADERS'
    had_local_headers = local_headers_marker in body
    managed = r'\n' + re.escape(BEGIN) + r'\n.*?' + re.escape(END) + r'\n'
    clean, count = re.subn(managed, '', body, flags=re.S)
    if count > 1 or BEGIN in clean or END in clean:
        raise ValueError('Malformed Agent upstream TLS block')
    parsed = helper.tokens(clean)
    edits = []
    proxies = 0
    hosts = 0
    headers = 0
    target = 'https://154.8.205.162' + cloud_path
    for index, (token, start, _) in enumerate(parsed):
        if token == 'proxy_pass':
            if index + 2 >= len(parsed) or parsed[index + 2][0] != ';':
                raise ValueError('Unsupported proxy_pass syntax')
            value = parsed[index + 1][0]
            # The relay alias may explicitly append its original location URI.
            allowed = {upstream, target}
            if upstream == 'http://deputy_relay':
                allowed.add(upstream + cloud_path.removeprefix('/relay'))
            if value not in allowed:
                raise ValueError('Unexpected Agent proxy upstream')
            edits.append((parsed[index + 1][1], parsed[index + 1][2], target))
            proxies += 1
        elif token == 'proxy_set_header':
            headers += 1
            if index + 3 < len(parsed) and parsed[index + 1][0].lower() == 'host':
                if parsed[index + 3][0] != ';' or parsed[index + 2][0] not in {'$host', '$http_host', 'leshine.cloud'}:
                    raise ValueError('Unexpected Agent Host header')
                edits.append((start, parsed[index + 3][2], ''))
                hosts += 1
        elif token == 'access_log' and cloud_path == '/relay/ws':
            finish = index + 1
            while finish < len(parsed) and parsed[finish][0] != ';':
                finish += 1
            if finish == len(parsed):
                raise ValueError('Malformed WebSocket access_log directive')
            edits.append((start, parsed[finish][2], ''))
        elif token.startswith('proxy_ssl_'):
            raise ValueError('Unowned proxy TLS configuration requires review')
    if proxies != 1 or hosts > 1:
        raise ValueError('Expected one Agent proxy and at most one Host header')
    for start, end, replacement in sorted(edits, reverse=True):
        clean = clean[:start] + replacement + clean[end:]
    extra = []
    if not headers and not had_local_headers:
        # Adding a location-level Host disables nginx's inheritance of ALL
        # proxy_set_header directives. Carry the existing parent set forward.
        extra = [line for line in inherited if helper.tokens(line)[1][0].lower() != 'host']
    if headers or had_local_headers:
        extra.append(local_headers_marker)
    if cloud_path == '/relay/ws':
        extra.append('access_log off;')
    managed = TLS.replace('    ' + END, ''.join('    ' + line + '\n' for line in extra) + '    ' + END)
    return '\n' + managed + clean


def render(content, spec, helper):
    matches = {path: 0 for path in spec}
    edits = []
    for path, opening, closing in locations(content, helper):
        if path not in spec:
            continue
        body = content[opening:closing]
        if not any(token == 'proxy_pass' for token, _, _ in helper.tokens(body)):
            # Leave any HTTP redirects for the same path unchanged.
            continue
        upstream, cloud_path = spec[path]
        edits.append((opening, closing, rewrite_location(body, upstream, cloud_path, helper,
                                                         inherited_headers(content, opening, helper))))
        matches[path] += 1
    if not all(matches.values()):
        raise ValueError('Expected Agent location is missing: ' + ','.join(path for path, count in matches.items() if not count))
    for start, end, body in reversed(edits):
        content = content[:start] + body + content[end:]
    return content


def validate_host(request, helper):
    if (request.get('target') != TARGET
            or not re.fullmatch(r'[a-f0-9]{32}', request.get('expected_machine_id', ''))
            or MACHINE_ID.read_text().strip() != request['expected_machine_id']):
        raise ValueError('Source host identity mismatch')
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise ValueError('Root execution required')
    resolved = [path.resolve(strict=True) for path in FILES]
    if len(set(resolved)) != len(FILES) or any(not path.is_relative_to(helper.NGINX_ROOT.resolve()) for path in resolved):
        raise ValueError('Unexpected source nginx file targets')
    return resolved


def test_candidate(candidates, directory, helper):
    seen = []
    expanded = helper.expand(helper.MAIN, {path: body.decode() for path, body in candidates.items()}, seen)
    if any(path not in seen for path in candidates):
        raise ValueError('Source candidate file is not included by nginx')
    helper.private_write(directory / 'candidate-main.conf', expanded.encode())
    check_path = helper.NGINX_ROOT / ('.ark-source-agent-check-' + uuid.uuid4().hex)
    try:
        helper.atomic_write(check_path, expanded.encode(), 0o600)
        helper.run(['nginx', '-t', '-c', str(check_path)])
    finally:
        check_path.unlink(missing_ok=True)


def execute(request, helper=None):
    helper = helper or helper_from(request)
    files = validate_host(request, helper)
    action = request.get('action')
    if action == 'prepare':
        helper.run(['nginx', '-t'])
        originals = {path: path.read_bytes() for path in files}
        candidates = {path: render(originals[path].decode(), spec, helper).encode() for path, spec in zip(files, SPECS)}
        manifest = [{'path': str(path), 'original_sha256': helper.digest(originals[path]),
                     'candidate_sha256': helper.digest(candidates[path]), 'mode': stat.S_IMODE(path.stat().st_mode)} for path in files]
        identity = {'target': TARGET, 'machine_id': request['expected_machine_id'], 'files': manifest}
        plan_id = helper.digest(json.dumps(identity, sort_keys=True).encode())
        directory = STATE / plan_id
        for index, path in enumerate(files):
            helper.private_write(directory / f'{index}-original.conf', originals[path])
            helper.private_write(directory / f'{index}-candidate.conf', candidates[path])
        test_candidate(candidates, directory, helper)
        plan = {**identity, 'plan_id': plan_id, 'status': 'prepared',
                'original_sha256': {item['path']: item['original_sha256'] for item in manifest}}
        helper.save_plan(directory, plan)
        return plan
    if action not in {'activate', 'verify'} or not re.fullmatch(r'[a-f0-9]{64}', request.get('plan_id', '')):
        raise ValueError('Expected prepare or an existing activate/verify plan')
    directory = STATE / request['plan_id']
    plan = json.loads((directory / 'plan.json').read_text())
    if (plan['target'] != TARGET or plan['machine_id'] != request['expected_machine_id']
            or plan['original_sha256'] != request.get('original_sha256')
            or [item['path'] for item in plan['files']] != [str(path) for path in files]):
        raise ValueError('Source plan identity or original digests differ')
    originals, candidates, current = {}, {}, {}
    for index, (path, item) in enumerate(zip(files, plan['files'])):
        originals[path] = (directory / f'{index}-original.conf').read_bytes()
        candidates[path] = (directory / f'{index}-candidate.conf').read_bytes()
        if helper.digest(originals[path]) != item['original_sha256'] or helper.digest(candidates[path]) != item['candidate_sha256']:
            raise ValueError('Prepared source artifact changed')
        current[path] = path.read_bytes()
        if current[path] not in (originals[path], candidates[path]):
            raise ValueError('Source nginx changed since prepare')
    if action == 'verify' or plan['status'] == 'active':
        if plan['status'] != 'active' or current != candidates:
            raise ValueError('Source Agent routing has not been activated')
        helper.run(['nginx', '-t'])
        helper.run(['systemctl', 'is-active', '--quiet', 'nginx'])
        return {**plan, 'status': 'verified' if action == 'verify' else 'active'}
    test_candidate(candidates, directory, helper)
    if validate_host(request, helper) != files or any(path.read_bytes() != current[path] for path in files):
        raise ValueError('Source nginx changed during candidate validation')
    plan['status'] = 'activating'
    helper.save_plan(directory, plan)
    try:
        for path, item in zip(files, plan['files']):
            helper.atomic_write(path, candidates[path], item['mode'])
        helper.run(['nginx', '-t'])
        helper.run(['systemctl', 'reload', 'nginx'])
        helper.run(['systemctl', 'is-active', '--quiet', 'nginx'])
    except Exception:
        if any(path.read_bytes() not in (originals[path], candidates[path]) for path in files):
            raise RuntimeError('Concurrent source nginx changes; automatic restore withheld') from None
        for path, item in zip(files, plan['files']):
            helper.atomic_write(path, originals[path], item['mode'])
        helper.run(['nginx', '-t'])
        helper.run(['systemctl', 'reload', 'nginx'])
        plan['status'] = 'rolled-back'
        helper.save_plan(directory, plan)
        raise RuntimeError('Source route activation failed; original nginx restored') from None
    plan['status'] = 'active'
    helper.save_plan(directory, plan)
    return plan


if __name__ == '__main__':
    try:
        import fcntl
        os.umask(0o077)
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        STATE.chmod(0o700)
        with (STATE / 'activation.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as error:
        print('Source Agent route operation failed: ' + (str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
