"""Performance contracts and safety checks, isolated files/mocked remote actions."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time
import tarfile
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_events as events
import npm_cache
import static_prepare
import static_retention as retention
import remote_static
import publish


def tree(root, files):
    for name, body in files.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(body)
    return {name: hashlib.sha256(body).hexdigest() for name, body in files.items()}


def test_retention_hashes_each_required_file_once_and_detects_corruption(tmp_path, monkeypatch):
    roots = [tmp_path / str(i) for i in range(3)]
    files = {'index.html': b'index', 'assets/a.js': b'a', 'assets/b.js': b'b'}
    manifests = [tree(root, files) for root in roots]
    calls = []
    original = retention.sha
    def traced(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(retention, 'sha', traced)
    plan = retention.plan_cleanup(list(zip(roots, manifests)), [], retention.asset_union(manifests))
    assert plan['copies'] == plan['deletes'] == []
    assert len(calls) == len(set(calls)) == 9
    (roots[1] / 'assets/b.js').write_bytes(b'bad')
    with pytest.raises(ValueError, match='corrupt'):
        retention.plan_cleanup(list(zip(roots, manifests)), [], retention.asset_union(manifests))


def test_retention_extra_sources_are_lazy_and_unsafe_deletion_still_blocks(tmp_path, monkeypatch):
    current, old = tmp_path / 'current', tmp_path / 'old'
    files = tree(current, {'index.html': b'i', 'assets/a.js': b'a'})
    extra = tree(old, {'index.html': b'o', 'assets/b.js': b'b'})
    plan = retention.plan_cleanup([(current, files)], [old], retention.asset_union([files, extra]), [old])
    assert plan['copies'] == [(old / 'assets/b.js', current / 'assets/b.js')]
    retention.apply_cleanup(plan, [tmp_path])
    assert (current / 'assets/b.js').read_bytes() == b'b' and not old.exists()


def test_parallel_hosts_serial_targets_order_and_private_archives(tmp_path, monkeypatch):
    rendezvous = threading.Barrier(2)
    active, seen, mutex = set(), [], threading.Lock()
    targets = [{'host': host, 'component': 'frontend', 'root': '/' + str(i), 'domain': str(i)}
               for i, host in enumerate(['a', 'b', 'a', 'b'])]
    def prepare(source, host, root, state, domain):
        with mutex:
            assert host not in active
            active.add(host)
            seen.append((host, state))
        if domain in {'0', '1'}:
            rendezvous.wait(timeout=5)
        with mutex:
            active.remove(host)
        return domain
    monkeypatch.setattr(static_prepare.static_sync, 'prepare', prepare)
    assert static_prepare.prepare_all(targets, {'frontend': tmp_path}, tmp_path) == ['0', '1', '2', '3']
    assert len(set(path for _, path in seen)) == 4


def test_prepare_failure_joins_inflight_before_return(tmp_path, monkeypatch):
    rendezvous = threading.Barrier(2)
    finished = threading.Event()
    def prepare(source, host, *args):
        rendezvous.wait(timeout=5)
        if host == 'a':
            raise RuntimeError('prepare failed')
        time.sleep(0.05)
        finished.set()
        return 'prepared'
    monkeypatch.setattr(static_prepare.static_sync, 'prepare', prepare)
    targets = [{'host': host, 'component': 'f', 'root': '/', 'domain': host} for host in ('a', 'b')]
    with pytest.raises(RuntimeError, match='prepare failed'):
        static_prepare.prepare_all(targets, {'f': tmp_path}, tmp_path)
    assert finished.is_set()


def test_parallel_timings_are_complete_and_json_writes_serialized(tmp_path, monkeypatch):
    original, active, guard = events.atomic_json, 0, threading.Lock()
    def write(path, data):
        nonlocal active
        with guard:
            active += 1
            assert active == 1
        time.sleep(0.001)
        original(path, data)
        with guard:
            active -= 1
    monkeypatch.setattr(events, 'atomic_json', write)
    with events.timing_session(tmp_path):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: events.step(str(i), 'test', lambda: i), range(12)))
    result = json.loads(next((tmp_path / 'timings').glob('*.json')).read_text())
    assert result['status'] == 'succeeded' and len(result['steps']) == 12
    assert all(row['status'] == 'succeeded' and row['elapsed_ms'] >= 0 for row in result['steps'])


def test_dependency_cache_restores_private_files_and_prunes_owned_pairs(tmp_path):
    first, second = tmp_path / 'a/frontend', tmp_path / 'b/frontend'
    files = {'pkg/package.json': b'{}', 'pkg/bin.exe': b'program', '.bin/tool.cmd': b'command'}
    tree(first / 'node_modules', files)
    second.mkdir(parents=True)
    state = tmp_path / 'state'
    key = 'a' * 64
    npm_cache.store(first, state, key)
    assert npm_cache.restore(second, state, key)
    (second / 'node_modules/pkg/bin.exe').write_bytes(b'changed')
    assert (first / 'node_modules/pkg/bin.exe').read_bytes() == b'program'
    assert not npm_cache.restore(second, state, key)
    for char in 'bcde':
        npm_cache.store(first, state, char * 64)
    cache = state / 'npm-cache/frontend'
    assert len(list(cache.glob('*.json'))) == npm_cache.KEEP
    assert len(list(cache.glob('*.zip'))) == npm_cache.KEEP


@pytest.mark.parametrize('name', ['../outside', '/outside', 'C:/outside', 'pkg/file:ads', 'pkg/NUL.txt', 'pkg/a.'])
def test_dependency_archive_rejects_unsafe_paths_before_writing(tmp_path, name):
    folder, state, key = tmp_path / 'frontend', tmp_path / 'state', 'a' * 64
    folder.mkdir()
    root, archive, receipt = npm_cache.paths(state, folder.name, key)
    root.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr(name, b'bad')
    retention.atomic_json(receipt, {'schema': 1, 'key': key, 'sha256': retention.sha(archive), 'bytes': 3, 'files': 1})
    with pytest.raises(ValueError):
        npm_cache.restore(folder, state, key)
    assert not (folder / 'node_modules').exists() and not list(folder.glob('node_modules.restore-*'))


@pytest.mark.parametrize('kind', ['checksum', 'case-alias', 'symlink', 'parent-file'])
def test_corrupt_or_ambiguous_cache_cannot_install_partial_dependencies(tmp_path, kind):
    folder, state, key = tmp_path / 'frontend', tmp_path / 'state', 'a' * 64
    folder.mkdir()
    root, archive, receipt = npm_cache.paths(state, folder.name, key)
    root.mkdir(parents=True)
    with zipfile.ZipFile(archive, 'w') as bundle:
        info = zipfile.ZipInfo('pkg/a')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16 if kind == 'symlink' else (stat.S_IFREG | 0o644) << 16
        bundle.writestr(info, b'bad')
        if kind == 'case-alias': bundle.writestr('PKG/A', b'bad')
        if kind == 'parent-file': bundle.writestr('pkg', b'bad')
    retention.atomic_json(receipt, {'schema': 1, 'key': key, 'sha256': 'wrong' if kind == 'checksum' else retention.sha(archive), 'bytes': 3, 'files': 1})
    with pytest.raises(ValueError):
        npm_cache.restore(folder, state, key)
    assert not (folder / 'node_modules').exists() and not list(folder.glob('node_modules.restore-*'))


def test_restore_failure_removes_only_its_incomplete_tree(tmp_path, monkeypatch):
    folder, state, key = tmp_path / 'frontend', tmp_path / 'state', 'a' * 64
    tree(folder / 'node_modules', {'pkg/a': b'a'})
    npm_cache.store(folder, state, key)
    target = tmp_path / 'other/frontend'
    target.mkdir(parents=True)
    sentinel = target / 'business.txt'
    sentinel.write_bytes(b'keep')
    def fail(*args): raise OSError('full disk')
    monkeypatch.setattr(npm_cache.shutil, 'copyfileobj', fail)
    with pytest.raises(OSError): npm_cache.restore(target, state, key)
    assert sentinel.read_bytes() == b'keep'
    assert not (target / 'node_modules').exists() and not list(target.glob('node_modules.restore-*'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows cache eligibility')
def test_cache_key_includes_effective_config_and_rejects_unreviewed_hooks(tmp_path, monkeypatch):
    folder = tmp_path / 'frontend'
    folder.mkdir()
    package = {'name': 'frontend', 'scripts': {'build': 'vite build'}}
    lock = {'lockfileVersion': 3, 'packages': {'': {}, 'node_modules/esbuild': {'hasInstallScript': True}}}
    (folder / 'package.json').write_text(json.dumps(package))
    (folder / 'package-lock.json').write_text(json.dumps(lock))
    for name in ('ESBUILD_BINARY_PATH', 'NODE_PATH', 'NODE_OPTIONS'):
        monkeypatch.delenv(name, raising=False)
    config = {'registry': 'https://registry.npmjs.org', 'omit': [], 'local-prefix': 'candidate-a', 'install-links': False}
    runtime = ['v22', 'win32', 'x64', '127']
    def run(args, **kwargs):
        if 'config' in args: return json.dumps(config)
        return json.dumps(runtime) if '-p' in args else 'version-1'
    first = npm_cache.fingerprint(folder, 'npm', run)
    assert first
    config['local-prefix'] = 'candidate-b'
    assert npm_cache.fingerprint(folder, 'npm', run) == first
    runtime[2] = 'arm64'
    assert npm_cache.fingerprint(folder, 'npm', run) != first
    runtime[2] = 'x64'
    config['omit'] = ['dev']
    assert npm_cache.fingerprint(folder, 'npm', run) != first
    package['scripts']['postinstall'] = 'custom.js'
    (folder / 'package.json').write_text(json.dumps(package))
    assert npm_cache.fingerprint(folder, 'npm', run) is None
    del package['scripts']['postinstall']
    (folder / 'package.json').write_text(json.dumps(package))
    lock['packages']['node_modules/unknown'] = {'hasInstallScript': True}
    (folder / 'package-lock.json').write_text(json.dumps(lock))
    assert npm_cache.fingerprint(folder, 'npm', run) is None


def test_asset_merge_is_independent_and_rejects_conflicting_bytes(tmp_path):
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    tree(base, {'assets/old.js': b'old', 'assets/shared.js': b'same'})
    tree(candidate, {'assets/new.js': b'new', 'assets/shared.js': b'same'})
    remote_static.retain_assets(base, candidate)
    (candidate / 'assets/old.js').write_bytes(b'changed')
    assert (base / 'assets/old.js').read_bytes() == b'old'
    with pytest.raises(ValueError, match='different bytes'):
        remote_static.retain_assets(base, candidate)


def test_failed_cache_receipt_does_not_poison_next_candidate(tmp_path, monkeypatch):
    folder, state, key = tmp_path / 'frontend', tmp_path / 'state', 'a' * 64
    tree(folder / 'node_modules', {'pkg/a': b'a'})
    original = npm_cache.atomic_json
    def fail(*args): raise OSError('full disk')
    monkeypatch.setattr(npm_cache, 'atomic_json', fail)
    with pytest.raises(OSError): npm_cache.store(folder, state, key)
    root, archive, receipt = npm_cache.paths(state, folder.name, key)
    assert not archive.exists() and not receipt.exists()
    next_candidate = tmp_path / 'next/frontend'
    next_candidate.mkdir(parents=True)
    assert not npm_cache.restore(next_candidate, state, key)
    monkeypatch.setattr(npm_cache, 'atomic_json', original)
    npm_cache.store(folder, state, key)
    assert npm_cache.restore(next_candidate, state, key)


def test_event_is_one_complete_write(tmp_path, monkeypatch):
    writes = []
    class Output:
        def write(self, text): writes.append(text)
        def flush(self): pass
    monkeypatch.setenv('ARK_DESKTOP_RUN_ID', 'a' * 32)
    monkeypatch.setattr(events.sys, 'stdout', Output())
    events.emit('step', key='a', status='running')
    assert len(writes) == 1 and writes[0].endswith('\n')
    assert json.loads(writes[0][len(events.PREFIX):])['key'] == 'a'


def test_parallel_same_artifact_different_missing_sets_have_private_packages(tmp_path, monkeypatch):
    sync = static_prepare.static_sync
    source, state = tmp_path / 'source', tmp_path / 'transfers'
    tree(source, {'index.html': b'i', 'a.js': b'a', 'b.js': b'b'})
    rendezvous = threading.Barrier(2)
    bundles, paths = {}, []
    mutex = threading.Lock()
    def remote(host, request):
        if request['action'] == 'plan':
            return {'artifact': 'a' * 64, 'active_artifact': None, 'initialized': False,
                    'staged': False, 'missing': [host + '.js']}
        return {}
    def upload(args, **kwargs):
        archive = Path(args[-2])
        host = args[-1].split(':')[0]
        rendezvous.wait(timeout=5)
        with tarfile.open(archive) as bundle:
            with mutex:
                bundles[host] = bundle.getnames()
                paths.append(archive)
    monkeypatch.setattr(sync, 'remote', remote)
    monkeypatch.setattr(sync, 'run', upload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda host: sync.prepare(source, host, '/site', state, host), ['a', 'b']))
    assert bundles == {'a': ['a.js'], 'b': ['b.js']}
    assert len(set(paths)) == 2 and all(not path.exists() for path in paths)


def test_windows_scanner_retry_requires_unchanged_destination(tmp_path, monkeypatch):
    temporary, destination = tmp_path / 'incoming', tmp_path / 'node_modules'
    temporary.mkdir()
    original, attempts = Path.rename, []
    def rename(path, target):
        attempts.append(path)
        if len(attempts) == 1: raise PermissionError('scanner busy')
        return original(path, target)
    monkeypatch.setattr(Path, 'rename', rename)
    monkeypatch.setattr(npm_cache.time, 'sleep', lambda _: None)
    npm_cache.install_tree(temporary, destination)
    assert destination.is_dir() and len(attempts) == 2
    temporary.mkdir()
    attempts.clear()
    with pytest.raises(ValueError, match='destination changed'):
        npm_cache.install_tree(temporary, destination)
    assert attempts == []


def test_publisher_restores_new_candidate_without_running_npm_ci(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    first, second = tmp_path / 'a/frontend', tmp_path / 'b/frontend'
    for folder in (first, second):
        folder.mkdir(parents=True)
        (folder / 'package.json').write_text('{}')
        (folder / 'package-lock.json').write_text('{}')
    installs = []
    def run(args, cwd=None, **kwargs):
        if 'ci' in args:
            installs.append(cwd)
            tree(cwd / 'node_modules', {'pkg/a': b'installed'})
            return ''
        return 'test-version'
    monkeypatch.setattr(publish, 'STATE', state)
    monkeypatch.setattr(publish, 'npm_command', lambda: 'npm')
    monkeypatch.setattr(publish, 'run', run)
    monkeypatch.setattr(npm_cache, 'fingerprint', lambda *args: 'a' * 64)
    for folder in (first, second):
        monkeypatch.setattr(publish, 'ROOT', folder.parent)
        publish.npm_install(folder)
    assert installs == [first]
    assert (second / 'node_modules/pkg/a').read_bytes() == b'installed'
    assert publish.marker('deps-frontend')['digest'] == 'a' * 64
