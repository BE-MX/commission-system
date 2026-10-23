from pathlib import Path
from types import SimpleNamespace

import pytest
import reportlab

from app.invoice import pdf_font


def test_image_loadable_postscript_font_is_rejected_before_pdf_export(tmp_path, monkeypatch):
    path = tmp_path / 'cff-font.otf'
    path.write_bytes(b'OTTO' + bytes(12))
    # Pillow accepting a font is insufficient: use the actual ReportLab parser.
    monkeypatch.setattr(pdf_font, 'load_configured_cjk_font', lambda *args: object())
    with pytest.raises(RuntimeError, match='PDF_CJK_FONT_PATH.*ReportLab'):
        pdf_font.validate_configured_cjk_font(SimpleNamespace(PDF_CJK_FONT_PATH=str(path)))


def test_reportlab_compatible_font_passes_preflight(monkeypatch):
    path = Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf'
    # CJK glyph validation is separate and remains enforced in production.
    monkeypatch.setattr(pdf_font, 'load_configured_cjk_font', lambda *args: object())
    assert pdf_font.validate_configured_cjk_font(SimpleNamespace(PDF_CJK_FONT_PATH=str(path))) == path
