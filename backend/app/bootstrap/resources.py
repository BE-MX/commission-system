"""Fail-fast checks for non-database runtime resources."""

from app.core.config import Settings
from app.invoice.pdf_font import validate_configured_cjk_font


def check_pdf_export_resources(settings: Settings | None = None):
    return validate_configured_cjk_font(settings)
