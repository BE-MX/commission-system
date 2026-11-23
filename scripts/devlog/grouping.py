# scripts/devlog/grouping.py
"""痕迹 → 事项（P0 用 Git 能确定的最好近似；精确归并靠 P1 会话与人工修正）。

1. main first-parent 上的合并：识别出功能分支名 → branch:<名>（同名多次合并并成一件）；
   名字是 main/master（含 origin/main 同步合并）→ 带进来的提交当作直接提交；
   识别不了或是过程分支 → merge:<sha>，整个合并算一件事，标题用合并信息。
2. 直接提交 → batch:<北京日期>-<模块>-<代理>。
3. 未合入 main 的功能分支（tip 不早于 since）→ main..branch 的提交；
   直接提交若与某未合并分支提交内容等价（cherry-pick 进 main），归该分支。
4. 非 main 的 worktree 有 14 天内的未提交改动 → 证据挂到该分支事项；分支无提交则成为「开发中」事项。
5. 同一提交第一次归到哪件事就永久沿用（KeyMap），防止分支删除 / fast-forward 后键漂移。
"""
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import gitdata
from classify import agent_of, module_of

PROCESS = re.compile(
    r"^(main|master)$|^origin/|(^|/)global-release-|(^|/)release-.*\d{6,}|-release(-\d+)?$"
    r"|main-integration$|(^|/)integration-.*\d{8}|-integration-\d{8}"
)
MERGE_NAME = re.compile(r"^Merge (?:remote-tracking )?branch '([^']+)'")
# 自由文本的同步合并，如「Merge origin/main into main」「Merge main into codex/x」
SYNC_MERGE = re.compile(r"^Merge (?:remote-tracking branch |branch )?'?(?:origin/)?(?:main|master)'?(?:\s+into\b|$)")
DIRTY_FRESH_DAYS = 14


def is_process_branch(name: str) -> bool:
    return bool(PROCESS.search(name))


def _normalize(name: str) -> str:
    return name.removeprefix("origin/")


class KeyMap:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}

    def resolve_commit(self, commit, proposed: str, pid: str | None) -> str:
        """Persist patch ownership too, so later cherry-picks keep the original item."""
        patch_key = "patch:" + pid if pid else None
        key = self.data.get(commit.sha) or (self.data.get(patch_key) if patch_key else None) or proposed
        self.data.setdefault(commit.sha, key)
        if patch_key:
            self.data.setdefault(patch_key, key)
        return key

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        os.replace(tmp, self.path)


@dataclass
class Group:
    key: str
    branch: str | None = None
    title_hint: str | None = None
    commits: list = field(default_factory=list)
    dirty_files: int = 0
    dirty_mtime: datetime | None = None


def _merge_name(repo, merge) -> str | None:
    if len(merge.parents) > 2:
        return None  # An octopus merge does not belong to only its second parent.
    if SYNC_MERGE.match(merge.subject):
        return "main"
    match = MERGE_NAME.match(merge.subject)
    if match:
        return _normalize(match.group(1))
    found = gitdata.name_rev(repo, merge.parents[1])
    # name-rev 可能把提交算到「合并之后才从 main 切出」的分支名下（实测 111 个无名合并错 94 个）：
    # 该分支若已包含这次合并本身，说明它不是被合并的那个分支，丢弃名字
    if not found or gitdata.is_ancestor(repo, merge.sha, found):
        return None
    return _normalize(found)


def _batch_key(c) -> str:
    return f"batch:{c.at:%Y%m%d}-{module_of(c.files) or 'misc'}-{agent_of(None, c.coauthors)}"


def build_groups(repo, since: str, *, keymap: KeyMap, cache, now: datetime, main: str = "main") -> list[Group]:
    proposed: dict[str, Group] = {}

    def add(key, commits, branch=None, title_hint=None):
        group = proposed.setdefault(key, Group(key=key, branch=branch, title_hint=title_hint))
        known = {c.sha for c in group.commits}
        group.commits.extend(c for c in commits if c.sha not in known)

    loose = []
    for entry in gitdata.first_parent(repo, main, since):
        if not entry.is_merge:
            loose.append(entry)
            continue
        # Include all parents and nested semantic merges, not only parent #2.
        inner = gitdata.range_commits(repo, entry.parents[0], entry.sha, cache=cache)
        if not inner:
            continue
        name = _merge_name(repo, entry)
        if name in ("main", "master"):
            loose.extend(inner)
        elif name and not is_process_branch(name):
            add(f"branch:{name}", inner, branch=name)
        else:
            add(f"merge:{entry.sha}", inner, title_hint=entry.subject)

    since_at = gitdata.to_bj_naive(since + "T00:00:00+08:00")
    open_groups = {}
    for branch in gitdata.branches(repo):
        if is_process_branch(branch.name) or branch.at < since_at:
            continue
        own = gitdata.range_commits(repo, main, branch.name, cache=cache)
        if own:
            open_groups[branch.name] = own
            add(f"branch:{branch.name}", own, branch=branch.name)

    # 直接提交若与未合并分支内容等价，归该分支，避免一件事算两次
    branch_pids = cache.get(repo, [c.sha for own in open_groups.values() for c in own])
    owner = {branch_pids[c.sha]: name for name, own in open_groups.items() for c in own if c.sha in branch_pids}
    loose_pids = cache.get(repo, [c.sha for c in loose])
    for c in loose:
        name = owner.get(loose_pids.get(c.sha))
        add(f"branch:{name}" if name else _batch_key(c), [c], branch=name)

    fresh_after = now - timedelta(days=DIRTY_FRESH_DAYS)
    for tree in gitdata.worktrees(repo):
        if (not tree.branch or tree.branch == main or is_process_branch(tree.branch) or tree.dirty_files == 0
                or tree.dirty_mtime is None or tree.dirty_mtime < fresh_after):
            continue
        group = proposed.setdefault(f"branch:{tree.branch}", Group(key=f"branch:{tree.branch}", branch=tree.branch))
        group.dirty_files, group.dirty_mtime = tree.dirty_files, tree.dirty_mtime

    final: dict[str, Group] = {}
    all_pids = cache.get(repo, [c.sha for group in proposed.values() for c in group.commits])
    # Preserve ownership per commit, not a majority vote that silently moves old items.
    claimed = set()
    for group in proposed.values():
        partitions = {}
        for commit in group.commits:
            if commit.sha in claimed:
                continue
            claimed.add(commit.sha)
            key = keymap.resolve_commit(commit, group.key, all_pids.get(commit.sha))
            partitions.setdefault(key, []).append(commit)
        if not group.commits:
            partitions[group.key] = []
        for key, commits in partitions.items():
            target = final.setdefault(key, Group(key=key, branch=group.branch, title_hint=group.title_hint))
            target.commits.extend(commits)
            target.branch = target.branch or group.branch
            target.title_hint = target.title_hint or group.title_hint
            if group.dirty_files:
                target.dirty_files, target.dirty_mtime = group.dirty_files, group.dirty_mtime
    for group in final.values():
        group.commits.sort(key=lambda c: c.at)
    return list(final.values())
