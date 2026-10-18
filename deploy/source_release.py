"""Prepare source without modifying the running office checkout."""

import os
import hashlib
from pathlib import Path
import re
import shutil
import subprocess


def prepare(live, state, pull, pinned_revision=None):
    if pinned_revision and not re.fullmatch(r"[0-9a-f]{40}", pinned_revision):
        raise ValueError("Pinned release requires a full commit SHA")
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=live, text=True).strip()
    previous = git("rev-parse", "HEAD")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Commit reviewed source before publishing; checkout must be clean")
    revision = previous
    if pull:
        git("fetch", "--prune")
    if pinned_revision:
        revision = git("rev-parse", pinned_revision + "^{commit}")
        if git("merge-base", previous, revision) != previous:
            raise RuntimeError("Pinned deployment is not a fast-forward")
    elif pull:
        upstream = git("rev-parse", "@{upstream}")
        base = git("merge-base", previous, upstream)
        if base == previous:
            revision = upstream
        elif base != upstream:
            raise RuntimeError("Deployment source is not a fast-forward; reconcile Git first")
    source = state / "sources" / revision
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "--detach", str(source), revision)
        from candidate_retention import record_created
        record_created(state, source, revision, 'source')
    # Ignored build/runtime settings stay on this machine, never in release archives.
    settings = {}
    for name in ("frontend", "frontend-pm", "backend"):
        for original in (live / name).glob(".env*"):
            if original.name.endswith((".example", ".sample")) or not original.is_file():
                continue
            destination = source / name / original.name
            if name == "backend":
                if original.name != ".env":
                    continue
                if not destination.exists():
                    os.link(original, destination)
            else:
                shutil.copy2(original, destination)
            settings[destination.relative_to(source).as_posix()] = hashlib.sha256(destination.read_bytes()).hexdigest()
    from candidate_retention import record_settings
    record_settings(state, source, settings)
    return source, revision, previous
