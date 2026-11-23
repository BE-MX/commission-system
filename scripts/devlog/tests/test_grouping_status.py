# scripts/devlog/tests/test_grouping_status.py
import os
import time
import pytest
import subprocess
from datetime import datetime

from conftest import commit, sh
from grouping import KeyMap, build_groups, is_process_branch
from status import PatchCache, Release, compute_items
from gitdata import BJ

SINCE = "2026-10-01"
NOW = datetime(2026, 11, 23, 15, 0)


def collect(repo, tmp_path, releases=(), origin="main", now=NOW):
    cache = PatchCache(tmp_path / "patch-ids.json")
    keymap = KeyMap(tmp_path / "keymap.json")
    groups = build_groups(repo, SINCE, keymap=keymap, cache=cache, now=now)
    items = compute_items(repo, groups, SINCE, releases=list(releases), origin_ref=origin, now=now, cache=cache, keymap=keymap)
    keymap.save()
    cache.save()
    return items


def by_key(items):
    return {i["key"]: i for i in items}


def test_process_branch_patterns():
    for name in ["main", "origin/main", "codex/global-release-96e42ec3", "codex/release-followup-strategy-20261123",
                 "codex/followup-strategy-main-integration", "codex/x-pilot-release", "codex/outbound-proof-20261111-release",
                 "integration-agent-cloud-20260926", "codex/x-integration-20261019"]:
        assert is_process_branch(name), name
    for name in ["codex/cross-border-review", "accio/private-sea-integration-ce44d944", "codex/release-notes-page"]:
        assert not is_process_branch(name), name


def test_merged_branch_and_cherry_pick_release_counts_as_released(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/strategy")
    fix = commit(repo, "backend/app/domestic_followup/s.py", "retry = 1\n", "Recover truncated strategies", "2026-11-23T11:02:00+08:00")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/strategy", "-m", "Merge branch 'codex/strategy'")
    sh(repo, "checkout", "-b", "codex/release-strategy-20261123", "HEAD~1")   # 发布分支从旧基点 cherry-pick
    sh(repo, "cherry-pick", fix)
    release_rev = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    items = by_key(collect(repo, tmp_path, [Release(release_rev, datetime(2026, 11, 23, 14, 2), "office-and-cloud")]))
    assert list(items) == ["branch:codex/strategy"]
    item = items["branch:codex/strategy"]
    assert item["status"] == "released" and item["released_revision"] == release_rev
    assert item["status_at"] == "2026-11-23T14:02:00" and item["unmerged_hotfix"] is False
    assert (item["agent"], item["module"], item["type"]) == ("codex", "domestic_followup", "data")


def test_partial_release_does_not_count(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/a")
    commit(repo, "backend/app/stock/a.py", "a = 1\n", "Add a")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/a", "-m", "Merge branch 'codex/a'")
    head = sh(repo, "rev-parse", "HEAD")
    item = collect(repo, tmp_path, [Release(head, datetime(2026, 11, 23, 14), "cloud-only")])[0]
    assert item["status"] == "pending_release"


def test_hotfix_only_on_release_branch_is_released_and_flagged(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/release-hotfix-20261123")
    commit(repo, "backend/app/invoice/h.py", "h = 1\n", "Fix invoice crash")
    release_rev = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    items = by_key(collect(repo, tmp_path, [Release(release_rev, datetime(2026, 11, 23, 16), "office-and-cloud")]))
    hotfix = items["batch:hotfix-" + release_rev[:12]]
    assert hotfix["status"] == "released" and hotfix["unmerged_hotfix"] is True and hotfix["type"] == "bug"


def test_unnamed_merge_of_deleted_branch_is_one_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/editor")
    commit(repo, "backend/app/invoice/e1.py", "a\n", "Add editor lock")
    commit(repo, "backend/app/invoice/e2.py", "b\n", "Fix editor save")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/editor", "-m", "Merge invoice editor fix")
    sh(repo, "branch", "-D", "codex/editor")
    items = collect(repo, tmp_path)
    assert len(items) == 1 and items[0]["key"].startswith("merge:")
    assert items[0]["title"] == "Merge invoice editor fix" and len([e for e in items[0]["evidences"] if e["kind"] == "commit"]) == 2


def test_unnamed_merge_not_attributed_to_branch_cut_later(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/gone")
    commit(repo, "backend/app/invoice/g.py", "g\n", "Add gone")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/gone", "-m", "Merge gone work")
    sh(repo, "branch", "-D", "codex/gone")
    sh(repo, "branch", "codex/later")   # 合并后才切出的分支，name-rev 会误认它
    items = collect(repo, tmp_path)
    assert [i["key"].split(":")[0] for i in items] == ["merge"]


def test_free_text_sync_merge_is_not_a_feature(repo, tmp_path):
    sh(repo, "checkout", "-b", "elsewhere2")
    commit(repo, "backend/app/stock/q.py", "q\n", "Speed up stock query", "2026-11-21T10:00:00+08:00")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "elsewhere2", "-m", "Merge origin/main into main")
    sh(repo, "branch", "-D", "elsewhere2")
    assert [i["key"] for i in collect(repo, tmp_path)] == ["batch:20261121-stock-unknown"]


def test_same_revision_twice_in_ledger_yields_one_hotfix_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/release-hotfix-20261124")
    commit(repo, "backend/app/invoice/h2.py", "h\n", "Fix invoice crash again")
    rev = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    items = collect(repo, tmp_path, [Release(rev, datetime(2026, 11, 24, 9), "office-and-cloud"),
                                     Release(rev, datetime(2026, 11, 24, 10), "office-and-cloud")])
    keys = [i["key"] for i in items]
    assert keys.count("batch:hotfix-" + rev[:12]) == 1
    assert items[0]["status_at"] == "2026-11-24T09:00:00"


def test_sync_merge_of_origin_main_creates_no_fake_branch_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "elsewhere")
    commit(repo, "backend/app/stock/r.py", "r\n", "Speed up stock list", "2026-11-20T10:00:00+08:00")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "elsewhere", "-m", "Merge remote-tracking branch 'origin/main'")
    sh(repo, "branch", "-D", "elsewhere")
    keys = list(by_key(collect(repo, tmp_path)))
    assert keys == ["batch:20261120-stock-unknown"]


def test_same_branch_merged_twice_is_one_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/twice")
    commit(repo, "backend/app/stock/t1.py", "1\n", "Add t1")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/twice", "-m", "Merge branch 'codex/twice'")
    sh(repo, "checkout", "codex/twice")
    commit(repo, "backend/app/stock/t2.py", "2\n", "Fix t2")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/twice", "-m", "Merge branch 'codex/twice'")
    items = collect(repo, tmp_path)
    assert [i["key"] for i in items] == ["branch:codex/twice"]
    assert len([e for e in items[0]["evidences"] if e["kind"] == "commit"]) == 2


def test_direct_commits_group_by_day_module_agent(repo, tmp_path):
    commit(repo, "backend/app/stock/a.py", "a\n", "Speed up stock a", "2026-11-20T10:00:00+08:00")
    commit(repo, "backend/app/stock/b.py", "b\n", "Speed up stock b", "2026-11-20T11:00:00+08:00")
    commit(repo, "backend/app/invoice/c.py", "c\n", "Fix invoice c", "2026-11-20T12:00:00+08:00")
    items = by_key(collect(repo, tmp_path))
    assert set(items) == {"batch:20261120-stock-unknown", "batch:20261120-invoice-unknown"}
    assert items["batch:20261120-stock-unknown"]["title"].endswith("等2项")


def test_keymap_keeps_key_after_fast_forward_and_branch_delete(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/ff")
    commit(repo, "backend/app/stock/f.py", "f\n", "Add ff")
    sh(repo, "checkout", "main")
    assert collect(repo, tmp_path)[0]["key"] == "branch:codex/ff"
    sh(repo, "merge", "--ff-only", "codex/ff")
    sh(repo, "branch", "-D", "codex/ff")
    items = collect(repo, tmp_path)
    assert [(i["key"], i["status"]) for i in items] == [("branch:codex/ff", "pending_release")]


def test_unmerged_branch_states_and_preconditions(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/cross-border")
    commit(repo, "backend/alembic/versions/277_cross_border_review.py", "revision = '277'\n", "Add cross border review")
    commit(repo, "backend/app/core/config.py", "class S:\n    CROSS_BORDER_DXP_ID: str = ''\n", "Add DXP setting")
    commit(repo, "backend/app/auth/service.py", 'P = [\n    ("cross_border:read", "cross_border", "read", "x"),\n]\n', "Add permission")
    sh(repo, "checkout", "main")
    item = collect(repo, tmp_path)[0]
    assert item["key"] == "branch:codex/cross-border" and item["status"] == "pending_merge"
    assert item["preconditions"] == {"migrations": ["277_cross_border_review"], "config_keys": ["CROSS_BORDER_DXP_ID"],
                                     "permissions": ["cross_border:read"]}


def test_local_main_ahead_of_origin_is_pending_push(repo, tmp_path):
    sh(repo, "branch", "origin-snapshot")
    commit(repo, "backend/app/stock/x.py", "x\n", "Speed up stock list", "2026-11-22T10:00:00+08:00")
    item = collect(repo, tmp_path, origin="origin-snapshot")[0]
    assert item["status"] == "pending_push" and item["type"] == "improve"


def test_dev_worktree_only_with_recent_dirt_and_main_dirt_ignored(repo, tmp_path):
    (repo / "scratch.txt").write_text("main dirt", encoding="utf-8")
    sh(repo, "branch", "claude/devlog")
    sh(repo, "branch", "codex/abandoned")
    fresh, old = tmp_path / "fresh", tmp_path / "old"
    sh(repo, "worktree", "add", str(fresh), "claude/devlog")
    sh(repo, "worktree", "add", str(old), "codex/abandoned")
    (fresh / "draft.md").write_text("x", encoding="utf-8")
    stale_file = old / "left.md"
    stale_file.write_text("x", encoding="utf-8")
    past = time.time() - 30 * 86400
    os.utime(stale_file, (past, past))
    # 改动新鲜度按真实当前时间判断（文件 mtime 是真实时间），不用固定的 NOW
    items = collect(repo, tmp_path, now=datetime.fromtimestamp(time.time(), BJ).replace(tzinfo=None, microsecond=0))
    assert [(i["key"], i["status"]) for i in items] == [("branch:claude/devlog", "dev")]


def test_stale_flag_after_14_days(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/old")
    commit(repo, "backend/app/stock/o.py", "o\n", "Add old idea", "2026-11-01T10:00:00+08:00")
    sh(repo, "checkout", "main")
    item = collect(repo, tmp_path)[0]
    assert item["status"] == "pending_merge" and item["stale"] is True


def test_fingerprint_stable_and_patch_cache_reused(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/a")
    commit(repo, "backend/app/stock/a.py", "a\n", "Add a")
    sh(repo, "checkout", "main")
    first = collect(repo, tmp_path)[0]
    assert (tmp_path / "patch-ids.json").is_file()
    assert collect(repo, tmp_path)[0]["fingerprint"] == first["fingerprint"]


def test_keymap_preserves_multiple_commits_ownership_after_branch_deletion(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/one")
    commit(repo, "backend/app/stock/a.py", "a\n", "Add first")
    sh(repo, "checkout", "main")
    sh(repo, "checkout", "-b", "codex/two")
    commit(repo, "backend/app/stock/b.py", "b\n", "Add second")
    sh(repo, "checkout", "main")
    before = by_key(collect(repo, tmp_path))
    sh(repo, "merge", "--ff-only", "codex/one")
    sh(repo, "cherry-pick", "codex/two")
    sh(repo, "branch", "-D", "codex/one")
    sh(repo, "branch", "-D", "codex/two")
    after = by_key(collect(repo, tmp_path))
    assert "branch:codex/one" in after
    # Original commits retain their keys even when first-parent batches now mix them.
    assert before["branch:codex/one"]["evidences"][1]["ref"] in [e["ref"] for e in after["branch:codex/one"]["evidences"]]


def test_release_main_shared_patch_covers_feature_commit(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/original")
    original = commit(repo, "backend/app/stock/e.py", "x\n", "Add equivalent")
    sh(repo, "checkout", "main")
    sh(repo, "cherry-pick", original)
    revision = sh(repo, "rev-parse", "HEAD")
    items = collect(repo, tmp_path, [Release(revision, NOW, "office-and-cloud")])
    assert len(items) == 1 and items[0]["status"] == "released"


def test_hotfix_cherry_pick_of_open_feature_is_one_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/open-feature")
    original = commit(repo, "backend/app/stock/e.py", "x\n", "Fix urgent issue")
    sh(repo, "checkout", "main")
    sh(repo, "checkout", "-b", "codex/release-20261123")
    sh(repo, "cherry-pick", original)
    revision = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    items = collect(repo, tmp_path, [Release(revision, NOW, "office-and-cloud")])
    assert len(items) == 1 and items[0]["key"] == "branch:codex/open-feature"
    assert items[0]["status"] == "released" and items[0]["unmerged_hotfix"]


@pytest.mark.parametrize("integration", ["merge", "cherry-pick"])
def test_hotfix_keeps_item_identity_across_runs_after_main_integration(repo, tmp_path, integration):
    sh(repo, "checkout", "-b", "codex/release-hotfix-20261123")
    original = commit(repo, "backend/app/stock/h.py", "urgent\n", "Fix urgent problem")
    sh(repo, "checkout", "main")
    ledger = [Release(original, NOW, "office-and-cloud")]
    first = collect(repo, tmp_path, ledger)
    assert len(first) == 1 and first[0]["unmerged_hotfix"]
    original_key = first[0]["key"]
    if integration == "merge":
        sh(repo, "merge", "--ff-only", original)
        assert sh(repo, "rev-parse", "HEAD") == original
    else:
        commit(repo, "unrelated.txt", "unrelated\n", "Update notes")
        sh(repo, "cherry-pick", original)
        assert sh(repo, "rev-parse", "HEAD") != original
    second = collect(repo, tmp_path, ledger)
    released = [item for item in second if item["status"] == "released"]
    assert len(released) == 1 and released[0]["key"] == original_key
    assert not released[0]["unmerged_hotfix"]
    assert released[0]["status_at"] == first[0]["status_at"]


def test_partially_integrated_hotfix_remains_one_item_across_runs(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/release-hotfix-20261123")
    one = commit(repo, "backend/app/stock/h1.py", "first\n", "Fix first")
    two = commit(repo, "backend/app/stock/h2.py", "second\n", "Fix second")
    sh(repo, "checkout", "main")
    ledger = [Release(two, NOW, "office-and-cloud")]
    first = collect(repo, tmp_path, ledger)
    sh(repo, "cherry-pick", one)
    second = collect(repo, tmp_path, ledger)
    assert len(second) == 1 and second[0]["key"] == first[0]["key"]
    assert second[0]["status"] == "released" and second[0]["unmerged_hotfix"]


def test_merge_added_migration_is_not_released_with_only_second_parent(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/merge-extra")
    feature = commit(repo, "backend/app/stock/a.py", "feature\n", "Add feature")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "--no-commit", "codex/merge-extra")
    merged = commit(repo, "backend/alembic/versions/999_merge_extra.py", "revision = '999'\n",
                    "Merge branch 'codex/merge-extra'")
    items = collect(repo, tmp_path, [Release(feature, NOW, "office-and-cloud")])
    item = by_key(items)["branch:codex/merge-extra"]
    assert item["status"] == "pending_release"
    assert item["preconditions"]["migrations"] == ["999_merge_extra"]
    assert merged in [e["ref"] for e in item["evidences"]]
    after = by_key(collect(repo, tmp_path, [Release(merged, NOW, "office-and-cloud")]))
    assert after[item["key"]]["status"] == "released"


def test_conflict_resolution_is_not_released_with_only_second_parent(repo, tmp_path):
    commit(repo, "backend/app/stock/conflict.py", "base\n", "Initial file", "2026-09-01T10:00:00+08:00")
    sh(repo, "checkout", "-b", "codex/conflict")
    feature = commit(repo, "backend/app/stock/conflict.py", "feature\n", "Add feature")
    sh(repo, "checkout", "main")
    commit(repo, "backend/app/stock/conflict.py", "main\n", "Fix main side")
    with pytest.raises(subprocess.CalledProcessError):
        sh(repo, "merge", "--no-ff", "codex/conflict")
    merged = commit(repo, "backend/app/stock/conflict.py", "independent resolution\n", "Merge branch 'codex/conflict'")
    items = by_key(collect(repo, tmp_path, [Release(feature, NOW, "office-and-cloud")]))
    assert items["branch:codex/conflict"]["status"] == "pending_release"
    assert merged in [e["ref"] for e in items["branch:codex/conflict"]["evidences"]]


@pytest.mark.parametrize("outer_merge", [False, True])
@pytest.mark.parametrize("kind", ["extra", "conflict"])
def test_nested_semantic_merge_is_retained_on_feature_and_main(repo, tmp_path, outer_merge, kind):
    base = commit(repo, "backend/app/stock/shared.py", "base\n", "Initial file", "2026-09-01T10:00:00+08:00")
    sh(repo, "checkout", "-b", "codex/nested")
    left = commit(repo, "backend/app/stock/shared.py", "left\n", "Add left")
    sh(repo, "checkout", "-b", "codex/side", base)
    right_path = "backend/app/stock/shared.py" if kind == "conflict" else "backend/app/stock/right.py"
    right = commit(repo, right_path, "right\n", "Add right")
    sh(repo, "checkout", "codex/nested")
    if kind == "conflict":
        with pytest.raises(subprocess.CalledProcessError):
            sh(repo, "merge", "--no-ff", "codex/side")
        inner = commit(repo, "backend/app/stock/shared.py", "resolved independently\n", "Merge side into feature")
    else:
        sh(repo, "merge", "--no-ff", "--no-commit", "codex/side")
        migration = repo / "backend/alembic/versions/998_nested.py"
        migration.parent.mkdir(parents=True, exist_ok=True)
        migration.write_text("revision = '998'\n", encoding="utf-8")
        sh(repo, "add", "backend/alembic/versions/998_nested.py")
        inner = commit(repo, "backend/app/core/config.py", "class S:\n    NESTED_ONLY: str = ''\n", "Merge side into feature")
    sh(repo, "branch", "-D", "codex/side")
    # Both original parents are reachable in this candidate, but the independent
    # feature merge resolution is absent. An ancestry-only parent check is unsafe.
    sh(repo, "checkout", "-b", "codex/release-nested-20261123", left)
    sh(repo, "merge", "--no-ff", "-s", "ours", right, "-m", "Candidate without feature merge resolution")
    revision = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    if outer_merge:
        sh(repo, "merge", "--no-ff", "codex/nested", "-m", "Merge branch 'codex/nested'")
    items = by_key(collect(repo, tmp_path, [Release(revision, NOW, "office-and-cloud")]))
    item = items["branch:codex/nested"]
    assert item["status"] == ("pending_release" if outer_merge else "pending_merge")
    refs = [e["ref"] for e in item["evidences"]]
    assert inner in refs and left in refs and right in refs
    if outer_merge:
        assert sh(repo, "rev-parse", "HEAD") not in refs  # Ordinary outer merge is filtered.
    if kind == "extra":
        assert "998_nested" in item["preconditions"]["migrations"]
        assert "NESTED_ONLY" in item["preconditions"]["config_keys"]


def test_octopus_merge_includes_every_parent_and_requires_merge_coverage(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/first")
    first = commit(repo, "backend/app/stock/first.py", "first\n", "Add first")
    sh(repo, "checkout", "main")
    sh(repo, "checkout", "-b", "codex/second")
    second = commit(repo, "backend/app/stock/second.py", "second\n", "Add second")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "--no-commit", "codex/first", "codex/second")
    merged = commit(repo, "backend/alembic/versions/997_octopus.py", "revision = '997'\n", "Merge both features")
    assert len(sh(repo, "rev-list", "--parents", "-n", "1", merged).split()) == 4
    item = by_key(collect(repo, tmp_path, [Release(first, NOW, "office-and-cloud")]))["merge:" + merged]
    assert item["status"] == "pending_release"
    refs = [e["ref"] for e in item["evidences"]]
    assert first in refs and second in refs and merged in refs
    assert "997_octopus" in item["preconditions"]["migrations"]
    after = by_key(collect(repo, tmp_path, [Release(merged, NOW, "office-and-cloud")]))
    assert after[item["key"]]["status"] == "released"


def test_nested_plain_merge_still_allows_parent_patch_equivalent_release(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/nested-plain")
    left = commit(repo, "backend/app/stock/left.py", "left\n", "Add left")
    sh(repo, "checkout", "-b", "codex/plain-side", "main")
    right = commit(repo, "backend/app/stock/right.py", "right\n", "Add right")
    sh(repo, "checkout", "codex/nested-plain")
    sh(repo, "merge", "--no-ff", "codex/plain-side", "-m", "Merge side into feature")
    inner = sh(repo, "rev-parse", "HEAD")
    sh(repo, "branch", "-D", "codex/plain-side")
    sh(repo, "checkout", "-b", "codex/release-plain-20261123", "main")
    sh(repo, "cherry-pick", left)
    sh(repo, "cherry-pick", right)
    released = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    items = collect(repo, tmp_path, [Release(released, NOW, "office-and-cloud")])
    assert len(items) == 1 and items[0]["status"] == "released"
    assert inner not in [e["ref"] for e in items[0]["evidences"]]
