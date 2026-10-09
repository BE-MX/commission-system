"""Real browser checkout/acceptance and HTTP employee commands; synthetic upstream data."""
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

from fastapi import FastAPI, Header
import pytest
from pypdf import PdfReader
import reportlab
from sqlalchemy import Column, Integer, MetaData, Table, func, select
from sqlalchemy.orm import sessionmaker

from test_approval_service import portal_metadata
from test_quotes import quoting, priced_catalog, catalog, managed, auth_context
from live_browser_server import running_portal
from app.auth.dependencies import get_current_user
from app.core.database import Base, get_db
from app.invoice.models import Invoice, InvoiceDelegateGrant, InvoiceItem
from app.receipt.models import ReceiptIntent
from app.portal import access_policy, authority, invoice_adapter, mapping_service, pi_pdf, order_queries
from app.portal import router as customer_router, admin_router
from app.portal.access_policy import validate_binding as real_validate_binding
from app.portal.models import Conversion, OrderRequest, Publication, RequestLine, Revision
from app.portal.schemas import MappingInput


def test_browser_checkout_customer_acceptance_and_real_pi(quoting, monkeypatch, request):
    paths = [request.config.getoption(name) for name in ('portal_browser_node', 'portal_browser_module', 'portal_browser_chromium')]
    if not all(paths): pytest.skip('Opt in with --portal-browser-node/module/chromium')
    ctx = quoting
    repo = Path(__file__).resolve().parents[3]
    dist = repo / 'frontend-portal/dist'
    assert (dist / 'index.html').exists()
    metadata = MetaData()
    for name in ('ark_user_roles', 'ark_roles', 'ark_role_permissions', 'ark_permissions', InvoiceDelegateGrant.__tablename__):
        source = Base.metadata.tables[name]
        Table(name, metadata, *(Column(c.name, Integer() if c.primary_key else c.type,
            primary_key=c.primary_key, nullable=c.nullable) for c in source.columns))
    metadata.create_all(ctx.db.get_bind())
    monkeypatch.setattr(access_policy, 'validate_binding', real_validate_binding)
    monkeypatch.setattr(customer_router, 'get_settings', lambda: ctx.settings)
    monkeypatch.setattr(authority, 'get_settings', lambda: ctx.settings)
    monkeypatch.setattr(order_queries, 'get_settings', lambda: ctx.settings)
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.2']
    ctx.settings.PORTAL_INVOICE_ENABLED = True
    invoices = invoice_adapter.invoices
    monkeypatch.setattr(invoices, 'resolve_okki_flags', lambda *args: {'okki_new_deal': 1, 'okki_free_shipping': 0, 'okki_first_return': 0})
    monkeypatch.setattr(invoices, 'get_customer_grade', lambda *args: None)
    monkeypatch.setattr(invoices, 'suggest_invoice_no', lambda *args: 'PI-LIVE-TEST')
    monkeypatch.setattr(invoices.product_service, 'valid_okki_product_skus', lambda db, pairs: pairs)
    monkeypatch.setattr(pi_pdf, 'get_settings', lambda: SimpleNamespace(PDF_CJK_FONT_PATH=str(Path(reportlab.__file__).parent / 'fonts/Vera.ttf')))
    item = ctx.items[0]
    mapping_service.publish(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, MappingInput(base_version=0, entries=[
        {'kind': 'sku', 'source_key': item.public_id, 'item_id': item.public_id, 'display_value': 'Silk Collection'},
        {'kind': 'color', 'source_key': item.standard_json['color_key'], 'display_value': 'Midnight'},
    ]))
    ctx.db.commit()
    lock = threading.Lock()
    factory = sessionmaker(bind=ctx.db.get_bind())
    def database():
        with lock, factory() as db: yield db
    def employee(x_test_actor: int = Header(default=1)):
        # Only this pytest app uses synthetic employees. Production JWT is not bypassed.
        return {'sub': str(x_test_actor)}
    app = FastAPI()
    app.include_router(customer_router.router, prefix='/api/portal/v1')
    app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = employee
    tmp_path = request.getfixturevalue('tmp_path')
    with running_portal(app, ctx, dist, tmp_path) as (origin, backend):
        result = subprocess.run([paths[0], str(repo / 'frontend-portal/tests/liveTrade.browser.mjs'),
            origin, backend, paths[1], paths[2], str(tmp_path)],
            input=json.dumps({'session': ctx.session_token, 'item_id': item.public_id}),
            text=True, capture_output=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report['status'] == 'pass' and report['apiInterceptions'] == 0
    ctx.db.expire_all()
    order = ctx.db.scalar(select(OrderRequest))
    assert order.status == 'invoice_created' and order.row_version == 4
    assert ctx.db.scalar(select(func.count()).select_from(OrderRequest)) == 1
    for model in (Invoice, InvoiceItem, Conversion, Publication):
        assert ctx.db.scalar(select(func.count()).select_from(model)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(ReceiptIntent)) == 0
    invoice = ctx.db.get(Invoice, order.invoice_id)
    assert invoice.total_amount == Decimal('128.00') and invoice.source_type == 'portal'
    assert invoice.sales_user_id == 1
    actual_line = ctx.db.scalar(select(InvoiceItem))
    assert str(actual_line.product_id) == item.product_id and str(actual_line.sku_id) == item.sku_id
    assert actual_line.model == 'ST' and actual_line.color == '1'
    assert actual_line.price_per_piece == Decimal('27.0000')
    assert actual_line.total_price == Decimal('81.00')
    # Portal PIs skip the receipt intent draft; Ark receipt entries handle collection later.
    assert ctx.db.scalar(select(func.count()).select_from(ReceiptIntent)) == 0
    accepted = ctx.db.get(Revision, order.accepted_revision_id)
    line = ctx.db.scalar(select(RequestLine).where(RequestLine.revision_id == accepted.id))
    assert line.customer_display_json['model_name'] == 'Silk Collection'
    assert line.customer_display_json['color_name'] == 'Midnight'
    assert line.standard_json['model'] == 'ST' and line.sku_id == item.sku_id
    pdf = (tmp_path / 'confirmed.pdf').read_bytes()
    assert pdf.startswith(b'%PDF-')
    content = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    assert all(value in content for value in ('PROFORMA INVOICE', '128.00', 'Silk Collection', 'Midnight'))
    print(json.dumps(report))
