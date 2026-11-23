# scripts/devlog/classify.py
"""类型 / 模块 / 代理推断：确定性规则，判不出就给保守默认值。"""
import re
from collections import Counter

TYPE_RULES = [
    ("data", re.compile(r"\b(backfill|recover|restore|reconcile|migrate data|data repair)\b", re.I)),
    ("bug", re.compile(r"^(fix|hotfix|repair|correct|prevent|guard)\b|\bfix(es|ed)?\b", re.I)),
    ("feature", re.compile(r"^(add|implement|introduce|support|enable|feat|create|build)\b", re.I)),
]
PRIORITY = ["feature", "data", "bug", "improve", "ops", "docs"]
SHARED_DIRS = {"core", "api", "services", "models", "schemas", "utils", "bootstrap", "schedulers", "tests",
               "components", "composables", "styles", "config", "layout"}
AGENTS = ("codex", "claude", "kimi", "accio")


def _subject_type(subject: str) -> str:
    for name, pattern in TYPE_RULES:
        if pattern.search(subject):
            return name
    return "improve"


def _path_type(files) -> str | None:
    paths = [path for _, path in files]
    if paths and all(p.startswith("docs/") or p.endswith(".md") for p in paths):
        return "docs"
    if paths and all(p.startswith(("deploy/", "scripts/")) for p in paths):
        return "ops"
    return None


def item_type(subjects: list[str], files=()) -> str:
    counts = Counter(_subject_type(s) for s in subjects)
    by_path = _path_type(files)
    if by_path and set(counts) == {"improve"}:
        return by_path
    best = max(counts.values())
    return next(name for name in PRIORITY if counts.get(name) == best)


def module_of(files) -> str:
    counts = Counter()
    for _, path in files:
        parts = path.split("/")
        if parts[:2] == ["backend", "app"] and len(parts) > 3:
            counts[parts[2]] += 1
        elif parts[:3] == ["frontend", "src", "views"] and len(parts) > 4:
            counts[parts[3].replace("-", "_")] += 1
    for name, _ in counts.most_common():
        if name not in SHARED_DIRS and re.fullmatch(r"[a-z0-9_]{1,40}", name):
            return name
    return ""


def agent_of(branch: str | None, coauthors: str) -> str:
    if branch and branch.split("/")[0] in AGENTS:
        return branch.split("/")[0]
    lowered = coauthors.lower()
    return next((name for name in AGENTS if name in lowered), "unknown")
