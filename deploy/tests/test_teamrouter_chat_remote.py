"""Isolated transaction tests: no SSH, real Nginx, provider or production data."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('teamrouter_remote', Path(__file__).parents[1] / 'teamrouter_chat_remote.py')
remote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote)
TEMPLATE = (Path(__file__).parents[1] / 'nginx/teamrouter-chat.conf').read_text()
VERIFIER = 'a' * 22
ORIGINAL = b'''server { listen 80; server_name leshine.work www.leshine.work; }
server {
 listen 443 ssl;
 server_name leshine.work www.leshine.work;
 location / { return 200; }
}
'''


def test_render_only_https_and_fixed_security():
    candidate = remote.render(ORIGINAL, VERIFIER, TEMPLATE).decode()
    assert candidate.startswith(ORIGINAL.decode().split('server {\n')[0])
    assert candidate.count(remote.BEGIN) == 1
    assert candidate.index(remote.BEGIN) > candidate.index('listen 443 ssl')
    for text in ('secure_link_md5 "ark-teamrouter-chat-v1|$http_x_api_key"',
                 'proxy_pass_request_headers off', 'proxy_ssl_verify on',
                 'proxy_ssl_name api.teamorouter.com', 'proxy_next_upstream off',
                 'proxy_request_buffering off', 'proxy_buffering off',
                 'if ($request_uri ~ "[?]")', 'if ($request_method != POST)', 'access_log off'):
        assert text in candidate
    assert 'Authorization' not in candidate
    assert remote.render(ORIGINAL, VERIFIER, TEMPLATE) == remote.render(ORIGINAL, VERIFIER, TEMPLATE)


@pytest.mark.parametrize('value', ['', 'a' * 21, 'a' * 23, '";return 200;#' + 'a' * 8])
def test_verifier_rejects_invalid(value):
    with pytest.raises(ValueError):
        remote.render(ORIGINAL, value, TEMPLATE)


def test_conflicts_and_unknown_vhosts_rejected():
    for data in (ORIGINAL + remote.BEGIN.encode(), ORIGINAL + remote.ROUTE.encode(),
                 ORIGINAL.replace(b'443 ssl', b'444 ssl'), ORIGINAL + ORIGINAL):
        with pytest.raises(ValueError):
            remote.render(data, VERIFIER, TEMPLATE)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    path = tmp_path / 'leshine.conf'
    path.write_bytes(ORIGINAL)
    monkeypatch.setattr(remote, 'CONFIG', path)
    monkeypatch.setattr(remote, 'STATE', tmp_path / 'state')
    import contextlib
    @contextlib.contextmanager
    def fake_lock():
        remote.STATE.mkdir(exist_ok=True)
        yield
    monkeypatch.setattr(remote, 'lock', fake_lock)
    # The deployed target is Linux. Windows tests model atomic replace and metadata separately.
    def atomic(path, data, mode=0o600, owner=None):
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_bytes(data)
        temporary.replace(path)
    monkeypatch.setattr(remote, 'atomic', atomic)
    monkeypatch.setattr(remote, 'syntax', lambda *args: None)
    calls = []
    monkeypatch.setattr(remote, 'run', lambda args: calls.append(args) or '')
    monkeypatch.setattr(remote, 'healthy', lambda **kwargs: None)
    prepared = remote.execute({'action': 'prepare', 'verifier': VERIFIER, 'template': TEMPLATE})
    request = {'verifier': VERIFIER, 'template': TEMPLATE, 'baseline': prepared['baseline'], 'candidate': prepared['candidate']}
    return path, request, calls


def test_prepare_activate_rollback(runtime):
    path, request, calls = runtime
    assert path.read_bytes() == ORIGINAL
    assert remote.execute(dict(request, action='activate'))['status'] == 'activated'
    assert path.read_bytes() == remote.render(ORIGINAL, VERIFIER, TEMPLATE)
    assert remote.execute(dict(request, action='rollback'))['status'] == 'rolled_back'
    assert path.read_bytes() == ORIGINAL
    assert calls.count(['nginx', '-t']) == 2


@pytest.mark.parametrize('expected', ['0' * 64, 'bad', None])
def test_prepare_expected_baseline_rejects_drift_before_render(runtime, monkeypatch, expected):
    path, request, calls = runtime
    def forbidden(*args):
        pytest.fail('Must reject before rendering or writing a candidate')
    monkeypatch.setattr(remote, 'render', forbidden)
    with pytest.raises((RuntimeError, ValueError)):
        remote.execute({'action': 'prepare', 'verifier': VERIFIER, 'template': TEMPLATE,
                        'expected_baseline': expected})
    assert path.read_bytes() == ORIGINAL
    assert calls == []


def test_prepare_expected_baseline_accepts_match(runtime):
    path, request, calls = runtime
    result = remote.execute({'action': 'prepare', 'verifier': VERIFIER, 'template': TEMPLATE,
                             'expected_baseline': remote.digest(ORIGINAL)})
    assert result['status'] == 'prepared'
    assert result['candidate'] == request['candidate']


@pytest.mark.parametrize('action', ['activate', 'rollback'])
def test_live_drift_never_overwritten(runtime, action):
    path, request, calls = runtime
    drift = ORIGINAL + b'# another operator\n'
    path.write_bytes(drift)
    with pytest.raises(RuntimeError, match='drifted'):
        remote.execute(dict(request, action=action))
    assert path.read_bytes() == drift
    assert calls == []


def test_failed_health_restores_original(runtime, monkeypatch):
    path, request, calls = runtime
    def fail():
        raise RuntimeError('probe failed')
    monkeypatch.setattr(remote, 'healthy', fail)
    with pytest.raises(RuntimeError, match='probe failed'):
        remote.execute(dict(request, action='activate'))
    assert path.read_bytes() == ORIGINAL
    assert calls.count(['systemctl', 'reload', 'nginx']) == 2


def test_failed_health_with_external_drift_preserves_it(runtime, monkeypatch):
    path, request, calls = runtime
    def fail():
        path.write_bytes(b'operator changed')
        raise RuntimeError('probe failed')
    monkeypatch.setattr(remote, 'healthy', fail)
    with pytest.raises(RuntimeError, match='concurrent drift'):
        remote.execute(dict(request, action='activate'))
    assert path.read_bytes() == b'operator changed'


def test_tampered_candidate_and_wrong_verifier_rejected(runtime):
    path, request, calls = runtime
    with pytest.raises(RuntimeError, match='mismatch'):
        remote.execute(dict(request, action='activate', verifier='b' * 22))
    (remote.STATE / request['candidate'] / 'candidate').write_bytes(b'tampered')
    with pytest.raises(RuntimeError, match='mismatch'):
        remote.execute(dict(request, action='activate'))
    assert path.read_bytes() == ORIGINAL


def test_probe_retains_tls_and_no_credentials(monkeypatch):
    calls = []
    def run(args):
        calls.append(args)
        return '403' if remote.ROUTE in args[-1] else '200'
    monkeypatch.setattr(remote, 'run', run)
    remote.healthy()
    assert len(calls) == 2
    assert all('--insecure' not in args and '-k' not in args for args in calls)
    assert all('--header' not in args for args in calls)


def test_probe_retries_worker_handoff(monkeypatch):
    responses = iter(['404', '200', '403', '200'])
    sleeps = []
    monkeypatch.setattr(remote, 'run', lambda args: next(responses))
    monkeypatch.setattr(remote.time, 'sleep', sleeps.append)
    remote.healthy()
    assert sleeps == [0.5]


def test_probe_retries_are_bounded(monkeypatch):
    calls, sleeps = [], []
    monkeypatch.setattr(remote, 'run', lambda args: calls.append(args) or '404')
    monkeypatch.setattr(remote.time, 'sleep', sleeps.append)
    with pytest.raises(RuntimeError, match='post-reload'):
        remote.healthy()
    assert len(calls) == 10
    assert sleeps == [0.5] * 4


def test_syntax_isolates_runtime_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(remote, 'atomic', lambda path, data: path.write_bytes(data))
    calls = []
    monkeypatch.setattr(remote, 'run', lambda args: calls.append(args))
    remote.syntax(remote.render(ORIGINAL, VERIFIER, TEMPLATE), tmp_path)
    text = (tmp_path / 'check.conf').read_text()
    for name in ('client_body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'):
        assert f'{name}_temp_path "{tmp_path.as_posix()}/{name}"' in text
    assert 'access_log off' in text
    assert calls[0][:2] == ['nginx', '-t']
