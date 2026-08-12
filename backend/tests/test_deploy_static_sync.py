"""Regression checks for the Windows-to-cloud frontend sync path."""

from pathlib import Path


DEPLOY_SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "deploy.bat"


def _scp_smart_section() -> str:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    return script.split("\n:scp_smart\n", 1)[1].split("\n:scp_full\n", 1)[0]


def test_scp_smart_uploads_generic_dist_items() -> None:
    """Static folders such as festival/ must not disappear on hosts without rsync."""
    section = _scp_smart_section()

    assert "STATIC_ITEM_CHANGED" in section
    assert "frontend/public/%%E" in section
    assert 'scp %SSH_OPTS% -r "%%E" %CLOUD_SERVER%:%CLOUD_DIST%/' in section
    assert "if errorlevel 1 set \"SMART_FAIL=1\"" in section


def test_scp_smart_switch_prelude_is_ascii_safe_for_cmd() -> None:
    """cmd.exe corrupts UTF-8 comments while parsing a parenthesized block."""
    section = _scp_smart_section()
    switch_prelude = section.split('if "!SMART_FAIL!"=="0" (', 1)[1].split(
        "    if errorlevel 1 (", 1
    )[0]

    assert switch_prelude.isascii()


def test_cloud_ssh_retries_connection_establishment() -> None:
    """A transient port-22 timeout must get another connection attempt."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "-o ConnectionAttempts=3" in script


def test_deploy_loads_versioned_pantone_solid_coated_data() -> None:
    """Deploying the filtered endpoint must not leave its color collection empty."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert r".\.venv\Scripts\python.exe scripts\import_pantone.py" in script


def test_deploy_stops_backend_before_database_migration() -> None:
    """Old application code must not write while a data migration is running."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    migration = script.split("REM ---------- [4/7] Database migration ----------", 1)[1]

    stop_index = migration.index('"%NSSM_EXE%" stop "%SERVICE_NAME%"')
    upgrade_index = migration.index(r".\.venv\Scripts\python.exe -m alembic upgrade head")

    assert stop_index < upgrade_index
    assert "migration was not started" in migration[stop_index:upgrade_index]


def test_deploy_restarts_backend_only_after_migration_validation() -> None:
    """The new writer starts only after Alembic reports a current revision."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    migration = script.split("REM ---------- [4/7] Database migration ----------", 1)[1]

    validation_index = migration.index('if "%CURRENT_REVISION%"==""')
    restart_index = migration.index(
        'call :restart_nssm_service "%SERVICE_NAME%" "Ark backend"'
    )

    assert validation_index < restart_index
    assert 'set "BACKEND_RESTARTED_AFTER_MIGRATION=1"' in migration[restart_index:]
