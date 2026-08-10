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
