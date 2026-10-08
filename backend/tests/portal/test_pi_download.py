from io import BytesIO
from uuid import uuid4
import pytest
from pypdf import PdfReader
from sqlalchemy import select, update
from test_portal_invoice_lifecycle import published, approving, accepted, proposing, submitted, submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context
from app.invoice.models import Invoice
from app.portal import pi_service as service, pi_pdf
from app.portal.models import OrderRequest, Publication
from app.portal.errors import PortalError


@pytest.fixture(autouse=True)
def portable_pdf_font(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    import reportlab
    monkeypatch.setattr(pi_pdf, "get_settings", lambda: SimpleNamespace(
        PDF_CJK_FONT_PATH=str(Path(reportlab.__file__).parent/"fonts"/"Vera.ttf")))


def test_pdf_contains_customer_snapshot_and_valid_pdf(published):
    ctx, invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    data, filename = service.download(ctx.db, ctx.session_token, order.public_id)
    assert data.startswith(b"%PDF-") and filename == "PI-"+order.public_id+".pdf"
    reader = PdfReader(BytesIO(data))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "PROFORMA INVOICE" in text and "128.00" in text
    assert "Buyer Company" in text and "PAYMENT TERMS" in text
    assert "invoice_document_hash" not in text and "line_bindings" not in text


@pytest.mark.parametrize("mutation", ["orm", "bulk", "snapshot", "price", "other_order"])
def test_download_denies_changed_or_unauthorized_document(published, mutation):
    ctx, invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    request_id = order.public_id
    if mutation == "orm":
        invoice.shipping_fee += 1
        ctx.db.commit()
    elif mutation == "bulk":
        ctx.db.execute(update(Invoice).where(Invoice.id == invoice.id).values(remark="Changed by bulk writer"))
        ctx.db.commit()
    elif mutation == "snapshot":
        row = ctx.db.scalar(select(Publication))
        altered = {**row.customer_snapshot_json, "total_amount":"0.01"}
        ctx.db.execute(update(Publication).where(Publication.id == row.id).values(customer_snapshot_json=altered))
        ctx.db.commit()
    elif mutation == "price":
        ctx.access.can_order = ctx.access.can_view_price = False
        ctx.db.commit()
    else:
        request_id = str(uuid4())
    with pytest.raises(PortalError) as caught:
        service.download(ctx.db, ctx.session_token, request_id)
    assert caught.value.status == (403 if mutation == "price" else 404 if mutation == "other_order" else 409)


@pytest.mark.parametrize("mutation", ["permission", "invoice"])
def test_final_check_rejects_change_during_rendering(published, monkeypatch, mutation):
    ctx, invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    def render(snapshot):
        assert not ctx.db.in_transaction()
        if mutation == "permission":
            ctx.access.can_order = ctx.access.can_view_price = False
        else:
            invoice.remark = "Changed during rendering"
        ctx.db.commit()
        return b"%PDF-test"
    monkeypatch.setattr(pi_pdf, "render", render)
    with pytest.raises(PortalError):
        service.download(ctx.db, ctx.session_token, order.public_id)


@pytest.mark.parametrize("development_cookie", [False, True])
def test_http_pi_is_private_pdf(published, monkeypatch, development_cookie):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http
    ctx, invoice = published
    order = ctx.db.scalar(select(OrderRequest))
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(http, "get_settings", lambda: ctx.settings)
    if development_cookie:
        monkeypatch.setattr(http, "cookie_name", lambda kind: "dev-portal_"+kind)
    app = FastAPI(); app.include_router(http.router, prefix="/api/portal/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
            headers={"X-Real-IP":"203.0.113.1"}) as client:
            client.cookies.set("dev-portal_session" if development_cookie else "__Host-portal_session",ctx.session_token)
            response = await client.get("/api/portal/v1/orders/"+order.public_id+"/pi")
            assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["content-disposition"].startswith("attachment;")
    asyncio.run(scenario())


def test_long_customer_rows_paginate_and_markup_is_plain_text(published):
    from copy import deepcopy
    ctx, invoice = published
    snapshot = deepcopy(ctx.db.scalar(select(Publication)).customer_snapshot_json)
    row = snapshot["items"][0]
    row["display_snapshot"]["model_name"] = 'Long customer model <link href="https://example.invalid">plain text</link>'
    snapshot["items"] = [deepcopy(row) for _ in range(40)]
    reader = PdfReader(BytesIO(pi_pdf.render(snapshot)))
    assert len(reader.pages) > 1
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "".join(text.split()).count("plaintext</link>") == 40
    assert all(not page.get("/Annots") for page in reader.pages)


def test_missing_font_reports_safe_configuration_error(published, monkeypatch):
    from types import SimpleNamespace
    ctx, invoice = published
    monkeypatch.setattr(pi_pdf, "get_settings", lambda: SimpleNamespace(PDF_CJK_FONT_PATH="missing-private-path.ttf"))
    with pytest.raises(PortalError) as caught:
        pi_pdf.render(ctx.db.scalar(select(Publication)).customer_snapshot_json)
    assert caught.value.code == "PDF_UNAVAILABLE" and "private-path" not in caught.value.message
