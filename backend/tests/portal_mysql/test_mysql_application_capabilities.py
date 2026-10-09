"""Actual read-only customer UI under current Ark capability settings."""
import json
from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import Invoice, InvoiceItem
from app.receipt.models import ReceiptIntent
from app.portal import order_service
from app.portal.models import CustomerAccess, Conversion, Publication, OrderRequest, Revision, RequestLine, Quote, CommandReceipt
from test_mysql_application_trade import commerce  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_customer_application_browser import ROOT, live_application, run_browser


@pytest.mark.parametrize('view_price', [True, False])
def test_actual_readonly_customer_capabilities(commerce, request, view_price):
    c = commerce; c.readonly_price = view_price
    runtime = [request.config.getoption('portal_browser_' + name) for name in ('node', 'module', 'chromium')]
    if not all(runtime): pytest.skip('Explicit owned browser runtimes required')
    node, playwright, chrome = (str(Path(value).resolve(strict=True)) for value in runtime)
    output = Path(request.config.getoption('portal_mysql_workspace')).resolve() / ('readonly-price-' + str(view_price).lower())
    output.mkdir()
    # Real domain submission under the original same-company member; no forged history rows.
    with Session(c.app.ctx.engine) as db:
        history = order_service.submit(db, c.app.ctx.token, c.app.ctx.csrf, c.app.ctx.key, c.app.ctx.body)
        db.commit()
        c.history_request_id, c.history_request_no = history['request_id'], history['request_no']
    models = (Invoice, InvoiceItem, ReceiptIntent, Conversion, Publication, OrderRequest, Revision, RequestLine, Quote, CommandReceipt)
    def snapshot():
        with Session(c.app.ctx.engine) as db:
            return tuple(tuple(tuple(row) for row in db.execute(select(*model.__table__.columns).order_by(model.id)).all()) for model in models)
    before = snapshot()
    with live_application(c) as (origin, shell):
        summary = run_browser(c, shell, node, ROOT / 'frontend-portal/tests/applicationCapabilities.browser.mjs', origin, playwright, chrome, output)
        (output / 'runner-summary.json').write_text(json.dumps(summary), encoding='utf-8')
        assert not summary['timed_out'] and summary['exit_code'] == 0, 'Read-only browser failed; inspect safe evidence'
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        assert report['status'] == 'pass' and report['viewPrice'] is view_price
        assert report['apiInterceptions'] == 0 and len(report['scenarios']) == 6
        assert shell.otp_reads[c.buyer_id] == 1
        with Session(c.app.ctx.engine) as db:
            access = db.get(CustomerAccess, c.app.ctx.access_id)
            assert access.status == 'enabled' and access.can_order is False and access.can_view_price is view_price
            assert access.row_version == c.access_version + 1
        assert snapshot() == before
    assert c.calls == [] and c.forbidden_writes == []
    (output / 'server-evidence.json').write_text(json.dumps({'scope': 'owned read-only application', 'viewPrice': view_price, 'orderingAllowed': False, 'financialGraphUnchanged': True, 'historyRequestId': c.history_request_id, 'historyAndQuoteSnapshotsUnchanged': True}), encoding='utf-8')
