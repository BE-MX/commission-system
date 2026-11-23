# scripts/devlog/gitdata.py
"""只读 Git 采集：分支、worktree、first-parent 历史、区间提交与 patch-id。除 fetch 外不做任何写操作。"""
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

BJ = timezone(timedelta(hours=8))
SEP, REC = "\x1f", "\x1e"
LOG_FORMAT = f"{REC}%H{SEP}%P{SEP}%cI{SEP}%s{SEP}%(trailers:key=Co-Authored-By,valueonly,separator=%x20)"


def git(repo, *args, input_text=None, check=True) -> str:
    result = subprocess.run(["git", "--no-optional-locks", "-c", "core.quotepath=false", "-C", str(repo), *args], input=input_text, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=check, timeout=120)
    return result.stdout


def to_bj_naive(iso: str) -> datetime:
    """Git 的 ISO 时间带偏移：先换算到北京时间再去 tzinfo（红线 23）。"""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BJ).replace(tzinfo=None)


@dataclass
class Commit:
    sha: str
    parents: list[str]
    at: datetime
    subject: str
    coauthors: str = ""
    files: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1


def _parse_log(text: str) -> list[Commit]:
    commits = []
    for record in text.split(REC):
        if not record.strip():
            continue
        header, _, rest = record.partition("\n")
        sha, parents, at, subject, coauthors = (header.split(SEP) + [""] * 5)[:5]
        files = []
        for line in rest.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0]:
                files.append((parts[0][0], parts[-1]))
        commits.append(Commit(sha=sha, parents=parents.split() if parents else [], at=to_bj_naive(at),
                              subject=subject.strip(), coauthors=coauthors.strip(), files=files))
    return commits


def first_parent(repo, ref: str, since: str) -> list[Commit]:
    return _parse_log(git(repo, "log", "--first-parent", f"--since={since}", f"--format={LOG_FORMAT}", "--name-status", ref))


def range_commits(repo, exclude: str, include: str, *, cache=None) -> list[Commit]:
    """All side-parent history, retaining merges only when they carry semantic content."""
    commits = list(reversed(_parse_log(git(repo, "log", f"--format={LOG_FORMAT}", "--name-status",
                                          include, f"^{exclude}"))))
    result = []
    for commit in commits:
        if commit.is_merge:
            commit.files = cache.merge_files(repo, commit) if cache is not None else merge_changes(repo, commit)
            if not commit.files:
                continue
        result.append(commit)
    return result


def merge_changes(repo, commit: Commit) -> list[tuple[str, str]]:
    """Changes beyond Git's automatic merge result must be independently covered.

    Octopus merges cannot be remerged; conservatively keep their full first-parent
    delta as evidence rather than silently assuming all content came from parents.
    """
    mode = "--remerge-diff" if len(commit.parents) == 2 else "--first-parent"
    text = git(repo, "show", "--format=", mode, "--name-status", "--no-ext-diff", "--no-textconv", commit.sha)
    return [(parts[0][0], parts[-1]) for line in text.splitlines()
            if len(parts := line.split("\t")) >= 2 and parts[0]]


def reachable_shas(repo, ref: str, since: str) -> list[str]:
    return git(repo, "rev-list", "--no-merges", f"--since={since}", ref).split()


def patch_ids(repo, shas: list[str]) -> dict[str, str]:
    """commit → patch-id（内容等价判定）。空 diff 的提交不出现在结果里。"""
    if not shas:
        return {}
    patches = git(repo, "log", "--no-walk=unsorted", "--stdin", "-p", "--no-color", "--no-ext-diff", "--no-textconv", "--format=commit %H",
                  input_text="\n".join(shas) + "\n")
    out = git(repo, "patch-id", "--stable", input_text=patches)
    return {commit: pid for pid, commit in (line.split() for line in out.splitlines() if line.strip())}


@dataclass
class Branch:
    name: str
    sha: str
    at: datetime


def branches(repo) -> list[Branch]:
    out = git(repo, "for-each-ref", f"--format=%(refname:short){SEP}%(objectname){SEP}%(committerdate:iso-strict)", "refs/heads")
    return [Branch(name, sha, to_bj_naive(at)) for name, sha, at in (line.split(SEP) for line in out.splitlines() if line)]


@dataclass
class Worktree:
    path: Path
    branch: str | None
    dirty_files: int
    dirty_mtime: datetime | None   # 改动文件最近修改的北京时间；用于排除早已废弃的残留改动


def _status_entries(path: Path) -> list[str]:
    """--no-optional-locks：不改写其他代理 worktree 的 index；-z：中文路径不被转义。"""
    raw = subprocess.run(["git", "--no-optional-locks", "-C", str(path), "status", "--porcelain", "-z"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=120).stdout
    entries, parts, i = [], raw.split("\0"), 0
    while i < len(parts):
        entry = parts[i]
        if len(entry) > 3:
            entries.append(entry[3:])
            if any(code in entry[:2] for code in "RC"):   # 重命名/复制：-z 模式下原路径紧跟在后面
                i += 1
        i += 1
    return entries


def _dirty_mtime(path: Path, names: list[str]) -> datetime | None:
    stamps = []
    for name in names:
        target = path / name
        if target.exists():
            stamps.append(target.stat().st_mtime)
    if not stamps:
        return None
    return datetime.fromtimestamp(max(stamps), BJ).replace(tzinfo=None)


def worktrees(repo) -> list[Worktree]:
    result, current = [], {}
    for line in git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if current.get("worktree"):
                path = Path(current["worktree"])
                names = _status_entries(path) if path.exists() else []
                branch = current.get("branch", "").removeprefix("refs/heads/") or None
                result.append(Worktree(path, branch, len(names), _dirty_mtime(path, names)))
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return result


def reach(repo, ref: str) -> set[str]:
    """ref 可达的全部提交（不截断日期；只取 sha，开销很小）。"""
    return set(git(repo, "rev-list", ref).split())


def name_rev(repo, sha: str) -> str | None:
    """为无名合并找回功能分支名（只看本地分支，排除 main/master，否则已合入的提交都会被命名成 main~N）。"""
    out = git(repo, "name-rev", "--name-only", "--no-undefined", "--exclude=refs/heads/main",
              "--exclude=refs/heads/master", "--refs=refs/heads/*", sha, check=False).strip()
    if not out:
        return None
    return re.split(r"[~^]", out, maxsplit=1)[0] or None


def is_ancestor(repo, older: str, newer: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer],
                          capture_output=True).returncode == 0


def object_exists(repo, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0


def fetch(repo) -> tuple[bool, str]:
    result = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin"], capture_output=True, text=True, timeout=120)
    return result.returncode == 0, "" if result.returncode == 0 else "fetch failed"


def show_added_lines(repo, sha: str, path: str) -> list[str]:
    diff = git(repo, "show", "--first-parent", "--no-color", "--no-ext-diff", "--no-textconv", "--format=", sha, "--", path)
    return [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
