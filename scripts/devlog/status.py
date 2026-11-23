# scripts/devlog/status.py
"""状态判定：先看 sha 是否可达（祖先关系，开销小），不可达时再比 patch-id（cherry-pick 的内容等价）。
patch-id 持久缓存在 .devlog_state/patch-ids.json，首轮之后只算新增提交。只看 Git 证据，不读任何人写的状态词。
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import gitdata
from classify import agent_of, item_type, module_of
from grouping import Group
from redact import redact_title, safe_identifier

STALE_DAYS = 14
PID_MARGIN_DAYS = 120
GLOBAL_SCOPE = "office-and-cloud"
CONFIG_LINE = re.compile(r"^\s{4}([A-Z][A-Z0-9_]+)\s*:")
PERMISSION_LINE = re.compile(r'^\s*\("([a-z0-9_]+:[a-z0-9_]+)"')


@dataclass
class Release:
    revision: str
    released_at: datetime
    scope: str


class PatchCache:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}

    def get(self, repo, shas) -> dict[str, str]:
        missing = [s for s in dict.fromkeys(shas) if s not in self.data]
        for start in range(0, len(missing), 400):
            chunk = missing[start:start + 400]
            computed = gitdata.patch_ids(repo, chunk)
            for sha in chunk:
                self.data[sha] = computed.get(sha, "")   # "" = 空 diff，不参与内容比对
        return {s: self.data[s] for s in shas if self.data.get(s)}

    def merge_files(self, repo, commit):
        key = "merge-files:" + commit.sha
        if key not in self.data:
            self.data[key] = gitdata.merge_changes(repo, commit)
        return self.data[key]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        os.replace(tmp, self.path)


class Membership:
    def __init__(self, shas: set[str], pids: set[str]):
        self.shas, self.pids = shas, pids

    def contains(self, sha: str, pid: str | None) -> bool:
        return sha in self.shas or (pid is not None and pid in self.pids)


def _branch_membership(repo, ref, since, cache) -> Membership:
    margin = (datetime.fromisoformat(since) - timedelta(days=PID_MARGIN_DAYS)).date().isoformat()
    recent = gitdata.reachable_shas(repo, ref, margin)
    return Membership(gitdata.reach(repo, ref), set(cache.get(repo, recent).values()))


def _release_membership(repo, release, since, cache) -> Membership:
    # Shared main history can also contain a cherry-pick of an open branch commit.
    # Excluding main here misses that equivalent patch even though production has it.
    return _branch_membership(repo, release.revision, since, cache)


def _hotfix_groups(repo, releases, main, main_m, origin_m, cache, existing=(), keymap=None) -> list[Group]:
    """只在发布分支上、未回合 main 的提交。同一 revision 只取最早一次；同一提交只归最早那次发布。"""
    groups, seen_revisions, claimed = [], set(), set()
    known = [c.sha for group in existing for c in group.commits]
    claimed.update(known)
    claimed_pids = set(cache.get(repo, known).values())
    for release in releases:   # 已按 released_at 升序
        if release.revision in seen_revisions:
            continue
        seen_revisions.add(release.revision)
        only = gitdata.range_commits(repo, main, release.revision, cache=cache)
        pids = cache.get(repo, [c.sha for c in only])
        fixes = [c for c in only if c.sha not in claimed and pids.get(c.sha) not in claimed_pids
                 and not main_m.contains(c.sha, pids.get(c.sha)) and not origin_m.contains(c.sha, pids.get(c.sha))]
        claimed.update(c.sha for c in fixes)
        claimed_pids.update(pids[c.sha] for c in fixes if c.sha in pids)
        partitions = {}
        for commit in fixes:
            proposed = f"batch:hotfix-{release.revision[:12]}"
            key = keymap.resolve_commit(commit, proposed, pids.get(commit.sha)) if keymap is not None else proposed
            partitions.setdefault(key, []).append(commit)
        groups.extend(Group(key=key, commits=commits) for key, commits in partitions.items())
    return groups


def _preconditions(repo, commits):
    migrations, config_keys, permissions = [], [], []
    for c in commits:
        for change, path in c.files:
            if change == "A" and path.startswith("backend/alembic/versions/") and path.endswith(".py"):
                migrations.append(path.rsplit("/", 1)[-1][:-3])
            if path == "backend/app/core/config.py":
                config_keys += [m.group(1) for line in gitdata.show_added_lines(repo, c.sha, path) if (m := CONFIG_LINE.match(line))]
            if path == "backend/app/auth/service.py":
                permissions += [m.group(1) for line in gitdata.show_added_lines(repo, c.sha, path) if (m := PERMISSION_LINE.match(line))]
    unique = lambda values: list(dict.fromkeys(values))[:20]
    return {"migrations": unique(migrations), "config_keys": unique(config_keys), "permissions": unique(permissions)}


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _title(group: Group, subjects: list[str]) -> str:
    if group.title_hint:
        return redact_title(group.title_hint)
    if subjects:
        text = subjects[0] + (f" 等{len(subjects)}项" if group.key.startswith("batch:") and len(subjects) > 1 else "")
        return redact_title(text)
    return redact_title((group.branch or "").split("/")[-1].replace("-", " "))


def compute_items(repo, groups, since, *, releases, cache, origin_ref="origin/main", main="main", now: datetime, keymap=None) -> list[dict]:
    main_m = _branch_membership(repo, main, since, cache)
    origin_m = _branch_membership(repo, origin_ref, since, cache) if origin_ref else Membership(set(), set())
    global_releases = sorted((r for r in releases if r.scope == GLOBAL_SCOPE), key=lambda r: r.released_at)
    release_ms = [(r, _release_membership(repo, r, since, cache)) for r in global_releases]
    groups = list(groups)
    groups += _hotfix_groups(repo, global_releases, main, main_m, origin_m, cache, groups, keymap)
    # A multi-commit hotfix may be only partly integrated into main this round.
    # Its integrated and release-only parts must still be one original item.
    merged = {}
    for group in groups:
        if group.key not in merged:
            merged[group.key] = group
        else:
            target = merged[group.key]
            known = {c.sha for c in target.commits}
            target.commits.extend(c for c in group.commits if c.sha not in known)
    groups = list(merged.values())
    items = []
    for group in groups:
        commits = group.commits
        pids = cache.get(repo, [c.sha for c in commits])
        # A merge-only resolution can have no ordinary patch-id. It must not be
        # discarded just because the inner commits do have patch-ids.
        relevant = [c for c in commits if c.is_merge or c.sha in pids] or commits

        def covered(m):
            return bool(relevant) and all(m.contains(c.sha, pids.get(c.sha)) for c in relevant)

        last_commit_at = max((c.at for c in commits), default=None)
        released = next((r for r, m in release_ms if covered(m)), None)
        if not commits:
            status, status_at = "dev", group.dirty_mtime
        elif released:
            status, status_at = "released", released.released_at
        elif covered(origin_m):
            status, status_at = "pending_release", last_commit_at
        elif covered(main_m):
            status, status_at = "pending_push", last_commit_at
        else:
            status, status_at = "pending_merge", last_commit_at
        last_activity = max(t for t in (last_commit_at, group.dirty_mtime, status_at) if t)
        stale = status != "released" and last_activity < now - timedelta(days=STALE_DAYS)
        subjects = [c.subject for c in commits]
        files = [f for c in commits for f in c.files]
        evidences = [{"kind": "branch", "ref": safe_identifier(group.branch), "at": _iso(last_activity)}] if group.branch else []
        evidences += [{"kind": "commit", "ref": c.sha, "at": _iso(c.at)} for c in commits[-50:]]
        if released:
            evidences.append({"kind": "release", "ref": released.revision, "at": _iso(released.released_at)})
        if group.dirty_files:
            evidences.append({"kind": "worktree", "ref": f"dirty-{group.dirty_files}", "at": _iso(group.dirty_mtime)})
        item = {
            "key": ("branch:" + safe_identifier(group.key.split(":", 1)[1], 180)) if group.key.startswith("branch:") else group.key,
            "title": _title(group, subjects), "type": item_type(subjects or ["Add draft"], files),
            "module": module_of(files), "agent": agent_of(group.branch, " ".join(c.coauthors for c in commits)),
            "status": status, "status_at": _iso(status_at), "last_activity_at": _iso(last_activity), "stale": stale,
            "unmerged_hotfix": bool(released) and not covered(main_m),
            "released_revision": released.revision if released else None,
            "preconditions": _preconditions(repo, commits) if status != "released" else {"migrations": [], "config_keys": [], "permissions": []},
            "evidences": evidences,
        }
        basis = {k: item[k] for k in ("key", "status", "stale", "released_revision", "title", "type", "module")}
        basis["commits"] = sorted(c.sha for c in commits)
        basis["dirty"] = group.dirty_files
        basis["dirty_mtime"] = _iso(group.dirty_mtime) if group.dirty_mtime else None
        basis["preconditions"] = item["preconditions"]
        basis["unmerged_hotfix"] = item["unmerged_hotfix"]
        item["fingerprint"] = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
        items.append(item)
    return items
