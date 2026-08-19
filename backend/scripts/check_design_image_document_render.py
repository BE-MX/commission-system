"""Deployment preflight for isolated PDF/SVG dieline rendering."""

from __future__ import annotations

import io

from pypdf import PdfWriter

from app.design_image.file_service import normalize_upload


def _pdf_bytes() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=150)
    writer.write(output)
    return output.getvalue()


def main() -> None:
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">'
        b'<path d="M10 10 H190 V90 H10 Z" fill="none" stroke="red"/></svg>'
    )
    for content, mime in ((_pdf_bytes(), "application/pdf"), (svg, "image/svg+xml")):
        normalized = normalize_upload(content, mime, True)
        if normalized.mime_type != "image/png" or normalized.width != 2048:
            raise RuntimeError(f"unexpected {mime} render result")
    print("design-image document render preflight OK", flush=True)


if __name__ == "__main__":
    main()
