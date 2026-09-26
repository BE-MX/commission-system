import json
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import colorwork_backup_retention as retention


@pytest.fixture
def store(tmp_path):
    state = tmp_path / 'colorwork'
    backups = state / 'backups'
    backups.mkdir(parents=True)
    names = [f'{i:040x}-{i:032x}' for i in range(1, 5)]
    for name in names:
        folder = backups / name / 'v3'
        (folder / 'r2/site-creator-r2/blobs').mkdir(parents=True)
        (folder / 'r2/site-creator-r2/blobs/blob').write_bytes(b'asset')
        (folder / 'r2/miniflare-R2BucketObject').mkdir()
        with sqlite3.connect(folder / 'r2/miniflare-R2BucketObject/bucket.sqlite') as db:
            db.execute('CREATE TABLE _mf_objects(key TEXT, blob_id TEXT, size INTEGER)')
            db.execute('CREATE TABLE _mf_multipart_parts(blob_id TEXT, size INTEGER, object_key TEXT)')
            db.execute("INSERT INTO _mf_objects VALUES ('key','blob',5)")
        db.close()
        with sqlite3.connect(folder / 'data.sqlite') as db:
            db.execute('CREATE TABLE sample(id INTEGER)')
        db.close()
    for name in ['current.json', 'success.json']:
        (state / name).write_text(json.dumps({
            'status': 'succeeded', 'source': '/candidate',
            'backup': str(backups / names[-1]),
        }))
    (state / 'maintenance').mkdir()
    (state / 'maintenance/retention-last.json').write_text(json.dumps({
        'created': {name: i for i, name in enumerate(names)},
    }))
    return state, names


def test_keep_two_and_delete_only_old_backups(store):
    state, names = store
    live = state / 'data'
    live.mkdir()
    (live / 'business').write_text('preserve')
    plan = retention.make_plan(state)
    assert plan['keep'] == names[-2:]
    assert plan['delete'] == names[:2]
    retention.apply_plan(state, plan)
    assert sorted(x.name for x in (state / 'backups').iterdir()) == names[-2:]
    assert (live / 'business').read_text() == 'preserve'
    assert retention.make_plan(state)['delete'] == []


def test_recovery_reference_is_protected_even_if_old(store):
    state, names = store
    for filename in ['current.json', 'success.json']:
        data = json.loads((state / filename).read_text())
        data['backup'] = str(state / 'backups' / names[0])
        (state / filename).write_text(json.dumps(data))
    plan = retention.make_plan(state)
    assert set(plan['keep']) == {names[0], *names[-2:]}
    assert plan['delete'] == [names[1]]


@pytest.mark.parametrize('status', ['failed', 'activating', 'prepared'])
def test_unfinished_release_blocks_all_deletion(store, status):
    state, names = store
    p = state / 'current.json'
    d = json.loads(p.read_text()); d['status'] = status; p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError, match='succeeded'):
        retention.make_plan(state)
    assert len(list((state / 'backups').iterdir())) == 4


def test_journal_drift_after_plan_blocks_deletion(store):
    state, names = store
    plan = retention.make_plan(state)
    (state / 'current.json').write_text('{}')
    with pytest.raises(RuntimeError, match='changed'):
        retention.apply_plan(state, plan)
    assert len(list((state / 'backups').iterdir())) == 4


def test_missing_referenced_backup_blocks_cleanup(store):
    state, _ = store
    p = state / 'success.json'
    d = json.loads(p.read_text()); d['backup'] += '-missing'; p.write_text(json.dumps(d))
    with pytest.raises(RuntimeError):
        retention.make_plan(state)


def test_bad_retained_database_blocks_cleanup(store):
    state, names = store
    (state / 'backups' / names[-2] / 'v3/data.sqlite').write_bytes(b'broken sqlite')
    with pytest.raises(sqlite3.DatabaseError):
        retention.apply_plan(state, retention.make_plan(state))
    assert len(list((state / 'backups').iterdir())) == 4


def test_unknown_directory_blocks_cleanup(store):
    state, _ = store
    (state / 'backups/manual-business-data').mkdir()
    with pytest.raises(RuntimeError, match='Unrecognized'):
        retention.make_plan(state)


def test_failed_removal_preserves_original_backup_order(store, monkeypatch):
    state, names = store
    original = retention.shutil.rmtree
    monkeypatch.setattr(retention.shutil, 'rmtree', lambda p: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):
        retention.apply_plan(state, retention.make_plan(state))
    monkeypatch.setattr(retention.shutil, 'rmtree', original)
    retry = retention.make_plan(state)
    assert retry['keep'] == names[-2:]
    assert retry['delete'] == names[:2]


def test_symlink_target_refused(store):
    state, names = store
    link = state / 'backups' / names[0] / 'v3/escape'
    try:
        link.symlink_to(state, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation needs OS permission')
    with pytest.raises(RuntimeError, match='Unsafe'):
        retention.make_plan(state)


def test_same_name_replacement_after_plan_refused(store):
    state, names = store
    plan = retention.make_plan(state)
    p = state / 'backups' / names[0]
    p.rename(state / 'saved')
    p.mkdir()
    with pytest.raises(RuntimeError, match='identity'):
        retention.apply_plan(state, plan)


def test_missing_retained_r2_blob_blocks_all_deletion(store):
    state, names = store
    blob = state / 'backups' / names[-2] / 'v3/r2/site-creator-r2/blobs/blob'
    blob.unlink()
    with pytest.raises(RuntimeError, match='blob missing'):
        retention.apply_plan(state, retention.make_plan(state))
    assert len(list((state / 'backups').iterdir())) == 4


def test_incomplete_multipart_metadata_blocks_deletion(store):
    state, names = store
    db = sqlite3.connect(state / 'backups' / names[-2] / 'v3/r2/miniflare-R2BucketObject/bucket.sqlite')
    db.execute("INSERT INTO _mf_objects VALUES ('multipart',NULL,10)")
    db.commit(); db.close()
    with pytest.raises(RuntimeError, match='multipart'):
        retention.apply_plan(state, retention.make_plan(state))
    assert len(list((state / 'backups').iterdir())) == 4
