"""Static execution-safety checks for the isolated MySQL migration gate."""

from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "test_di_migration_mysql.ps1"
)


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_alembic_child_drains_stdout_and_stderr_without_pipe_deadlock():
    script = _script_text()

    assert ".ReadToEnd()" not in script
    stdout_async = script.index("StandardOutput.ReadToEndAsync()")
    stderr_async = script.index("StandardError.ReadToEndAsync()")
    wait = script.index("WaitForExit()")
    stdout_result = script.index("$stdoutTask.Result")
    stderr_result = script.index("$stderrTask.Result")

    assert stdout_async < wait < stdout_result
    assert stderr_async < wait < stderr_result


def test_container_is_registered_for_cleanup_before_start_can_fail():
    script = _script_text()

    create = script.index("docker create")
    cleanup_flag = script.index("$containerCreated = $true", create)
    start = script.index("docker start", cleanup_flag)
    finally_block = script.index("finally")
    cleanup_guard = script.index("if ($containerCreated)", finally_block)
    remove = script.index("docker rm --force", cleanup_guard)

    assert create < cleanup_flag < start < finally_block < cleanup_guard < remove
    assert "docker run" not in script
