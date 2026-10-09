"""Actual customer main uses real stock SQL with owned synthetic mirror rows."""
from datetime import timedelta
from decimal import Decimal
import json,re
from pathlib import Path
import pytest
from sqlalchemy import Column,BigInteger,Integer,DateTime,Numeric,MetaData,Table,event,select
from sqlalchemy.orm import Session
from app.core.time import beijing_now
from app.portal import catalog_service,inventory_source,auth_service,mapping_service
from app.portal.models import CatalogItem,Quote,OrderRequest,RequestLine,Revision,CustomerAccess,MappingRevision
from app.invoice.models import Invoice,InvoiceItem
from app.receipt.models import ReceiptIntent
from test_mysql_application_trade import commerce,business_snapshot  # noqa: F401
from test_mysql_full_application import assembled,boot  # noqa: F401
from test_mysql_customer_application_browser import ROOT,live_application,run_browser


@pytest.fixture(autouse=True)
def mirror_inventory(boot,trade,request,monkeypatch):
    # boot -> trade -> mirror seed -> assembled/commerce write fence. No original
    # fence is weakened; the application only SELECTs this stock mirror.
    ctx=trade;scenario=request.param
    assert scenario in {'fresh','stale'}
    from app.portal.schemas import MappingInput
    with Session(ctx.engine) as db:
        access=db.get(CustomerAccess,ctx.access_id)
        published=mapping_service.publish(db,ctx.admin,access.public_id,access.row_version,MappingInput(base_version=0,entries=[]))
        assert published['mapping_version']==1
        db.commit()
    metadata=MetaData()
    table=Table('okki_inventory',metadata,Column('id',BigInteger,primary_key=True,autoincrement=True),
        Column('product_id',BigInteger),Column('sku_id',BigInteger),Column('enable_count',Numeric(20,6)),
        Column('disable_flag',Integer),Column('synced_at',DateTime))
    metadata.create_all(ctx.engine,checkfirst=True)
    settings=auth_service.get_settings()
    settings.PORTAL_INVENTORY_OBSERVED_COLUMN='synced_at'
    settings.PORTAL_INVENTORY_SOURCE_TIMEZONE='Asia/Shanghai'
    with Session(ctx.engine) as db:
        item=db.scalar(select(CatalogItem).where(CatalogItem.public_id==ctx.item_id))
        product,sku=int(item.product_id),int(item.sku_id)
        settings.PORTAL_INVENTORY_UNIT_BY_SKU={f'{product}:{sku}':'g'}
        item.safety_buffer=Decimal('5')
        latest=beijing_now().replace(microsecond=0)
        stamp=latest-timedelta(seconds=2)
        db.execute(table.insert(),[
            {'product_id':product,'sku_id':sku,'enable_count':Decimal('60'),'disable_flag':0,'synced_at':stamp},
            {'product_id':product,'sku_id':sku,'enable_count':Decimal('20'),'disable_flag':0,'synced_at':latest if scenario=='fresh' else stamp-timedelta(minutes=5)},
            {'product_id':product,'sku_id':sku,'enable_count':Decimal('9999'),'disable_flag':1,'synced_at':stamp},
            {'product_id':product,'sku_id':sku+1,'enable_count':Decimal('9999'),'disable_flag':0,'synced_at':stamp}])
        db.commit()
    monkeypatch.setattr(inventory_source,'get_settings',lambda:settings)
    monkeypatch.setattr(catalog_service,'load_observations',inventory_source.load)
    probe={'selects':0}
    def read_stock(connection,cursor,statement,parameters,context,executemany):
        if re.search(r'\bFROM\s+`?portal_isolated_test`?\.okki_inventory\b',statement,re.I):probe['selects']+=1
    event.listen(ctx.engine,'before_cursor_execute',read_stock)
    try:yield {'scenario':scenario,'table':table,'probe':probe,'stamp':stamp}
    finally:event.remove(ctx.engine,'before_cursor_execute',read_stock)


@pytest.mark.parametrize('mirror_inventory',['fresh','stale'],indirect=True)
def test_actual_customer_stock_sql_timestamp_and_stale_refusal(commerce,mirror_inventory,request):
    c=commerce;case=mirror_inventory
    assert catalog_service.load_observations is inventory_source.load
    runtime=[request.config.getoption('portal_browser_'+name) for name in ('node','module','chromium')]
    if not all(runtime):pytest.skip('Explicit owned Node, Playwright and Chrome paths required')
    node,playwright,chrome=(str(Path(value).resolve(strict=True)) for value in runtime)
    output=Path(request.config.getoption('portal_mysql_workspace')).resolve()/('inventory-evidence-'+case['scenario']);output.mkdir()
    with Session(c.app.ctx.engine) as db:
        mapping_before=tuple(db.execute(select(*MappingRevision.__table__.columns).order_by(MappingRevision.id)).all())
        stock_before=tuple(db.execute(select(case['table']).order_by(case['table'].c.id)).all())
        quotes_before=tuple(db.execute(select(*Quote.__table__.columns).order_by(Quote.id)).all())
    before=business_snapshot(c)
    with live_application(c) as (origin,shell):
        summary=run_browser(c,shell,node,ROOT/'frontend-portal/tests/applicationInventory.browser.mjs',origin,playwright,chrome,output)
        (output/'runner-summary.json').write_text(json.dumps(summary),encoding='utf-8')
        assert summary['exit_code']==0 and not summary['timed_out'] and summary['child_reaped'] and not summary['cleanup_failure']
        report=json.loads((output/'report.json').read_text())
        assert report['status']=='pass' and report['scenario']==case['scenario'] and report['businessResponseInterceptions']==0
        assert case['probe']['selects']>=2
        with Session(c.app.ctx.engine) as db:
            assert tuple(db.execute(select(*MappingRevision.__table__.columns).order_by(MappingRevision.id)).all())==mapping_before
            assert tuple(db.execute(select(case['table']).order_by(case['table'].c.id)).all())==stock_before
            if case['scenario']=='stale':
                assert tuple(db.execute(select(*Quote.__table__.columns).order_by(Quote.id)).all())==quotes_before
                assert business_snapshot(c)[:9]==before[:9]
                assert not shell.pdf_documents
            else:
                order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==report['requestId']))
                assert order.status=='invoice_created' and order.account_id==c.buyer_id
                invoice=db.get(Invoice,order.invoice_id);line=db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id))
                assert invoice.total_amount==81 and invoice.sales_user_id==c.app.ctx.actor
                assert line.quantity==3 and str(line.product_id)==c.product_id and line.model==c.standard['model'] and line.color==c.standard['color']
                quote=db.scalar(select(Quote).where(Quote.public_id==report['quoteId']))
                evidence=quote.lines_json[0]['inventory_snapshot']
                assert Decimal(evidence['quantity'])==80 and evidence['unit']=='g'
                assert Decimal(evidence['conversion_factor'])==20 and Decimal(evidence['safety_buffer'])==5
                assert evidence['source'].startswith('okki_inventory:okki:test:') and evidence['source'].endswith(':synced_at')
                assert quote.lines_json[0]['inventory_observed_at']==case['stamp'].isoformat()
                assert quote.product_amount==81 and quote.account_id==c.buyer_id
                revision=db.get(Revision,order.accepted_revision_id);record=db.scalar(select(RequestLine).where(RequestLine.revision_id==revision.id))
                assert record.unit_weight_grams==20 and record.qty==3 and record.unit_price==27 and record.line_amount==81
                assert str(record.product_id)==c.product_id and quote.status=='consumed'
                from app.portal.revision_evidence import verify
                verify(revision,[record])
                intents=db.scalars(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)).all()
                # Portal PIs skip the creation-time receipt intent draft.
                assert intents==[]
                assert not invoice.outbound_auto_requested and invoice.sync_status=='not_synced' and invoice.xiaoman_order_id is None
                from io import BytesIO
                from pypdf import PdfReader
                documents=['\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages) for pdf in shell.pdf_documents]
                assert documents and all('81.00' in value and 'Unit: pack' in value for value in documents)
                downloaded='\n'.join(page.extract_text() for page in PdfReader(str(output/'stock-confirmed.pdf')).pages)
                assert downloaded==documents[0]
                assert shell.pdf_documents
        assert c.calls==[] and c.forbidden_writes==[] and shell.fault_count==0
