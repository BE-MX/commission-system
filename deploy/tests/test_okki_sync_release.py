"""Outbound release verification uses only temp files and simulated processes."""
import base64
from contextlib import nullcontext
import hashlib
import importlib.util
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def release(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'okki_sync_remote.py'
    spec = importlib.util.spec_from_file_location('outbound_release_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path / 'runtime'
    module.ROOT.mkdir()
    monkeypatch.setattr(module, 'release_lock', nullcontext)
    monkeypatch.setattr(module, 'mirror_lock', nullcontext)
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: None)
    original = b'// reviewed live entry\n'
    (module.ROOT / 'sync-outbound.js').write_bytes(original)
    request = {
        'action': 'prepare',
        'expected_live': {name: hashlib.sha256(original).hexdigest() if name == 'sync-outbound.js' else None for name in module.NAMES},
        'files': {name: {'content': base64.b64encode(('// candidate ' + name).encode()).decode(), 'sha256': hashlib.sha256(('// candidate ' + name).encode()).hexdigest()} for name in module.NAMES},
    }
    return module, request, original


def test_prepare_changes_no_live_file(release):
    module, request, original = release
    assert module.execute(request)['status'] == 'prepared'
    assert (module.ROOT / 'sync-outbound.js').read_bytes() == original
    assert not (module.ROOT / 'outbound-store.mjs').exists()


def test_activation_requires_prepared_candidate(release):
    module, request, original = release
    request['action'] = 'activate'
    with pytest.raises(RuntimeError, match='prepared release'):
        module.execute(request)
    assert (module.ROOT / 'sync-outbound.js').read_bytes() == original


def test_live_drift_rejected_before_activation(release):
    module, request, _ = release
    module.execute(request)
    (module.ROOT / 'sync-outbound.js').write_bytes(b'new third party change')
    request['action'] = 'activate'
    with pytest.raises(RuntimeError, match='changed since review'):
        module.execute(request)
    assert not (module.ROOT / 'outbound-store.mjs').exists()


def test_activate_helpers_first_and_repeat_is_idempotent(release, monkeypatch):
    module, request, _ = release
    module.execute(request)
    replacements = []
    replace = module.os.replace
    def record(src, dst):
        if Path(dst).parent == module.ROOT:
            replacements.append(Path(dst).name)
        return replace(src, dst)
    monkeypatch.setattr(module.os, 'replace', record)
    request['action'] = 'activate'
    first = module.execute(request)
    assert replacements == list(module.NAMES)
    assert module.execute(request) == first
    request['action'] = 'prepare'
    assert module.execute(request) == first
    assert replacements == list(module.NAMES)


def test_partial_activation_restores_original_and_removes_new_helpers(release, monkeypatch):
    module, request, original = release
    module.execute(request)
    replace = module.os.replace
    def fail_entry(src, dst):
        if Path(dst) == module.ROOT / 'sync-outbound.js':
            raise OSError('injected activation failure')
        return replace(src, dst)
    monkeypatch.setattr(module.os, 'replace', fail_entry)
    request['action'] = 'activate'
    with pytest.raises(OSError):
        module.execute(request)
    assert (module.ROOT / 'sync-outbound.js').read_bytes() == original
    assert not (module.ROOT / 'outbound-store.mjs').exists()
    assert not (module.ROOT / 'inspection-contract.mjs').exists()
    assert 'rolled_back' in next(module.ROOT.rglob('release.json')).read_text()


def test_syntax_failure_does_not_mark_prepared(release, monkeypatch):
    module, request, original = release
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ['node', '--check'])
    monkeypatch.setattr(module.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        module.execute(request)
    assert not list(module.ROOT.rglob('release.json'))
    assert (module.ROOT / 'sync-outbound.js').read_bytes() == original


@pytest.mark.parametrize('mutation', ['path', 'digest', 'baseline'])
def test_malformed_input_rejected(release, mutation):
    module, request, original = release
    if mutation == 'path':
        request['files']['../outside'] = request['files'].pop('outbound-store.mjs')
    elif mutation == 'digest':
        request['files']['outbound-store.mjs']['sha256'] = '0' * 64
    else:
        request['expected_live']['outbound-store.mjs'] = 'not-a-digest'
    with pytest.raises(ValueError):
        module.execute(request)
    assert (module.ROOT / 'sync-outbound.js').read_bytes() == original


def test_symlink_parent_rejected(release):
    module, request, _ = release
    outside = module.ROOT.parent / 'outside'
    outside.mkdir()
    try:
        (module.ROOT / '.deploy-state').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink privileges unavailable')
    with pytest.raises(ValueError, match='symlink'):
        module.execute(request)
    assert not list(outside.iterdir())


def test_release_lock_encloses_prepare_state_and_activate(release, monkeypatch):
    module, request, _ = release
    from contextlib import contextmanager
    active = False
    @contextmanager
    def locked():
        nonlocal active
        active = True
        try:
            yield
        finally:
            active = False
    original = module.execute_locked
    def assert_locked(value):
        assert active
        return original(value)
    monkeypatch.setattr(module, 'release_lock', locked)
    monkeypatch.setattr(module, 'execute_locked', assert_locked)
    module.execute(request)
    request['action'] = 'activate'
    assert module.execute(request)['status'] == 'verified'
