"""Independent MySQL editing during actual PDF rendering cannot leak a changed PI."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
import reportlab
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.invoice.models import Invoice
from app.portal import approval_service, pi_pdf, pi_service
from app.portal.authority import lock_authority
from app.portal.errors import PortalError
from app.portal.models import AuditEvent, OrderRequest, Publication
from test_mysql_services import accepted_request, count


@pytest.mark.parametrize('sequence', ['edit_during_render', 'rollback_during_render', 'download_before_edit'])
def test_real_mysql_edit_and_download_final_check(trade, monkeypatch, sequence):
    ctx = trade
    request_id, body = accepted_request(ctx)
    with Session(ctx.engine) as db:
        approval_service.approve(db, ctx.actor, request_id, 3, body)
        db.commit()
        order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
        invoice_id = order.invoice_id
        version = db.get(Invoice, invoice_id).portal_document_version
    monkeypatch.setattr(pi_pdf, 'get_settings', lambda: SimpleNamespace(
        PDF_CJK_FONT_PATH=str(Path(reportlab.__file__).parent / 'fonts' / 'Vera.ttf')))
    real_render = pi_pdf.render
    rendering, release = Event(), Event()
    download_connections = []
    def download():
        with Session(ctx.engine) as db:
            download_connections.append(db.scalar(text('SELECT CONNECTION_ID()')))
            def render(snapshot):
                assert not db.in_transaction(), 'Rendering must release the authority and invoice transaction'
                rendering.set()
                assert release.wait(8), 'Editing could not finish while render was paused'
                return real_render(snapshot)
            monkeypatch.setattr(pi_pdf, 'render', render)
            try:
                data, filename = pi_service.download(db, ctx.token, request_id)
                return {'data': data, 'filename': filename}
            except PortalError as error:
                return {'error': error.code, 'status': error.status}
    def edit():
        with Session(edit_connection) as db:
            assert db.scalar(text('SELECT CONNECTION_ID()')) != download_connections[0]
            lock_authority(db, force=True)
            invoice = db.get(Invoice, invoice_id)
            invoice.remark = 'Unaccepted internal revision'
            db.flush()
            assert invoice.portal_document_version == version + 1
            if sequence == 'rollback_during_render':
                db.rollback()
            else:
                db.commit()
    with ctx.engine.connect() as edit_connection, ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(download)
        try:
            assert rendering.wait(8)
            if sequence == 'download_before_edit':
                release.set()
                result = task.result(timeout=10)
                edit()
            else:
                edit()
                release.set()
                result = task.result(timeout=10)
        finally:
            release.set()
    denied = sequence == 'edit_during_render'
    if denied:
        assert result == {'error': 'PI_REVISION_PENDING', 'status': 409}
    else:
        assert result['data'].startswith(b'%PDF-')
        content = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(result['data'])).pages)
        assert '128.00' in content and 'Unaccepted internal revision' not in content
        assert result['filename'] == 'PI-' + request_id + '.pdf'
    with Session(ctx.engine) as db:
        edited = sequence != 'rollback_during_render'
        assert db.get(Invoice, invoice_id).portal_document_version == version + int(edited)
        publication = db.scalar(select(Publication).where(Publication.invoice_id == invoice_id))
        assert publication.status == ('withdrawn' if edited else 'published')
        assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id)
            & (AuditEvent.action == 'order.pi_downloaded')) == int(not denied)
        if edited:
            with pytest.raises(PortalError) as caught:
                pi_service.capture(db, ctx.token, request_id)
            assert caught.value.code == 'PI_REVISION_PENDING'
            db.rollback()
