"""Bounded retention for local DSH JSONL logs that may contain raw business context."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import time


def prune_expired_session_logs(
    session_root: Path,
    *,
    retention_days: int,
    now: float | None = None,
) -> int:
    """Delete only old, regular ``session.jsonl`` files below the configured root.

    Symlinks and non-regular files are ignored. Directory cleanup is intentionally
    omitted: DSH workspaces are not model-writable in Ark's Cordis composition,
    while leaving their empty structure avoids broad recursive deletion semantics.
    """
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    root = session_root.resolve(strict=True)
    cutoff = (time.time() if now is None else now) - retention_days * 86_400
    removed = 0
    for path in root.rglob("session.jsonl"):
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink() or metadata.st_mtime >= cutoff:
            continue
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        os.unlink(resolved)
        removed += 1
    return removed
