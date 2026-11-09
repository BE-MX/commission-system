import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import colorwork_release as release
import colorwork_runtime as runtime


def test_candidate_limits_changes_to_wrangler(tmp_path):
    def git(*args):
        return runtime.git(tmp_path, *args)

    def commit(version, extra=False):
        (tmp_path / runtime.PACKAGE).write_text(json.dumps({'devDependencies': {'wrangler': version}}))
        (tmp_path / runtime.LOCK).write_text(version)
        if extra:
            (tmp_path / 'backend.py').write_text('unexpected change')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', version)
        return git('rev-parse', 'HEAD')

    git('init', '-q')
    (tmp_path / runtime.PACKAGE).parent.mkdir()
    old = commit('4.92.0')
    new = commit('4.100.0')
    assert runtime.validate_candidate(tmp_path, old, new) == '4.100.0'
    forbidden = commit('4.101.0', extra=True)
    with pytest.raises(ValueError, match='outside'):
        runtime.validate_candidate(tmp_path, new, forbidden)
    with pytest.raises(ValueError, match='one commit'):
        runtime.validate_candidate(tmp_path, old, forbidden)


@pytest.fixture
def staged(tmp_path, monkeypatch):
    state = tmp_path / 'colorwork'
    source = tmp_path / ('b' * 40)
    old_source = tmp_path / ('a' * 40)
    (state / 'data').mkdir(parents=True)
    (state / 'backups').mkdir()
    (state / 'data/example.sqlite').write_bytes(b'persistent store')
    folder = source / 'colorwork-workbench'
    (folder / 'drizzle').mkdir(parents=True)
    (folder / 'drizzle/001.sql').write_text('SELECT 1;')
    node = str(tmp_path / 'bin/node')
    migrations = release.migration_files(folder)
    old_unit = state / ('unit-' + old_source.name + '.service')
    old_unit.write_text(release.MANAGED + '\nold')
    new_unit = state / ('unit-' + source.name + '.service')
    new_unit.write_text(release.unit_text(folder, state, node, 'ubuntu'))
    installed = tmp_path / 'ark-colorwork.service'
    installed.write_bytes(old_unit.read_bytes())
    previous = {'source': str(old_source), 'status': 'succeeded', 'migrations': migrations}
    prepared = {'source': str(source), 'node': node, 'unit': str(new_unit), 'migrations': migrations}
    release.atomic_json(state / 'success.json', previous)
    release.atomic_json(state / 'current.json', previous)
    release.atomic_json(state / ('prepared-' + source.name + '.json'), prepared)
    calls = []

    def run(args, cwd):
        calls.append(args[2:])
        if args[2] == 'install':
            Path(args[-1]).write_bytes(Path(args[-2]).read_bytes())

    monkeypatch.setattr(release, 'UNIT_DIRECTORY', tmp_path)
    monkeypatch.setattr(release, 'run', run)
    monkeypatch.setattr(release, 'verify_history', Mock())
    monkeypatch.setattr(runtime, 'wait_ready', Mock())
    return state, source, previous, installed, calls


def test_activation_switches_only_colorwork_and_preserves_data(staged):
    state, source, previous, installed, calls = staged
    runtime.activate(state, source, previous, release)
    result = json.loads((state / 'success.json').read_text())
    assert result == json.loads((state / 'current.json').read_text())
    assert result['status'] == 'succeeded'
    assert result['source'] == str(source)
    assert (Path(result['backup']) / 'example.sqlite').read_bytes() == b'persistent store'
    assert (state / 'data/example.sqlite').read_bytes() == b'persistent store'
    assert calls[0] == ['systemctl', 'stop', 'ark-colorwork']
    assert calls[1][0] == 'install'
    assert calls[2:] == [['systemctl', 'daemon-reload'], ['systemctl', 'start', 'ark-colorwork']]
    assert str(source) in installed.read_text()


def test_failed_readiness_restores_old_unit_and_receipts(staged):
    state, source, previous, installed, calls = staged
    runtime.wait_ready.side_effect = [RuntimeError('health failed'), None]
    with pytest.raises(RuntimeError, match='health failed'):
        runtime.activate(state, source, previous, release)
    assert installed.read_text() == release.MANAGED + '\nold'
    assert previous == json.loads((state / 'current.json').read_text())
    assert previous == json.loads((state / 'success.json').read_text())
    assert json.loads((state / ('runtime-rollback-' + source.name + '.json')).read_text())['status'] == 'rolled_back'
    assert calls.count(['systemctl', 'start', 'ark-colorwork']) == 2


def test_migration_change_is_rejected_before_stopping_colorwork(staged):
    state, source, previous, _, calls = staged
    (source / 'colorwork-workbench/drizzle/001.sql').write_text('SELECT 2;')
    with pytest.raises(RuntimeError, match='identical Colorwork migrations'):
        runtime.activate(state, source, previous, release)
    assert not calls


def test_failed_backup_restarts_previous_unit_without_retaining_partial_copy(staged, monkeypatch):
    state, source, previous, installed, calls = staged

    def fail_copy(_, staging):
        staging.mkdir()
        raise OSError('disk full')

    monkeypatch.setattr(runtime.shutil, 'copytree', fail_copy)
    with pytest.raises(OSError, match='disk full'):
        runtime.activate(state, source, previous, release)
    assert installed.read_text() == release.MANAGED + '\nold'
    assert calls[-1] == ['systemctl', 'start', 'ark-colorwork']
    assert not list((state / 'backups').iterdir())
    assert json.loads((state / 'current.json').read_text()) == previous
