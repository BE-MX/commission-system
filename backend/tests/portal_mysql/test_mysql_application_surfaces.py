"""Legal display limits with unavailable assets in the actual owned application."""
from io import BytesIO
import json
from pathlib import Path
from uuid import UUID
import pytest
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import Invoice, InvoiceItem
from app.portal.models import Conversion, OrderRequest, Publication, Revision, RequestLine
from app.receipt.models import ReceiptIntent
from test_mysql_application_trade import commerce  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_images import image_case, image_schema  # noqa: F401
from test_mysql_customer_application_browser import ROOT, live_application, run_browser, published_graph

@pytest.fixture(autouse=True)
def approved_surface_image(boot, image_case):
    # Approve the owned image before commerce installs its production-write fence.
    return image_case

def test_actual_long_customer_content_and_asset_failure_trade(commerce, image_case, request):
    c=commerce
    assert c.app.ctx is image_case
    runtime=[request.config.getoption('portal_browser_'+name) for name in ('node','module','chromium')]
    if not all(runtime):pytest.skip('Explicit owned Node, Playwright and Chrome paths required')
    node,playwright,chrome=(str(Path(value).resolve(strict=True)) for value in runtime)
    output=Path(request.config.getoption('portal_mysql_workspace')).resolve()/'surface-evidence';output.mkdir()
    with live_application(c) as (origin,shell):
        summary=run_browser(c,shell,node,ROOT/'frontend-portal/tests/applicationSurfaces.browser.mjs',origin,playwright,chrome,output)
        (output/'runner-summary.json').write_text(json.dumps(summary),encoding='utf-8')
        assert summary['exit_code']==0 and not summary['timed_out'] and summary['child_reaped'] and not summary['cleanup_failure']
        report=json.loads((output/'report.json').read_text())
        assert report['status']=='pass' and report['businessResponseInterceptions']==0
        assert report['approvedImageHttp']==200 and report['imageLoadAborts']>=1
        assert report['fontStatus']=='error' and report['fontRequests']>=1
        assert report['lengths']==dict(model=128,color=128,sku=64,address=200,contact=100,phone=40,po=80)
        assert report['widths']==[1440,390,320] and len(report['stages'])==6
        request_id=str(UUID(report['requestId']))
        assert shell.pdf_documents and not shell.arm_accept and shell.fault_count==0
        texts=['\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages) for pdf in shell.pdf_documents]
        downloaded='\n'.join(page.extract_text() for page in PdfReader(str(output/'surface-confirmed.pdf')).pages)
        assert all(text==downloaded for text in texts)
        compact=''.join(downloaded.split())
        assert all(value in compact for value in ['M'*128,'C'*128,'S'*64,'A'*200,'N'*100,'P'*80,'128.00'])
        assert all(graph==shell.published_graphs[0] for graph in shell.published_graphs)
        assert published_graph(c,request_id)==shell.published_graphs[0]
        with Session(c.app.ctx.engine) as db:
            order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==request_id))
            assert order is not None and order.status=='invoice_created' and order.account_id==c.buyer_id
            invoices=db.scalars(select(Invoice).where(Invoice.source_order_id==request_id)).all()
            assert len(invoices)==1 and invoices[0].id==order.invoice_id
            invoice=invoices[0]
            assert invoice.total_amount==128 and invoice.sales_user_id==c.app.ctx.actor
            assert invoice.outbound_auto_requested==0 and invoice.sync_status=='not_synced' and invoice.xiaoman_order_id is None
            intents=db.scalars(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)).all()
            # Portal PIs skip the creation-time receipt intent draft.
            assert intents==[]
            conversions=db.scalars(select(Conversion).where(Conversion.request_id==order.id)).all()
            assert len(conversions)==1 and conversions[0].invoice_id==invoice.id and conversions[0].status=='created'
            publication=db.scalar(select(Publication).where(Publication.request_id==order.id))
            assert publication is not None
            revision=db.get(Revision,order.accepted_revision_id)
            assert revision.customer_accepted_by==c.buyer_id
            assert revision.delivery_json['address_line1']=='A'*200
            lines=db.scalars(select(RequestLine).where(RequestLine.revision_id==revision.id)).all()
            assert len(lines)==1 and lines[0].customer_display_json['model_name']=='M'*128 and lines[0].customer_display_json['color_name']=='C'*128
            line=db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id))
            assert str(line.product_id)==c.product_id and line.model==c.standard['model'] and line.color==c.standard['color']
        assert c.calls==[] and c.forbidden_writes==[]
