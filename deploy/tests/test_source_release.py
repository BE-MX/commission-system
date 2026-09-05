"""Cross-platform source and coordinator preflight tests; no external services."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish
import schema_release
import source_release


class SourceReleaseTests(unittest.TestCase):
    def test_preparation_never_changes_live_and_next_release_keeps_tracking(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(path, *args):
                return subprocess.check_output(["git", *args], cwd=path, text=True, stderr=subprocess.DEVNULL).strip()
            bare = root / "remote.git"
            git(root, "init", "--bare", str(bare))
            author = root / "author"
            git(root, "clone", str(bare), str(author))
            git(author, "checkout", "-b", "main")
            git(author, "config", "user.name", "Deployment Test")
            git(author, "config", "user.email", "deployment-test@example.invalid")
            (author / "code.txt").write_text("old")
            (author / ".gitignore").write_text(".deploy_state/\n")
            git(author, "add", ".")
            git(author, "commit", "-m", "Initial fixture")
            git(author, "push", "-u", "origin", "main")
            live = root / "office"
            git(root, "clone", "-b", "main", str(bare), str(live))
            for version in ("second", "third"):
                old = (live / "code.txt").read_text()
                (author / "code.txt").write_text(version)
                git(author, "commit", "-am", version)
                git(author, "push")
                source, revision, previous = source_release.prepare(live, live / ".deploy_state", True)
                self.assertEqual((live / "code.txt").read_text(), old)
                self.assertEqual((source / "code.txt").read_text(), version)
                self.assertEqual(git(live, "rev-parse", "HEAD"), previous)
                git(live, "merge", "--ff-only", revision)
                self.assertEqual(git(live, "symbolic-ref", "--short", "HEAD"), "main")
                self.assertEqual(git(live, "rev-parse", "--abbrev-ref", "@{upstream}"), "origin/main")

    def test_unverified_database_writers_block_before_any_stop(self):
        with patch.object(schema_release, "control") as control:
            with self.assertRaisesRegex(RuntimeError, "no services stopped"):
                schema_release.migrate({"pending": ["138_test"]}, {"migration_writers_verified": False})
        control.assert_not_called()

    def test_database_at_target_is_noop(self):
        with patch.object(schema_release, "run") as run:
            self.assertEqual(schema_release.migrate({"pending": []}, {}), [])
        run.assert_not_called()

    def test_build_digest_ignores_dependency_and_output_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src = root / "frontend"
            src.mkdir()
            (src / "source.js").write_text("source")
            deps = src / "node_modules"
            deps.mkdir()
            (deps / "large.js").write_text("ignored")
            with patch.object(publish, "ROOT", root):
                first = publish.input_digest([src])
                (deps / "large.js").write_text("changed ignored")
                self.assertEqual(publish.input_digest([src]), first)
                (src / "source.js").write_text("changed source")
                self.assertNotEqual(publish.input_digest([src]), first)


if __name__ == "__main__":
    unittest.main()
