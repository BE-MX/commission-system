"""Serve old and new entrypoints continuously during a static-only release."""
from pathlib import Path
import json
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import office_release as office
import office_hot_static as hot
from static_sync import manifest


def setup_release(tmp_path, monkeypatch):
    destination, staged = tmp_path / 'frontend/dist', tmp_path / 'next'
    for root, version in ((destination, 'old'), (staged, 'new')):
        (root / 'assets').mkdir(parents=True)
        (root / 'assets' / (version + '.js')).write_text(version)
        (root / 'index.html').write_text(version)
    old = manifest(destination)
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if args[:3] == ['git', 'rev-parse', 'HEAD']: return 'old'
        if args[1:2] == ['status']: return 'SERVICE_RUNNING'
        return ''
    monkeypatch.setattr(office, 'run', run)
    monkeypatch.setattr(office, 'STATE', tmp_path / 'state')
    office.STATE.mkdir()
    monkeypatch.setattr(office, 'health', lambda *_: None)
    monkeypatch.setattr(office, 'protocol_observation', lambda *_: {})
    monkeypatch.setattr(office, 'marker', lambda *_: {'files': old})
    prepared = dict(nssm='nssm', live=tmp_path, revision='new', previous='old',
        backend_changed=False, connector_changed=False, schema_changed=False,
        static=[('frontend', destination, staged, manifest(staged))], port=8001, schema='197',
        python='isolated-python', application=Path('python.exe'), parameters='')
    return prepared, commands, destination, staged


def test_frontend_only_release_keeps_api_and_old_assets(tmp_path, monkeypatch):
    prepared, commands, destination, _ = setup_release(tmp_path, monkeypatch)
    result = office.activate_locked(prepared)
    assert result['status'] == 'static_updated'
    assert (destination / 'index.html').read_text() == 'new'
    assert (destination / 'assets/old.js').read_text() == 'old'
    assert not any(len(c) > 1 and c[1] in {'start', 'stop'} for c in commands)


@pytest.mark.parametrize('failure', ['git', 'marker'])
def test_failure_after_new_html_restores_entry_and_receipts(tmp_path, monkeypatch, failure):
    prepared, commands, destination, _ = setup_release(tmp_path, monkeypatch)
    prior = {'revision': 'old', 'status': 'unchanged'}
    (office.STATE / 'office-success.json').write_text(json.dumps(prior))
    original_run, original_json, original_copy = office.run, hot.atomic_json, hot.copy_atomic
    seen = []
    def copy(source, target):
        assert (destination / 'index.html').exists()
        original_copy(source, target)
        seen.append((destination / 'index.html').read_text())
        assert (destination / 'assets/old.js').exists()
        if seen[-1] == 'new': assert (destination / 'assets/new.js').exists()
    def run(args, **kwargs):
        if failure == 'git' and args[:2] == ['git', 'merge']:
            raise RuntimeError('injected after HTML')
        return original_run(args, **kwargs)
    def save(path, value):
        if failure == 'marker' and path.name == 'office-success.json' and value.get('status') == 'static_updated':
            raise RuntimeError('injected receipt write')
        original_json(path, value)
    monkeypatch.setattr(hot, 'copy_atomic', copy)
    monkeypatch.setattr(office, 'run', run)
    monkeypatch.setattr(hot, 'atomic_json', save)
    with pytest.raises(RuntimeError, match='injected'): office.activate_locked(prepared)
    assert 'new' in seen and seen[-1] == 'old'
    assert (destination / 'assets/new.js').exists()
    assert json.loads((office.STATE / 'office-success.json').read_text()) == prior
    assert json.loads((office.STATE / 'office-static-switch.json').read_text())['status'] == 'rolled_back'
    assert not any(len(c) > 1 and c[1] in {'start', 'stop'} for c in commands)


def test_corrupt_backup_leaves_pending_and_blocks_all_followup_paths(tmp_path, monkeypatch):
    prepared, commands, destination, _ = setup_release(tmp_path, monkeypatch)
    original_run = office.run
    def run(args, **kwargs):
        if args[:2] == ['git', 'merge']:
            backup = next(office.STATE.glob('office-previous-*'))
            (backup / 'index.html').write_text('corrupt')
            raise RuntimeError('injected rollback failure')
        return original_run(args, **kwargs)
    monkeypatch.setattr(office, 'run', run)
    with pytest.raises(ValueError, match='corrupt retained'): office.activate_locked(prepared)
    assert (destination / 'index.html').read_text() == 'new'
    assert json.loads((office.STATE / 'office-static-switch.json').read_text())['status'] == 'applying'
    for backend_changed in (False, True):
        prepared.update(static=[], backend_changed=backend_changed)
        with pytest.raises(RuntimeError, match='Unfinished static switch'): office.activate_locked(prepared)
    assert not any(len(c) > 1 and c[1] in {'start', 'stop'} for c in commands)


@pytest.mark.parametrize('case', ['shared_asset', 'new_html', 'unmounted'])
def test_unsafe_static_change_falls_back_to_normal_release(tmp_path, monkeypatch, case):
    prepared, _, destination, staged = setup_release(tmp_path, monkeypatch)
    if case == 'shared_asset':
        (destination / 'config.js').write_text('old')
        (staged / 'config.js').write_text('new')
    elif case == 'new_html':
        (staged / 'extra.html').write_text('new')
    else:
        (destination / 'index.html').unlink()
    prepared['static'][0] = ('frontend', destination, staged, manifest(staged))
    assert not hot.eligible(prepared['static'])
