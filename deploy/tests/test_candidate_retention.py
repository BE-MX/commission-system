"""Real temporary Git worktrees; no office services, SSH or business database."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import candidate_retention as retention
import candidate_references as references
import desktop_events


@pytest.fixture
def release(tmp_path):
    live = tmp_path / 'office'
    live.mkdir()
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=live, text=True, stderr=subprocess.DEVNULL).strip()
    git('init')
    git('config', 'user.name', 'Retention Test')
    git('config', 'user.email', 'retention@example.invalid')
    (live / '.gitignore').write_text('.deploy_state/\nnode_modules/\nbackend/uploads/\n.env*\n')
    (live / 'frontend').mkdir()
    (live / 'frontend/package.json').write_text('{}')
    revisions = []
    for number in range(5):
        (live / 'code.txt').write_text(str(number))
        git('add', '.')
        git('commit', '-m', 'Fixture ' + str(number))
        revisions.append(git('rev-parse', 'HEAD'))
    state = live / '.deploy_state'
    state.mkdir()
    (state / 'publish.lock').write_text(str(os.getpid()))
    retention.atomic_json(state / 'publish-current.json', {
        'status': 'succeeded', 'scope': 'office-and-cloud', 'revision': revisions[-1]})
    retention.atomic_json(state / 'candidate-retention/inventory.json', {
        'schema': 1, 'entries': {}, 'successes': revisions[-2::-1][:3]})
    return live, state, revisions, git


def candidate(release, *, kind='source', index=0, managed=True, age=8 * 86400):
    live, state, revisions, git = release
    name = revisions[index] if kind == 'source' else 'office-next-frontend-' + str(time.time_ns())
    path = state / 'sources' / name if kind == 'source' else state / name
    if kind == 'source':
        path.parent.mkdir(exist_ok=True)
        git('worktree', 'add', '--detach', str(path), revisions[index])
    else:
        path.mkdir()
        (path / 'index.html').write_text('owned staging')
    if managed:
        retention.record_created(state, path, revisions[index], kind)
        data = retention.registry(state)
        data['entries'][name]['created_at'] -= age
        retention.atomic_json(state / 'candidate-retention/inventory.json', data)
    return path


def cleanup(release, **kwargs):
    live, state, revisions, _ = release
    return retention.run(live, state / 'sources' / revisions[-1], revisions[-2], probe=lambda _: set(), **kwargs)


def test_removes_registered_ancestor_and_staging_but_keeps_legacy_and_rollbacks(release):
    old = candidate(release)
    stage = candidate(release, kind='static', index=4)  # stale prepare for current SHA
    legacy = candidate(release, index=1, managed=False)
    rollback = candidate(release, index=2)
    result = cleanup(release)
    assert set(result['removed']) == {old.name, stage.name}
    assert not old.exists() and not stage.exists()
    assert old.as_posix() not in release[3]('worktree', 'list', '--porcelain')
    assert legacy.exists() and rollback.exists()
    assert retention.registry(release[1])['successes'] == release[2][-1:1:-1]


@pytest.mark.parametrize('kind', ['source', 'static'])
def test_grace_period_does_not_probe_or_delete_recent_candidates(release, kind):
    path = candidate(release, kind=kind, age=86400)
    live, state, revisions, _ = release
    probe = Mock(side_effect=AssertionError('unneeded expensive runtime probe'))
    result = retention.run(live, state / 'sources' / revisions[-1], revisions[-2], probe=probe)
    assert not result['removed'] and path.exists()


@pytest.mark.parametrize('status', ['prepared', 'failed', 'activating'])
def test_only_successful_full_release_can_delete(release, status):
    path = candidate(release)
    record = retention.read(release[1] / 'publish-current.json')
    record['status'] = status
    retention.atomic_json(release[1] / 'publish-current.json', record)
    with pytest.raises(RuntimeError, match='successful full release'):
        cleanup(release)
    assert path.exists()


def test_lock_must_be_owned_and_installed_revision_must_match(release):
    path = candidate(release)
    (release[1] / 'publish.lock').write_text('different-process')
    with pytest.raises(RuntimeError, match='owning publish lock'):
        cleanup(release)
    (release[1] / 'publish.lock').write_text(str(os.getpid()))
    release[3]('checkout', '--detach', release[2][-2])
    with pytest.raises(RuntimeError, match='Installed revision'):
        cleanup(release)
    assert path.exists()


@pytest.mark.parametrize('mutation', ['dirty', 'untracked', 'ignored-business', 'nested-node-modules'])
def test_local_or_ignored_business_content_blocks_source_removal(release, mutation):
    path = candidate(release)
    name = {'dirty': 'code.txt', 'untracked': 'local.txt', 'ignored-business': 'backend/uploads/photo.jpg',
            'nested-node-modules': 'backend/uploads/node_modules/important.txt'}[mutation]
    target = path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('preserve me')
    result = cleanup(release)
    assert not result['removed'] and target.read_text() == 'preserve me'
    assert result['skipped'][0]['reason'] in {'Unknown ignored source data', 'Source has local changes'}


def test_metadata_and_runtime_references_preserve_candidates(release):
    old = candidate(release)
    stage = candidate(release, kind='static')
    retention.atomic_json(release[1] / 'migration-tools/plan.json', {'source': str(old)})
    live, state, revisions, _ = release
    result = retention.run(live, state / 'sources' / revisions[-1], revisions[-2], probe=lambda _: {stage.name})
    assert not result['removed'] and old.exists() and stage.exists()


def test_unavailable_probe_fails_closed(release):
    path = candidate(release)
    live, state, revisions, _ = release
    with pytest.raises(RuntimeError, match='cannot inspect'):
        retention.run(live, state / 'sources' / revisions[-1], revisions[-2],
                      probe=Mock(side_effect=RuntimeError('cannot inspect')))
    assert path.exists()


def test_reference_added_during_validation_prevents_delete(release):
    path = candidate(release, kind='static')
    live, state, revisions, _ = release
    probe = Mock(side_effect=[set(), {path.name}])
    result = retention.run(live, state / 'sources' / revisions[-1], revisions[-2], probe=probe)
    assert path.exists() and result['skipped'][0]['reason'] == 'new-reference'


def test_count_budget_and_interrupted_delete_are_not_retried(release, monkeypatch):
    paths = [candidate(release, kind='static') for _ in range(retention.MAX_REMOVALS + 2)]
    result = cleanup(release)
    assert len(result['removed']) == retention.MAX_REMOVALS and sum(p.exists() for p in paths) == 2
    monkeypatch.setattr(retention.shutil, 'rmtree', Mock(side_effect=OSError('denied')))
    with pytest.raises(OSError):
        cleanup(release)
    receipt = retention.read(release[1] / 'candidate-retention/current.json')
    assert receipt['status'] == 'failed' and receipt['intent']
    with pytest.raises(RuntimeError, match='interrupted candidate'):
        cleanup(release)
    assert retention.shutil.rmtree.call_count == 1


def test_preview_preserves_inventory_and_interrupted_receipt(release):
    path = candidate(release, kind='static')
    receipt = release[1] / 'candidate-retention/current.json'
    retention.atomic_json(receipt, {'status': 'deleting', 'intent': path.name})
    inventory = release[1] / 'candidate-retention/inventory.json'
    before = (receipt.read_bytes(), inventory.read_bytes())
    result = cleanup(release, prepare_only=True)
    assert result['status'] == 'prepared' and result['planned'] == [path.name]
    assert path.exists() and (receipt.read_bytes(), inventory.read_bytes()) == before


def test_candidate_maintenance_rejects_mixed_actions(release):
    from types import SimpleNamespace
    from contextlib import nullcontext
    args = SimpleNamespace(candidate_retention_only=True, prepare_only=True, cloud_only=True)
    with pytest.raises(RuntimeError, match='only accepts'):
        retention.execute(args, release[0], release[0], nullcontext)


def test_maintenance_preserves_order_when_success_history_lags_installed_release(release, monkeypatch):
    from types import SimpleNamespace
    from contextlib import nullcontext
    live, state, revisions, _ = release
    args = SimpleNamespace(candidate_retention_only=True, prepare_only=True, revision=revisions[-1])
    action = Mock(return_value={'status': 'prepared'})
    monkeypatch.setattr(retention, 'run', action)
    retention.execute(args, live, live, nullcontext)
    assert action.call_args.args[2] == revisions[-2]
    retention.record_success(state, revisions[-1], revisions[-2])
    retention.execute(args, live, live, nullcontext)
    assert action.call_args.args[2] == revisions[-2]
    assert retention.registry(state)['successes'] == revisions[-1:1:-1]


def test_one_started_candidate_finishes_despite_soft_time_budget(release, monkeypatch):
    path = candidate(release, kind='static')
    clock = {'value': 0}
    monkeypatch.setattr(retention.time, 'monotonic', lambda: clock['value'])
    def validate(_):
        clock['value'] = retention.BUDGET_SECONDS + 1
    monkeypatch.setattr(retention, 'validate_static', validate)
    result = cleanup(release)
    assert path.name in result['removed'] and not path.exists()


def test_reparse_point_never_removes_external_sentinel(release):
    path = candidate(release, kind='static')
    outside = release[0].parent / 'business'
    outside.mkdir()
    (outside / 'sentinel').write_text('keep')
    link = path / 'assets'
    if os.name == 'nt':
        # Creating a fixture junction is non-destructive; cleanup uses native unlink.
        subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        result = cleanup(release)
        assert not result['removed'] and (outside / 'sentinel').read_text() == 'keep'
    finally:
        os.rmdir(link) if os.name == 'nt' else link.unlink()


def test_traversal_receipt_is_rejected(release):
    data = retention.registry(release[1])
    data['entries']['../business'] = {'kind': 'static', 'revision': release[2][0], 'created_at': 1}
    retention.atomic_json(release[1] / 'candidate-retention/inventory.json', data)
    with pytest.raises(ValueError, match='Unregistered candidate'):
        cleanup(release)


def test_source_dependency_junction_is_unlinked_without_touching_target(release):
    path = candidate(release)
    outside = release[0].parent / 'shared-dependencies'
    outside.mkdir()
    (outside / 'sentinel').write_text('keep')
    dep = path / 'frontend/node_modules'
    dep.mkdir(parents=True)
    link = dep / 'linked-package'
    if os.name == 'nt':
        subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        result = cleanup(release)
        assert path.name in result['removed'] and not path.exists()
        assert (outside / 'sentinel').read_text() == 'keep'
    finally:
        if link.exists():
            os.rmdir(link) if os.name == 'nt' else link.unlink()


@pytest.mark.parametrize('changed', [False, True])
def test_only_recorded_unchanged_copied_settings_can_be_deleted(release, changed):
    import hashlib
    path = candidate(release)
    setting = path / 'frontend/.env.production.local'
    setting.write_text('non-secret-fixture')
    retention.record_settings(release[1], path, {'frontend/.env.production.local': hashlib.sha256(setting.read_bytes()).hexdigest()})
    if changed:
        setting.write_text('manual-change')
    result = cleanup(release)
    assert path.exists() == changed
    assert bool(result['removed']) != changed


@pytest.mark.skipif(os.name != 'nt', reason='Windows absolute command path parsing')
def test_runtime_follows_external_script_without_swallowing_executable(tmp_path):
    live = tmp_path / 'office'
    live.mkdir()
    script = tmp_path / 'recovery tools' / 'resume.py'
    script.parent.mkdir()
    script.write_text('revision="' + 'c' * 40 + '"')
    command = 'C:\\Python\\python.exe "' + str(script) + '"'
    assert 'c' * 40 in references.inspect_runtime_text(command, live)
    command = 'C:\\Python\\python.exe ' + str(script)
    assert 'c' * 40 in references.inspect_runtime_text(command, live)


def test_encoded_launcher_references_and_bom_control_files(tmp_path):
    import base64
    revision = 'f' * 40
    content = '$revision="' + revision + '"'
    encoded = base64.b64encode(content.encode('utf-16le')).decode()
    assert revision in references.inspect_runtime_text('powershell -EncodedCommand ' + encoded, tmp_path)
    (tmp_path / 'recovery.json').write_text(json.dumps({'revision': revision}), encoding='utf-8-sig')
    assert revision in references.metadata_references(tmp_path)


def test_timings_record_failure_without_arguments_or_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv('ARK_DESKTOP_RUN_ID', raising=False)
    with pytest.raises(ValueError):
        with desktop_events.timing_session(tmp_path, prepare_only=True, revision='a' * 40):
            desktop_events.step('outer', 'outer', lambda: desktop_events.step('inner', 'inner',
                lambda: (_ for _ in ()).throw(ValueError('password=secret'))))
    files = list((tmp_path / 'timings').glob('*.json'))
    assert len(files) == 1
    text = files[0].read_text()
    record = json.loads(text)
    assert 'secret' not in text and record['status'] == 'failed'
    assert [row['key'] for row in record['steps']] == ['outer', 'inner']
    assert all(row['status'] == 'failed' and row['elapsed_ms'] >= 0 for row in record['steps'])
    assert record['started_at'].endswith('+08:00')
    assert desktop_events._timing is None


@pytest.mark.parametrize('fail_action', [False, True])
def test_timing_disk_failure_never_changes_action_outcome(tmp_path, monkeypatch, capsys, fail_action):
    monkeypatch.setattr(desktop_events, 'atomic_json', Mock(side_effect=OSError('private path disk full')))
    def action():
        if fail_action:
            raise ValueError('original action error')
        return 42
    if fail_action:
        with pytest.raises(ValueError, match='original action error'):
            with desktop_events.timing_session(tmp_path):
                desktop_events.step('action', 'action', action)
    else:
        with desktop_events.timing_session(tmp_path):
            assert desktop_events.step('action', 'action', action) == 42
    assert 'private path' not in capsys.readouterr().out
    assert desktop_events._timing is None


def test_timing_timestamp_uses_beijing_midnight_independent_of_host_timezone(monkeypatch):
    from datetime import datetime, timezone
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(desktop_events, 'datetime', Clock)
    assert desktop_events.timestamp() == '2026-10-17T00:00:00.000+08:00'
