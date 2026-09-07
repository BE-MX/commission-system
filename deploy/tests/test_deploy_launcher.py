"""Exercise the Windows entry point with a harmless publisher in a temporary repo."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Requires Windows cmd.exe")
PROMPT = "Press any key to close this window..."


@pytest.mark.parametrize("exit_code", [0, 23])
@pytest.mark.parametrize("unattended", [False, True])
def test_launcher_keeps_result_visible_and_preserves_exit_code(tmp_path, exit_code, unattended):
    root = tmp_path / "release folder (test)"
    deploy = root / "deploy"
    deploy.mkdir(parents=True)
    launcher = deploy / "deploy.bat"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "deploy.bat", launcher)
    (deploy / "publish.py").write_text(
        "import json, sys\n"
        "print('PUBLISHER_ARGS=' + json.dumps(sys.argv[1:]), flush=True)\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("DEPLOY_NO_PAUSE", None)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    if unattended:
        env["DEPLOY_NO_PAUSE"] = "1"
    process = subprocess.Popen(
        f'"{env["COMSPEC"]}" /d /c ""{launcher}" --no-pull --migration-credentials "protected file.txt""',
        cwd=Path(env["SYSTEMROOT"]) / "System32",
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    prefix = ""
    try:
        if not unattended:
            for line in process.stdout:
                prefix += line
                if PROMPT in line:
                    break
            assert PROMPT in prefix
            # A visible message alone is insufficient: wait for the user's key.
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=0.2)
    finally:
        stdout, stderr = process.communicate(input="\n", timeout=15)
    result = subprocess.CompletedProcess(process.args, process.returncode, prefix + stdout, stderr)
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert "PUBLISHER_ARGS=" + json.dumps([
        "--no-pull", "--migration-credentials", "protected file.txt",
    ]) in result.stdout
    assert ("Deployment failed." in result.stdout) == bool(exit_code)
    assert (PROMPT in result.stdout) == (not unattended)


def test_default_launcher_selects_installed_git_ssh(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "deploy.bat", deploy / "deploy.bat")
    git_root = tmp_path / "Git installation (test)"
    git_bin = git_root / "usr/bin"
    git_bin.mkdir(parents=True)
    git_cmd = git_root / "cmd"
    git_cmd.mkdir()
    (git_cmd / "git.exe").write_bytes(b"discovery-only fixture")
    (git_bin / "ssh.exe").write_bytes(b"discovery-only fixture")
    (deploy / "publish.py").write_text(
        "import shutil,pathlib\nprint('SSH_PATH=' + str(pathlib.Path(shutil.which('ssh')).resolve()))\n", encoding="utf-8")
    env = dict(os.environ, DEPLOY_NO_PAUSE="1")
    env["PATH"] = os.pathsep.join([str(git_cmd), str(Path(sys.executable).parent), env["PATH"]])
    result = subprocess.run(
        f'"{env["COMSPEC"]}" /d /c ""{deploy / "deploy.bat"}""', env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ("SSH_PATH=" + str(git_bin / "ssh.exe")).lower() in result.stdout.lower()
