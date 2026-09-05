"""Prepare source without modifying the running office checkout."""

import os
from pathlib import Path
import shutil
import subprocess


def prepare(live, state, pull):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=live, text=True).strip()
    previous = git("rev-parse", "HEAD")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Commit reviewed source before publishing; checkout must be clean")
    revision = previous
    if pull:
        git("fetch", "--prune")
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
    # Ignored build/runtime settings stay on this machine, never in release archives.
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
    return source, revision, previous
