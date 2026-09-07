"""Beijing code update. Shared schema is checked, never migrated on a second host."""

import json
from pathlib import Path
import shlex
import subprocess
import sys

from static_sync import SSH_OPTIONS, remote_python

TARGET = "ubuntu@154.8.205.162"
REPOSITORY = "ssh://ubuntu@154.8.205.162/home/ubuntu/repo.git"


def invoke(request):
    result = remote_python(TARGET, Path(__file__).parent / "remote_backend.py", request, timeout=1200)
    # Remote output is operational status only; never dump environment or credentials.
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:] + result.stdout[-2000:])
    return json.loads(result.stdout.splitlines()[-1])


def prepare(repo, revision, allow_pending=False):
    import os
    env = dict(os.environ, GIT_SSH_COMMAND=shlex.join(["ssh", *SSH_OPTIONS]))
    subprocess.run(["git", "push", REPOSITORY, revision + ":refs/heads/deploy/" + revision],
                   cwd=repo, env=env, check=True, timeout=300)
    result = invoke({"action": "prepare", "revision": revision, "allow_pending": allow_pending})
    print("  Beijing backend: " + json.dumps(result), flush=True)
    return result


def activate(revision):
    return invoke({"action": "activate", "revision": revision})
