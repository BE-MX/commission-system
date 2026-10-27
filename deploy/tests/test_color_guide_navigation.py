import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import color_guide_navigation as local
import color_guide_navigation_remote as release


class NavigationReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / '.deploy_state/color-guide-navigation'
        self.static = self.root / 'static'
        self.static.mkdir()
        self.static_state = self.root / 'static-releases'
        self.baseline, self.candidate = 'a' * 40, 'd' * 40
        self.head, self.dirty = self.baseline, False
        self.old_artifact = 'b' * 64
        self.before = {name: b'old-content' for name in release.PATHS}
        source = b'new-navigation'
        self.policy = {'source_sha256': release.digest(source), 'favorite_access': {
            release.URL: [{}, {}, {'anyPermission': ['colorwork_download:read', 'colorwork_edit:read', 'colorwork_master:read']}]}}
        self.after = {release.PATHS[0]: source, release.PATHS[1]: json.dumps(self.policy).encode()}
        for name in release.PATHS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.before[name])
        built = json.dumps({'git_sha': self.candidate, 'favorite_access': self.policy['favorite_access']}).encode()
        manifest = {'index.html': release.digest(b'html'), 'nav-manifest.json': release.digest(built)}
        self.new_artifact = release.remote_static.artifact_id(manifest)
        self.staged = self.static_state / 'versions' / self.new_artifact
        self.staged.mkdir(parents=True)
        (self.staged / 'nav-manifest.json').write_bytes(built)
        self.request = {'schema': 2, 'baseline': self.baseline, 'candidate': self.candidate, 'phase': 'activate',
            'bundle': '/tmp/ark-color-guide-' + self.candidate + '.bundle', 'bundle_sha256': 'e' * 64,
            'files': {name: {'before': release.digest(self.before[name]), 'after': release.digest(self.after[name])}
                      for name in release.PATHS},
            'static': {'root': str(self.static), 'host': 'leshine.cloud', 'expected': self.old_artifact,
                       'manifest': manifest}}
        self.inspection = {'static_artifact': self.old_artifact, 'bundle_sha256': self.request['bundle_sha256']}
        self.changed = list(release.PATHS)
        self.checkout_calls = []
        for attr, value in [('ROOT', self.root), ('STATE', self.state), ('STATIC_ROOT', self.static)]:
            mock = patch.object(release, attr, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(release, 'git', side_effect=self.fake_git)
        mock.start()
        self.addCleanup(mock.stop)
        mock = patch.object(release.remote_static, 'layout', side_effect=lambda root: (
            self.static_state, None, Path(self.old_artifact)))
        mock.start()
        self.addCleanup(mock.stop)

    def fake_git(self, *args):
        if args[0] == 'merge-base':
            return b''
        if args[0] == 'diff':
            return '\n'.join(self.changed).encode()
        if args[0] == 'ls-tree':
            return '\n'.join('100644 blob ' + 'f' * 40 + '\t' + name for name in self.changed).encode()
        if args[0] == 'show':
            revision, name = args[1].split(':', 1)
            return (self.before if revision == self.baseline else self.after)[name]
        if args[0] == 'rev-parse':
            return (self.candidate if args[1] == 'FETCH_HEAD' else self.head).encode()
        if args[0] == 'status':
            return b' M unexpected' if self.dirty else b''
        if args[0] == 'checkout':
            self.head = args[2]
            self.checkout_calls.append(self.head)
            for name, value in (self.before if self.head == self.baseline else self.after).items():
                (self.root / name).write_bytes(value)
            return b''
        if args[0] in {'bundle', 'fetch'}:
            return b''
        raise AssertionError(args)

    def activate(self, operation=None):
        with patch.object(release, 'inspect', return_value=self.inspection), \
             patch.object(release.remote_static, 'activate', side_effect=operation,
                          return_value={'artifact': self.new_artifact}):
            return release.execute(self.request)

    def test_rejects_mismatched_committed_source(self):
        self.request['files'][release.PATHS[0]]['after'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            release.validate_candidate(self.request)

    def test_rejects_removed_permission_gate(self):
        data = copy.deepcopy(self.policy)
        data['favorite_access'][release.URL] = [{}, {}, {}]
        value = json.dumps(data).encode()
        self.after[release.PATHS[1]] = value
        self.request['files'][release.PATHS[1]]['after'] = release.digest(value)
        with self.assertRaisesRegex(ValueError, 'group permissions'):
            release.validate_candidate(self.request)

    def test_rejects_unrelated_business_changes(self):
        self.changed.append('backend/app/auth/service.py')
        with self.assertRaisesRegex(ValueError, 'scope'):
            release.validate_candidate(self.request)

    def test_success_keeps_backup_and_clean_candidate(self):
        result = self.activate()
        self.assertEqual(result['status'], 'succeeded')
        self.assertTrue(result['checkout_clean'])
        self.assertEqual(self.head, self.candidate)
        self.assertEqual(self.checkout_calls, [self.candidate])
        self.assertFalse((self.state / 'pending.json').exists())
        record = json.loads((self.state / 'success.json').read_text())
        for index, name in enumerate(release.PATHS):
            self.assertEqual((self.root / name).read_bytes(), self.after[name])
            self.assertEqual((Path(record['backup']) / str(index)).read_bytes(), self.before[name])

    def test_failed_static_restores_baseline_commit(self):
        with self.assertRaisesRegex(RuntimeError, 'http failure'):
            self.activate(RuntimeError('http failure'))
        self.assertEqual(self.head, self.baseline)
        self.assertEqual(self.checkout_calls, [self.candidate, self.baseline])
        for name in release.PATHS:
            self.assertEqual((self.root / name).read_bytes(), self.before[name])
        self.assertFalse((self.state / 'pending.json').exists())

    def test_uncertain_static_preserves_candidate_and_pending(self):
        calls = 0
        def layout(root):
            nonlocal calls
            calls += 1
            return self.static_state, None, Path(self.old_artifact if calls == 1 else self.new_artifact)
        with patch.object(release.remote_static, 'layout', side_effect=layout):
            with self.assertRaisesRegex(RuntimeError, 'preserve candidate'):
                self.activate(RuntimeError('receipt failure'))
        self.assertTrue((self.state / 'pending.json').exists())
        self.assertEqual(self.head, self.candidate)
        self.assertEqual(self.checkout_calls, [self.candidate])

    def test_dirty_checkout_prevents_rollback_over_other_changes(self):
        def fail(*args):
            self.dirty = True
            raise RuntimeError('concurrent write')
        with self.assertRaisesRegex(RuntimeError, 'drift prevents'):
            self.activate(fail)
        self.assertTrue((self.state / 'pending.json').exists())
        self.assertEqual(self.checkout_calls, [self.candidate])

    def test_pending_blocks_retry(self):
        self.state.mkdir(parents=True)
        (self.state / 'pending.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'Interrupted'):
            release.inspect(self.request)

    def test_dirty_baseline_blocks_prepare(self):
        self.dirty = True
        with self.assertRaisesRegex(RuntimeError, 'tracked changes'):
            release.inspect(self.request)

    def test_rejects_stale_staged_frontend_before_checkout(self):
        bad = json.dumps({'git_sha': self.baseline, 'favorite_access': self.policy['favorite_access']}).encode()
        manifest = {**self.request['static']['manifest'], 'nav-manifest.json': release.digest(bad)}
        self.request['static']['manifest'] = manifest
        path = self.static_state / 'versions' / release.remote_static.artifact_id(manifest)
        path.mkdir()
        (path / 'nav-manifest.json').write_bytes(bad)
        with self.assertRaisesRegex(ValueError, 'approved navigation candidate'):
            self.activate()
        self.assertEqual(self.checkout_calls, [])
        self.assertFalse((self.state / 'pending.json').exists())

    def test_bundle_digest_failure_prevents_fetch(self):
        self.request['phase'] = 'stage'
        self.inspection['bundle_sha256'] = 'f' * 64
        with patch.object(release, 'inspect', return_value=self.inspection), \
             patch.object(release, 'git') as git:
            with self.assertRaisesRegex(ValueError, 'bundle digest'):
                release.execute(self.request)
        git.assert_not_called()

    def test_staging_does_not_switch_live_checkout(self):
        self.request['phase'] = 'stage'
        with patch.object(release, 'inspect', return_value=self.inspection):
            result = release.execute(self.request)
        self.assertEqual(result['status'], 'staged')
        self.assertEqual(self.checkout_calls, [])
        self.assertEqual(self.head, self.baseline)


class FixedPreparationTest(unittest.TestCase):
    def setUp(self):
        self.identity = {'schema': 2, 'baseline': 'a' * 40, 'candidate': 'd' * 40,
                         'files': {'nav': {'after': 'f' * 64}}, 'manifest': {'index.html': 'b' * 64}}
        self.prepared = {**self.identity, 'static': {'manifest': self.identity['manifest']}}

    def test_old_preparation_requires_explicit_archive(self):
        with self.assertRaisesRegex(ValueError, 'Legacy'):
            local.validate_prepared({'baseline': 'a' * 40}, self.identity)

    def test_modified_build_rejected_after_preparation(self):
        identity = copy.deepcopy(self.identity)
        identity['manifest']['index.html'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            local.validate_prepared(self.prepared, identity)

    def test_changed_source_rejected_after_preparation(self):
        identity = copy.deepcopy(self.identity)
        identity['files']['nav']['after'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'Candidate changed'):
            local.validate_prepared(self.prepared, identity)

    def test_same_candidate_can_use_existing_preparation(self):
        local.validate_prepared(self.prepared, self.identity)


class BuildIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.baseline, self.candidate = 'a' * 40, 'd' * 40
        self.source = b'new-navigation'
        self.policy = {'source_sha256': release.digest(self.source), 'favorite_access': {'guide': [{}, {}, {}]}}
        self.dist = self.root / 'frontend/dist'
        self.dist.mkdir(parents=True)
        (self.dist / 'index.html').write_text('html')
        self.write_build(self.candidate, self.policy['favorite_access'])
        self.dirty = False

    def write_build(self, revision, policy):
        (self.dist / 'nav-manifest.json').write_text(json.dumps({'git_sha': revision, 'favorite_access': policy}))

    def fake_git(self, source, *args):
        if args[0] == 'rev-parse':
            return self.candidate.encode()
        if args[0] == 'status':
            return b'?? unknown-source.js' if self.dirty else b''
        if args[0] == 'diff':
            return '\n'.join(release.PATHS).encode()
        if args[0] == 'show':
            revision, name = args[1].split(':', 1)
            if revision == self.baseline:
                return b'old'
            return self.source if name == release.PATHS[0] else json.dumps(self.policy).encode()
        raise AssertionError(args)

    def identity(self):
        with patch.object(local, 'git', side_effect=self.fake_git), patch.object(local.subprocess, 'run'):
            return local.candidate_identity(self.root, self.baseline)

    def test_rejects_old_build_even_when_policy_matches(self):
        self.write_build(self.baseline, self.policy['favorite_access'])
        with self.assertRaisesRegex(ValueError, 'rebuild first'):
            self.identity()

    def test_rejects_different_build_policy(self):
        self.write_build(self.candidate, {'stale-guide': []})
        with self.assertRaisesRegex(ValueError, 'rebuild first'):
            self.identity()

    def test_rejects_dirty_local_candidate(self):
        self.dirty = True
        with self.assertRaisesRegex(ValueError, 'clean candidate'):
            self.identity()

    def test_valid_build_is_bound_to_commit_and_all_files(self):
        value = self.identity()
        self.assertEqual(value['candidate'], self.candidate)
        self.assertEqual(set(value['manifest']), {'index.html', 'nav-manifest.json'})


if __name__ == '__main__':
    unittest.main()
