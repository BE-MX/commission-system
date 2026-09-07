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
