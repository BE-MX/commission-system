from pathlib import Path

import pytest

from app import bootstrap
from app.core.config import Settings
from app.invoice import export_service


def test_pdf_cjk_font_path_is_managed_by_settings(monkeypatch, tmp_path):
    configured = tmp_path / "invoice-cjk.ttf"
    monkeypatch.setenv("PDF_CJK_FONT_PATH", str(configured))

    settings = Settings(_env_file=None)

    assert Path(settings.PDF_CJK_FONT_PATH) == configured


def test_pdf_font_preflight_fails_early_with_actionable_missing_path(tmp_path):
    missing = tmp_path / "missing-cjk.ttf"
    settings = Settings(PDF_CJK_FONT_PATH=str(missing), _env_file=None)

    with pytest.raises(RuntimeError, match="PDF_CJK_FONT_PATH.*不存在"):
        bootstrap.check_pdf_export_resources(settings=settings)


def test_pdf_export_uses_only_the_configured_font_path(monkeypatch, tmp_path):
    missing = tmp_path / "configured-but-missing.ttf"
    settings = Settings(PDF_CJK_FONT_PATH=str(missing), _env_file=None)
    monkeypatch.setattr(export_service, "get_settings", lambda: settings, raising=False)
    export_service._cjk_font.cache_clear()

    with pytest.raises(RuntimeError, match="PDF_CJK_FONT_PATH"):
        export_service._cjk_font(12)
