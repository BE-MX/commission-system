import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "git_hooks.py"
SPEC = importlib.util.spec_from_file_location("ark_git_hooks", SCRIPT)
HOOKS = importlib.util.module_from_spec(SPEC)
sys.modules["ark_git_hooks"] = HOOKS
SPEC.loader.exec_module(HOOKS)

ZERO = "0" * 40


def run(repo, *args, env=None, stdin=None):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, env=env, input=stdin,
    )


def migration(rev, down):
    down_text = "None" if down is None else repr(down)
    return f"revision: str = {rev!r}\ndown_revision = {down_text}\n"


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for args in (
            ("init", "-q", "-b", "main"),
            ("config", "user.email", "t@example.com"),
            ("config", "user.name", "t"),
            ("config", "core.autocrlf", "false"),
        ):
            run(self.repo, *args)
        (self.repo / "scripts").mkdir()
        shutil.copy(SCRIPT, self.repo / "scripts" / "git_hooks.py")
        self.write("README.md", "x\n")
        self.write(f"{HOOKS.MIGRATION_DIR}/001.py", migration("001", None))
        run(self.repo, "add", ".")
        run(self.repo, "commit", "-q", "-m", "init")
        self.env = patch_env({})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, text, repo=None):
        path = (repo or self.repo) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def stage(self, rel, text, repo=None):
        self.write(rel, text, repo)
        run(repo or self.repo, "add", rel)

    def pre_commit(self, repo=None, **env):
        with patch_env(env):
            return HOOKS.pre_commit(repo or self.repo)


def patch_env(values):
    clean = {k: v for k, v in os.environ.items()
             if k not in ("ARK_AGENT", "ARK_PUSH_APPROVED", "ARK_PUSH_FORCE_APPROVED", "ARK_HOOKS_STRICT")}
    clean.update(values)
    return mock.patch.dict(os.environ, clean, clear=True)


class PreCommitTests(RepoCase):
    def test_human_commit_on_main_in_main_worktree_passes(self):
        self.stage("a.txt", "ok\n")
        self.assertEqual(self.pre_commit(), 0)

    def test_non_owner_agent_blocked_on_main(self):
        self.stage("a.txt", "ok\n")
        self.assertEqual(self.pre_commit(ARK_AGENT="accio"), 1)
        self.assertEqual(self.pre_commit(ARK_AGENT="claude"), 0)

    def test_agent_must_use_own_prefix(self):
        run(self.repo, "checkout", "-q", "-b", "codex/x")
        self.stage("a.txt", "ok\n")
        self.assertEqual(self.pre_commit(ARK_AGENT="accio"), 1)
        self.assertEqual(self.pre_commit(ARK_AGENT="codex"), 0)

    def test_unknown_agent_blocked(self):
        run(self.repo, "checkout", "-q", "-b", "accio/x")
        self.stage("a.txt", "ok\n")
        self.assertEqual(self.pre_commit(ARK_AGENT="robot"), 1)

    def test_main_blocked_in_linked_worktree(self):
        run(self.repo, "checkout", "-q", "-b", "accio/side")
        linked = self.root / "linked"
        self.assertEqual(run(self.repo, "worktree", "add", "-q", str(linked), "main").returncode, 0)
        self.stage("a.txt", "ok\n", repo=linked)
        self.assertEqual(self.pre_commit(repo=linked), 1)

    def test_whitespace_errors_blocked(self):
        self.stage("a.txt", "trailing \n")
        self.assertEqual(self.pre_commit(), 1)

    def test_secret_file_blocked_but_example_allowed(self):
        self.stage("backend/.env", "K=v\n")
        self.assertEqual(self.pre_commit(), 1)
        run(self.repo, "rm", "-q", "--cached", "backend/.env")
        self.stage("backend/.env.example", "K=\n")
        self.assertEqual(self.pre_commit(), 0)

    def test_private_key_content_blocked(self):
        self.stage("conf/k.txt", "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n")
        self.assertEqual(self.pre_commit(), 1)

    def test_second_alembic_head_blocked(self):
        self.stage(f"{HOOKS.MIGRATION_DIR}/002.py", migration("002", "001"))
        self.assertEqual(self.pre_commit(), 0)
        self.stage(f"{HOOKS.MIGRATION_DIR}/003.py", migration("003", "001"))
        self.assertEqual(self.pre_commit(), 1)

    def test_merge_migration_with_tuple_down_revision_passes(self):
        self.stage(f"{HOOKS.MIGRATION_DIR}/002.py", migration("002", "001"))
        self.stage(f"{HOOKS.MIGRATION_DIR}/003.py", migration("003", "001"))
        self.stage(f"{HOOKS.MIGRATION_DIR}/004.py", "revision = '004'\ndown_revision = ('002', '003')\n")
        self.assertEqual(self.pre_commit(), 0)

    def test_duplicate_revision_blocked(self):
        self.stage(f"{HOOKS.MIGRATION_DIR}/001_copy.py", migration("001", None))
        self.assertEqual(self.pre_commit(), 1)


class PrePushTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.base = run(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.stage("b.txt", "y\n")
        run(self.repo, "commit", "-q", "-m", "next")
        self.tip = run(self.repo, "rev-parse", "HEAD").stdout.strip()

    def push(self, ref, local, remote, **env):
        with patch_env(env):
            return HOOKS.check_push(self.repo, HOOKS.agent_name(), [("refs/heads/x", local, ref, remote)])

    def test_human_fast_forward_allowed(self):
        self.assertEqual(self.push("refs/heads/main", self.tip, self.base), [])

    def test_agent_push_requires_approval(self):
        self.assertTrue(self.push("refs/heads/accio/x", self.tip, ZERO, ARK_AGENT="accio"))
        self.assertEqual(
            self.push("refs/heads/accio/x", self.tip, ZERO, ARK_AGENT="accio", ARK_PUSH_APPROVED="1"), [])

    def test_agent_cannot_push_other_prefix(self):
        errors = self.push("refs/heads/codex/x", self.tip, ZERO, ARK_AGENT="accio", ARK_PUSH_APPROVED="1")
        self.assertTrue(any("codex" in e for e in errors))

    def test_main_rewrite_and_delete_need_force_approval(self):
        self.assertTrue(self.push("refs/heads/main", self.base, self.tip))
        self.assertTrue(self.push("refs/heads/main", ZERO, self.tip))
        self.assertEqual(self.push("refs/heads/main", self.base, self.tip, ARK_PUSH_FORCE_APPROVED="1"), [])

    def test_human_may_rewrite_feature_branch(self):
        self.assertEqual(self.push("refs/heads/feature", self.base, self.tip), [])

    def test_parse_push_lines(self):
        line = f"refs/heads/a {self.tip} refs/heads/a {ZERO}\n"
        self.assertEqual(HOOKS.parse_push_lines(line), [("refs/heads/a", self.tip, "refs/heads/a", ZERO)])


class ShimTests(RepoCase):
    def test_real_git_commit_runs_hook(self):
        hooks_src = SCRIPT.parents[1] / ".githooks"
        shutil.copytree(hooks_src, self.repo / ".githooks")
        run(self.repo, "config", "core.hooksPath", ".githooks")
        self.write("bad.txt", "trailing \n")
        run(self.repo, "add", "bad.txt")
        blocked = run(self.repo, "commit", "-q", "-m", "bad", env=os.environ.copy())
        self.assertNotEqual(blocked.returncode, 0, blocked.stderr)
        self.assertIn("ark-hooks", blocked.stderr)
        self.write("bad.txt", "clean\n")
        run(self.repo, "add", "bad.txt")
        passed = run(self.repo, "commit", "-q", "-m", "good", env=os.environ.copy())
        self.assertEqual(passed.returncode, 0, passed.stderr)


if __name__ == "__main__":
    unittest.main()
