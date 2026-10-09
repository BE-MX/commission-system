"""Actual customer repeat request adopts current terms without changing history."""
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
from uuid import UUID, uuid4
import pytest
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import CustomerPriceRule, Invoice, InvoiceItem
from app.portal import mapping_service, quote_service, order_service
from app.portal.models import CatalogItem, CustomerAccess, OrderRequest, Revision, RequestLine, Quote, Conversion, Publication
from app.portal.schemas import MappingInput, QuoteInput, SubmitInput
from app.receipt.models import ReceiptIntent
from test_mysql_application_trade import commerce  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_customer_application_browser import ROOT, live_application, run_browser


def source_graph(db, public_id):
    order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==public_id))
    return tuple(tuple(tuple(row) for row in db.execute(select(*model.__table__.columns).where(predicate).order_by(model.id)))
        for model,predicate in [(OrderRequest,OrderRequest.id==order.id),(Revision,Revision.request_id==order.id),(RequestLine,RequestLine.revision_id.in_(select(Revision.id).where(Revision.request_id==order.id)))])


@pytest.fixture(autouse=True)
def reorder_history(boot, trade):
    # Preserve bootstrap ordering and create business history before commerce's
    # write fence. Upstream pricing is an owned synthetic prerequisite.
    ctx=trade
    with Session(ctx.engine) as db:
        access=db.get(CustomerAccess,ctx.access_id)
        catalog=db.scalar(select(CatalogItem).where(CatalogItem.public_id==ctx.item_id))
        color_key=catalog.standard_json['color_key']
        def mapping(version,model,color,sku):
            return mapping_service.publish(db,ctx.admin,access.public_id,access.row_version,MappingInput(base_version=version,entries=[
                dict(kind='sku',source_key=ctx.item_id,item_id=ctx.item_id,display_value=model,customer_sku=sku),
                dict(kind='color',source_key=color_key,display_value=color)]))
        mapping(0,'History Straight','History Black','HISTORY-SKU');db.commit()
        payload=QuoteInput(items=[dict(item_id=ctx.item_id,quantity=3)],delivery=ctx.quote_body.delivery,
            customer_po='HISTORY-PO',remark='Historical repeat note')
        quote=quote_service.create(db,ctx.token,ctx.csrf,payload);db.commit()
        assert quote['product_amount']=='81.00'
        source=order_service.submit(db,ctx.token,ctx.csrf,uuid4(),SubmitInput(quote_id=quote['quote_id'],quote_content_hash=quote['content_hash'],customer_po=payload.customer_po,remark=payload.remark));db.commit()
        mapping(1,'Current Straight','Current Black','CURRENT-SKU');db.commit()
        rule=db.scalar(select(CustomerPriceRule).where(CustomerPriceRule.customer_id==str(access.customer_id)))
        assert rule.adjust_type=='percent' and rule.adjust_value==Decimal('-10')
        rule.adjust_value=Decimal('-20');db.commit()
        return source['request_id']


def test_actual_repeat_request_current_terms_and_immutable_history(commerce,reorder_history,request):
    c=commerce
    runtime=[request.config.getoption('portal_browser_'+name) for name in ('node','module','chromium')]
    if not all(runtime):pytest.skip('Explicit owned Node, Playwright and Chrome paths required')
    node,playwright,chrome=(str(Path(value).resolve(strict=True)) for value in runtime)
    output=Path(request.config.getoption('portal_mysql_workspace')).resolve()/'reorder-evidence';output.mkdir()
    with Session(c.app.ctx.engine) as db:
        before=source_graph(db,reorder_history)
        source=db.scalar(select(OrderRequest).where(OrderRequest.public_id==reorder_history))
        assert source.account_id!=c.buyer_id
        source_access_id=source.access_id
    with live_application(c) as (origin,shell):
        summary=run_browser(c,shell,node,ROOT/'frontend-portal/tests/applicationReorder.browser.mjs',origin,playwright,chrome,output)
        (output/'runner-summary.json').write_text(json.dumps(summary),encoding='utf-8')
        assert summary['exit_code']==0 and not summary['timed_out'] and summary['child_reaped'] and not summary['cleanup_failure']
        report=json.loads((output/'report.json').read_text())
        assert report['status']=='pass' and report['businessResponseInterceptions']==0 and report['reorderPosts']==1
        assert str(UUID(report['sourceId']))==reorder_history and report['sourceId']!=report['requestId']
        assert shell.pdf_documents and shell.fault_count==0 and not shell.arm_accept
        texts=['\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages) for pdf in shell.pdf_documents]
        assert all(all(value in text for value in ('Current Straight','Current Black','CURRENT-SKU','72.00')) for text in texts)
        with Session(c.app.ctx.engine) as db:
            assert source_graph(db,reorder_history)==before
            order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==report['requestId']))
            assert order.status=='invoice_created' and order.account_id==c.buyer_id and order.customer_po==''
            assert order.access_id==source_access_id
            invoice=db.get(Invoice,order.invoice_id)
            assert invoice.total_amount==72 and invoice.sales_user_id==c.app.ctx.actor
            assert not invoice.outbound_auto_requested and invoice.sync_status=='not_synced' and invoice.xiaoman_order_id is None
            assert len(db.scalars(select(Invoice).where(Invoice.source_order_id.in_([reorder_history,order.public_id]))).all())==1
            intents=db.scalars(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)).all()
            # Portal PIs skip the creation-time receipt intent draft.
            assert intents==[]
            assert len(db.scalars(select(Conversion).where(Conversion.request_id==order.id)).all())==1
            assert db.scalar(select(Publication.id).where(Publication.request_id==order.id)) is not None
            revision=db.get(Revision,order.accepted_revision_id)
            assert revision.customer_accepted_by==c.buyer_id and revision.mapping_version==2
            assert revision.remark=='Historical repeat note' and revision.delivery_json['address_line1']=='10 Test Street'
            line=db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id))
            assert str(line.product_id)==c.product_id and line.model==c.standard['model'] and line.color==c.standard['color']
            repeated=db.scalar(select(Quote).where(Quote.public_id==report['quoteId']))
            assert repeated.account_id==c.buyer_id and repeated.product_amount==72 and repeated.customer_po=='' and repeated.total_amount is None
        assert c.calls==[] and c.forbidden_writes==[]
