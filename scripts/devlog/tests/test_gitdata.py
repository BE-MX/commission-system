# scripts/devlog/tests/test_gitdata.py
from datetime import datetime

from conftest import commit, sh
import gitdata


def test_to_bj_naive_converts_offset_across_midnight():
    assert gitdata.to_bj_naive("2026-11-22T16:30:00+00:00") == datetime(2026, 11, 23, 0, 30)


def test_cherry_picked_commit_has_same_patch_id(repo):
    sh(repo, "checkout", "-b", "codex/fix")
    original = commit(repo, "backend/app/invoice/a.py", "x = 1\n", "Fix invoice rounding")
    sh(repo, "checkout", "main")
    sh(repo, "cherry-pick", original)
    picked = sh(repo, "rev-parse", "HEAD")
    ids = gitdata.patch_ids(repo, [original, picked])
    assert original != picked and ids[original] == ids[picked]


def test_first_parent_history_reports_merges_with_branch_name(repo):
    sh(repo, "checkout", "-b", "codex/feature")
    commit(repo, "backend/app/stock/s.py", "s = 1\n", "Add stock thing")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/feature", "-m", "Merge branch 'codex/feature'")
    history = gitdata.first_parent(repo, "main", "2026-10-01")
    merge = history[0]
    assert merge.is_merge and merge.subject == "Merge branch 'codex/feature'"
    inner = gitdata.range_commits(repo, merge.parents[0], merge.parents[1])
    assert [c.subject for c in inner] == ["Add stock thing"]
    assert inner[0].files == [("A", "backend/app/stock/s.py")]


def test_branches_and_dirty_worktrees(repo, tmp_path):
    sh(repo, "branch", "claude/wip")
    wt = tmp_path / "wt"
    sh(repo, "worktree", "add", str(wt), "claude/wip")
    (wt / "new.txt").write_text("draft", encoding="utf-8")
    branches = {b.name for b in gitdata.branches(repo)}
    assert {"main", "claude/wip"} <= branches
    trees = {w.branch: w for w in gitdata.worktrees(repo)}
    assert trees["claude/wip"].dirty_files == 1 and trees["claude/wip"].dirty_mtime is not None
    assert trees["main"].dirty_files == 0 and trees["main"].dirty_mtime is None


def test_reach_and_name_rev(repo):
    sh(repo, "checkout", "-b", "codex/named")
    tip = commit(repo, "a.txt", "a\n", "Add a")
    sh(repo, "checkout", "main")
    assert tip in gitdata.reach(repo, "codex/named") and tip not in gitdata.reach(repo, "main")
    assert gitdata.name_rev(repo, tip) == "codex/named"
    sh(repo, "merge", "--no-ff", "codex/named", "-m", "Merge something")
    sh(repo, "branch", "-D", "codex/named")
    assert gitdata.name_rev(repo, tip) is None   # 分支删除后不能被命名成 main~N
    merge = sh(repo, "rev-parse", "HEAD")
    sh(repo, "branch", "codex/later")            # 合并之后才从 main 切出的分支
    assert gitdata.is_ancestor(repo, merge, "codex/later") is True


def test_status_does_not_escape_chinese_paths(repo, tmp_path):
    sh(repo, "branch", "claude/zh")
    wt = tmp_path / "wt-zh"
    sh(repo, "worktree", "add", str(wt), "claude/zh")
    (wt / "发票说明.md").write_text("x", encoding="utf-8")
    tree = {w.branch: w for w in gitdata.worktrees(repo)}["claude/zh"]
    assert tree.dirty_files == 1 and tree.dirty_mtime is not None


def test_object_exists(repo):
    head = sh(repo, "rev-parse", "HEAD")
    assert gitdata.object_exists(repo, head) is True
    assert gitdata.object_exists(repo, "0" * 40) is False
