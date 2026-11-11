"""项目雷达更新分级与推送降噪。"""

from __future__ import annotations

import re

_BREAKING_RE = re.compile(r"breaking|deprecat|security|\bcve[-\s]?\w*|incompatible|不兼容|移除|安全", re.IGNORECASE)
_PRERELEASE_RE = re.compile(r"(?:^|[-.\d])(alpha|beta|rc|nightly|canary|dev)(?:[-.\d]|$)", re.IGNORECASE)


def _major(version: str | None) -> int | None:
    match = re.search(r"\d+", version or "")
    return int(match.group(0)) if match else None


def rule_level(from_version=None, to_version=None, release_notes="", *, archived=False, deleted=False, signal="release"):
    if archived or deleted:
        return "key"
    if signal in {"commit", "stars", "activity"}:
        return "noise"
    if _PRERELEASE_RE.search(to_version or ""):
        return "noise"
    if _BREAKING_RE.search(release_notes or ""):
        return "key"
    old_major, new_major = _major(from_version), _major(to_version)
    if old_major is not None and new_major is not None and new_major > old_major:
        return "key"
    return "normal"


def should_push(watch_level, level, release_notes="", *, days_since_normal_push=None):
    if watch_level == "silent" or level not in {"key", "normal"}:
        return False
    if watch_level == "adopted":
        return level == "key" and bool(_BREAKING_RE.search(release_notes or ""))
    if level == "key":
        return True
    if watch_level != "key":
        return False
    return days_since_normal_push is None or days_since_normal_push >= 7
