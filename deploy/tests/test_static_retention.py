"""Retention safety tests use isolated temporary directories, no business services."""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_static_retention as office
import remote_static as cloud
import static_retention as policy
import static_sync
from unittest.mock import Mock

NOW = 1_800_000_000
DAY = 24 * 3600


def tree(root, label):
    files = {'index.html': label.encode(), 'assets/' + label + '.js': label.encode(),
             'downloads/test.zip': (label + '-zip').encode()}
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}


class OfficeRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.live = Path(self.tmp.name)
        self.state = self.live / '.deploy_state'
        self.current = self.live / 'frontend/dist'
        self.files = tree(self.current, 'current')
        policy.atomic_json(self.state / 'office-frontend.json', {'files': self.files})

    def tearDown(self):
        self.tmp.cleanup()

    def backup(self, label, age, cache=True):
        root = self.state / ('office-previous-frontend-' + str((NOW - age) * 1_000_000_000))
        files = tree(root, label)
        if cache:
            tree(self.state / 'builds' / ('frontend-' + hashlib.sha256(label.encode()).hexdigest()), label)
        (self.current / ('assets/' + label + '.js')).write_bytes(label.encode())
        return root, files

    def test_bounded_backups_grace_survives_directory_deletion_and_retry(self):
        expired, _ = self.backup('expired', 30 * DAY, cache=False)
        grace, _ = self.backup('grace', 6 * DAY)
        second, _ = self.backup('second', 2 * DAY)
        latest, _ = self.backup('latest', DAY)
        # An irrelevant PM backup and uploads must never enter the cleanup plan.
        pm = self.state / 'office-previous-frontend-pm-1'
        tree(pm, 'pm')
        upload = self.live / 'backend/uploads/customer.jpg'
        upload.parent.mkdir(parents=True)
        upload.write_bytes(b'business')
        os.utime(self.current / 'assets/expired.js', (NOW, NOW))
        with patch.object(office.time, 'time', return_value=NOW):
            preview = office.cleanup(self.live, True)
            self.assertEqual(preview['backup_count_after'], 2)
            self.assertTrue(expired.exists())
            office.cleanup(self.live)
            retry = office.cleanup(self.live)
        self.assertEqual(retry['delete_paths'], 0)
        self.assertFalse(expired.exists())
        self.assertFalse(grace.exists())
        self.assertTrue((self.current / 'assets/grace.js').exists())
        self.assertFalse((self.current / 'assets/expired.js').exists())
        self.assertTrue(pm.exists())
        self.assertEqual(upload.read_bytes(), b'business')
        for root in (second, latest):
            self.assertTrue((root / 'assets/current.js').exists())
            self.assertTrue((root / 'downloads/test.zip').exists())
        with patch.object(office.time, 'time', return_value=NOW + 8 * DAY):
            office.cleanup(self.live)
        self.assertFalse((self.current / 'assets/grace.js').exists())
        self.assertTrue((self.current / 'assets/second.js').exists())

    def test_missing_legacy_manifest_blocks_before_any_delete(self):
        expired, _ = self.backup('expired', 30 * DAY, cache=False)
        self.backup('unverifiable', DAY, cache=False)
        (self.state / 'builds').mkdir()
        with patch.object(office.time, 'time', return_value=NOW), self.assertRaisesRegex(ValueError, 'reconstruct'):
            office.cleanup(self.live)
        self.assertTrue(expired.exists())
        self.assertTrue((self.current / 'assets/expired.js').exists())

    def test_corrupt_rollback_blocks_deletion(self):
        expired, _ = self.backup('expired', 30 * DAY, cache=False)
        self.backup('second', 2 * DAY)
        latest, own = self.backup('latest', DAY)
        office.record_backup(self.state, latest, own)
        (latest / 'assets/latest.js').write_bytes(b'bad')
        with patch.object(office.time, 'time', return_value=NOW), self.assertRaisesRegex(ValueError, 'corrupt'):
            office.cleanup(self.live)
        self.assertTrue(expired.exists())

    def test_old_rollback_assets_are_retained_even_beyond_grace(self):
        self.backup('latest', 20 * DAY)
        self.backup('second', 21 * DAY)
        self.backup('expired', 22 * DAY, cache=False)
        with patch.object(office.time, 'time', return_value=NOW):
            office.cleanup(self.live)
        self.assertTrue((self.current / 'assets/latest.js').exists())
        self.assertFalse((self.current / 'assets/expired.js').exists())

    def test_paths_and_conflicting_assets_are_rejected(self):
        for name in ('../x', '/x', 'C:/x', 'assets/../x', 'assets/x\\y'):
            with self.assertRaises(ValueError):
                policy.safe_relative(name)
        a = dict(self.files)
        b = dict(self.files, **{'assets/current.js': 'f' * 64})
        with self.assertRaisesRegex(ValueError, 'reused'):
            policy.asset_union([a, b])
        with self.assertRaisesRegex(ValueError, 'escaped'):
            policy.apply_cleanup({'deletes': [self.current], 'copies': []}, [self.current])

    def test_existing_staged_rollback_is_protected_through_client_prepare(self):
        result = {'staged': True, 'missing': [], 'initialized': True,
                  'active_artifact': 'b' * 64, 'artifact': 'a' * 64}
        remote = Mock(side_effect=[result, {}])
        with patch.object(static_sync, 'remote', remote), patch.object(static_sync, 'run') as upload:
            static_sync.prepare(self.current, 'target', '/registered', self.state, 'leshine.cloud')
        self.assertEqual(remote.call_count, 2)
        self.assertEqual(remote.call_args.args[1]['action'], 'prepared')
        upload.assert_not_called()

    def test_legacy_index_match_requires_matching_public_files(self):
        latest, own = self.backup('latest', DAY)
        alternate = self.state / 'builds' / ('frontend-' + 'f' * 64)
        tree(alternate, 'latest')
        (alternate / 'downloads/test.zip').write_bytes(b'other public bytes')
        self.assertEqual(office.legacy_manifest(latest, self.state), own)

    def test_interrupted_copy_never_leaves_partial_protected_asset(self):
        destination = self.current / 'assets/new.js'
        source = self.current / 'assets/current.js'
        plan = {'deletes': [], 'copies': [(source, destination)], 'bytes': 0,
                'kept': [], 'removed': [], 'assets': 1}
        def fail_copy(original, temporary):
            temporary.write_bytes(b'partial')
            raise OSError('disk full')
        with patch.object(policy.shutil, 'copyfile', side_effect=fail_copy), self.assertRaisesRegex(OSError, 'disk full'):
            policy.apply_cleanup(plan, [self.current])
        self.assertFalse(destination.exists())
        self.assertFalse(list(destination.parent.glob('new.js.next-*')))

    def test_copy_from_deleted_release_has_stable_completion_summary(self):
        old = self.state / 'old-release'
        files = tree(old, 'grace')
        assets = policy.asset_union([self.files, files])
        plan = policy.plan_cleanup([(self.current, self.files)], [old], assets, [old])
        result = policy.apply_cleanup(plan, [self.live])
        self.assertEqual(result['copy_bytes'], len(b'grace'))
        self.assertFalse(old.exists())
        self.assertEqual((self.current / 'assets/grace.js').read_bytes(), b'grace')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction protection')
    def test_windows_junction_blocks_before_deletion(self):
        expired, _ = self.backup('expired', 30 * DAY, cache=False)
        self.backup('second', 2 * DAY)
        latest, _ = self.backup('latest', DAY)
        outside = self.live / 'business-storage'
        outside.mkdir()
        (outside / 'proof.jpg').write_bytes(b'business')
        link = expired / 'junction'
        command = f"New-Item -ItemType Junction -Path '{link}' -Value '{outside}' | Out-Null"
        subprocess.run(['powershell', '-NoProfile', '-Command', command], check=True, capture_output=True)
        with patch.object(office.time, 'time', return_value=NOW), self.assertRaisesRegex(ValueError, 'reparse'):
            office.cleanup(self.live)
        self.assertTrue(expired.exists())
        self.assertTrue(latest.exists())
        self.assertEqual((outside / 'proof.jpg').read_bytes(), b'business')


@unittest.skipUnless(sys.platform == 'linux', 'Linux managed symlink semantics')
class CloudRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.root = self.directory / 'site'
        self.http = patch.object(cloud, 'verify_http')
        self.http.start()

    def tearDown(self):
        self.http.stop()
        self.tmp.cleanup()

    def stage(self, label):
        files = {'index.html': label.encode(), 'assets/' + label + '.js': label.encode()}
        archive = self.directory / 'bundle.tar.gz'
        with tarfile.open(archive, 'w:gz') as bundle:
            for name, content in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
        own = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
        cloud.stage(self.root, own, archive)
        return own

    def publish(self, label, moment):
        with patch.object(cloud.time, 'time', return_value=moment):
            files = self.stage(label)
            cloud.activate(self.root, files, cloud.plan(self.root, files)['active_artifact'])
        return files

    def test_retirement_window_keeps_last_two_and_pending_candidates(self):
        a = self.publish('a', NOW - 40 * DAY)
        self.publish('b', NOW - 30 * DAY)
        self.publish('c', NOW - 20 * DAY)
        self.publish('d', NOW - 10 * DAY)
        e = self.publish('e', NOW - DAY)
        # Re-preparing an old successfully retired version must protect it too.
        with patch.object(cloud.time, 'time', return_value=NOW):
            self.stage('a')
            pending = self.stage('pending')
            result = cloud.cleanup(self.root, 'leshine.cloud')
            self.assertTrue(result['removed'])
            retry = cloud.cleanup(self.root, 'leshine.cloud')
        self.assertEqual(retry['delete_paths'], 0)
        state, _, _ = cloud.layout(self.root)
        self.assertTrue((state / 'versions' / cloud.artifact_id(a)).exists())
        self.assertTrue((state / 'versions' / cloud.artifact_id(pending)).exists())
        self.assertTrue((self.root / 'assets/c.js').exists())  # second rollback
        self.assertFalse((self.root / 'assets/b.js').exists())
        self.assertEqual(cloud.plan(self.root, e)['active_artifact'], cloud.artifact_id(e))
        with patch.object(cloud.time, 'time', return_value=NOW):
            cloud.activate(self.root, a, cloud.artifact_id(e))
        self.assertTrue((self.root / 'assets/e.js').exists())
        self.assertTrue((self.root / 'assets/c.js').exists())

    def test_bootstrap_grace_is_persisted_and_does_not_slide(self):
        self.publish('a', NOW - 40 * DAY)
        self.publish('b', NOW - 30 * DAY)
        self.publish('c', NOW - 20 * DAY)
        self.publish('d', NOW - 10 * DAY)
        state, _, _ = cloud.layout(self.root)
        (state / 'retention-history.json').unlink()
        with patch.object(cloud.time, 'time', return_value=NOW):
            result = cloud.cleanup(self.root, 'leshine.cloud')
        self.assertEqual(result['legacy_grace_versions'], 3)
        self.assertFalse(result['removed'])
        with patch.object(cloud.time, 'time', return_value=NOW + 8 * DAY):
            result = cloud.cleanup(self.root, 'leshine.cloud')
        self.assertEqual(result['legacy_grace_versions'], 0)
        self.assertEqual(len(result['removed']), 1)

    def test_rapid_publishes_keep_three_directories_and_recent_chunks(self):
        for index, label in enumerate(('a', 'b', 'c', 'd', 'e')):
            self.publish(label, NOW - 100 + index)
        with patch.object(cloud.time, 'time', return_value=NOW):
            cloud.cleanup(self.root, 'leshine.cloud')
        state, _, _ = cloud.layout(self.root)
        self.assertEqual(len(list((state / 'versions').iterdir())), 3)
        for label in ('a', 'b', 'c', 'd', 'e'):
            self.assertTrue((self.root / ('assets/' + label + '.js')).exists())
        with patch.object(cloud.time, 'time', return_value=NOW + 8 * DAY):
            cloud.cleanup(self.root, 'leshine.cloud')
        self.assertFalse((self.root / 'assets/a.js').exists())

    def test_symlink_in_deletion_tree_blocks_all_deletion(self):
        self.publish('a', NOW - 40 * DAY)
        self.publish('b', NOW - 30 * DAY)
        self.publish('c', NOW - 20 * DAY)
        self.publish('d', NOW - 10 * DAY)
        state, _, _ = cloud.layout(self.root)
        history = policy.read_history(state / 'retention-history.json')
        oldest = min(history['releases'], key=lambda ident: history['releases'][ident]['retired_at'] or NOW)
        (state / 'versions' / oldest / 'escape').symlink_to(self.directory)
        with patch.object(cloud.time, 'time', return_value=NOW), self.assertRaisesRegex(ValueError, 'symlink'):
            cloud.cleanup(self.root, 'leshine.cloud')
        self.assertEqual(len(list((state / 'versions').iterdir())), 4)


if __name__ == '__main__':
    unittest.main()
