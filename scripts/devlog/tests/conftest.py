# scripts/devlog/tests/conftest.py
"""在临时目录建真实 Git 仓库，覆盖 merge、cherry-pick、worktree 场景。"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))


def sh(repo, *args, env_date=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    if env_date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = env_date
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


def commit(repo, path, content, message, when="2026-11-20T10:00:00+08:00"):
    file = Path(repo) / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    sh(repo, "add", path)
    sh(repo, "commit", "-m", message, env_date=when)
    return sh(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    sh(root, "init", "-b", "main")
    # 早于各测试的 SINCE（2026-10-01），不进入采集窗口，避免初始提交被算成事项
    commit(root, "README.md", "base\n", "Initial commit", "2026-09-01T09:00:00+08:00")
    return root
