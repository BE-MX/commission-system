"""Real source mutations between HTTP commands; no transaction-race claim."""
from decimal import Decimal
from uuid import uuid4
from pathlib import Path
import json,re
import pytest
from sqlalchemy import create_engine,select,update,event
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from app.core.time import beijing_now
from app.invoice.models import CustomerPriceRule,Invoice,InvoiceItem
from app.portal.models import AuditEvent,CatalogItem,CustomerAccess,OrderRequest,Quote,Revision,RequestLine,Conversion,Publication
from app.receipt.models import ReceiptIntent
from test_mysql_application_inventory import mirror_inventory  # noqa: F401
from test_mysql_application_trade import commerce,business_snapshot,customer_login,employee_login,proposal_body,pdf_text
from test_mysql_full_application import assembled,boot  # noqa: F401


def data(response,status=200):
    assert response.status_code==status
    body=response.json();assert body['code']==status
    return body['data']


@pytest.fixture
def price_reads(commerce):
    probe={name:0 for name in ('ark_customer_price_rules','ark_std_prices','ark_price_color_types')}
    def observed(connection,cursor,statement,parameters,context,executemany):
        if not re.match(r'^\s*SELECT\b',statement,re.I):return
        for name in probe:
            if re.search(r'\b(?:FROM|JOIN)\s+[`\"]?'+name+r'[`\"]?(?:\s|$)',statement,re.I):probe[name]+=1
    event.listen(commerce.app.ctx.engine,'before_cursor_execute',observed)
    try:yield probe
    finally:event.remove(commerce.app.ctx.engine,'before_cursor_execute',observed)


@pytest.mark.parametrize('mirror_inventory',['fresh'],indirect=True)
@pytest.mark.parametrize('phase',['submit','accept','approve'])
@pytest.mark.parametrize('changed',['inventory','price'])
def test_actual_source_changes_refuse_stale_commands_and_recover(commerce,mirror_inventory,phase,changed,request,price_reads):
    c=commerce;case=mirror_inventory;ctx=c.app.ctx
    # An independent importer connection changes only this owned DB's source
    # rows. The application engine's unchanged commercial DML fence stays on.
    assert ctx.engine.url.host=='127.0.0.1' and ctx.engine.url.database=='portal_isolated_test'
    importer=create_engine(ctx.engine.url,poolclass=NullPool)
    with Session(ctx.engine) as db:
        item=db.scalar(select(CatalogItem).where(CatalogItem.public_id==c.item_id))
        product,sku=int(item.product_id),int(item.sku_id)
        access=db.get(CustomerAccess,ctx.access_id)
        rule=db.scalar(select(CustomerPriceRule).where(CustomerPriceRule.customer_id==access.okki_company_id))
        assert rule.adjust_type=='percent' and rule.adjust_value==Decimal('-10')
        rule_id=rule.id
    table=case['table']
    rows=(table.c.product_id==product)&(table.c.sku_id==sku)&(table.c.disable_flag==0)
    def untouched_sources():
        with Session(ctx.engine) as db:
            return (tuple(db.execute(select(table).where(~rows).order_by(table.c.id)).all()),
                tuple(db.execute(select(*CustomerPriceRule.__table__.columns).where(CustomerPriceRule.id!=rule_id).order_by(CustomerPriceRule.id)).all()))
    untouched_before=untouched_sources()
    def revision_graph(public_id):
        with Session(ctx.engine) as db:
            revision=db.scalar(select(Revision).where(Revision.public_id==public_id))
            return (tuple(db.execute(select(*Revision.__table__.columns).where(Revision.id==revision.id)).one()),
                tuple(db.execute(select(*RequestLine.__table__.columns).where(RequestLine.revision_id==revision.id).order_by(RequestLine.id)).all()))
    def stock(amount):
        with importer.begin() as connection:
            assert connection.execute(update(table).where(rows).values(enable_count=Decimal(amount),synced_at=beijing_now().replace(microsecond=0))).rowcount==2
    def price(value):
        with importer.begin() as connection:
            assert connection.execute(update(CustomerPriceRule).where(CustomerPriceRule.id==rule_id).values(adjust_value=Decimal(value))).rowcount==1
    def audits():
        with Session(ctx.engine) as db:return tuple(db.execute(select(*AuditEvent.__table__.columns).order_by(AuditEvent.id)).all())
    def preserved_quote(quote_id):
        with Session(ctx.engine) as db:
            row=db.scalar(select(Quote).where(Quote.public_id==quote_id))
            return row.result_hash,row.lines_json,row.product_amount,row.delivery_json,row.payment_terms_snapshot
    try:
        with c.app.client() as client:
            owner=employee_login(client,c,c.owner_name);csrf,_=customer_login(client,c,c.buyer_email)
            headers={'X-Portal-CSRF':csrf};api='/api/portal/v1/orders';admin='/api/portal/admin/v1/orders/'
            quote_body=c.app.ctx.quote_body.model_dump(mode='json')
            quoted=data(client.post('/api/portal/v1/quotes',json=quote_body,headers=headers),201)
            assert quoted['product_amount']=='81.00'
            quote_before=preserved_quote(quoted['quote_id'])
            assert price_reads['ark_customer_price_rules']>0 and price_reads['ark_std_prices']>0
            key=str(uuid4())
            def submit_body(quote):return {'quote_id':quote['quote_id'],'quote_content_hash':quote['content_hash'],'customer_po':quote_body['customer_po'],'remark':quote_body['remark']}
            original_body=submit_body(quoted);submission_headers={**headers,'Idempotency-Key':key}
            request_id=None;proposal=None;accepted=None
            def current():return data(client.get(api+'/'+request_id))
            def propose():
                version=current()['row_version']
                return data(client.post(admin+request_id+'/proposals',headers={**owner,'If-Match':'"'+str(version)+'"'},json=proposal_body(c)))['original_receipt']
            def accept(revision,version):
                return client.post(api+'/'+request_id+'/proposals/'+revision['revision_id']+'/accept',json={'proposal_hash':revision['content_hash']},headers={**headers,'If-Match':'"'+str(version)+'"'})
            def approve(revision,version):
                return client.post(admin+request_id+'/approve',json={'accepted_revision_id':revision['revision_id']},headers={**owner,'If-Match':'"'+str(version)+'"'})
            if phase!='submit':
                submitted=data(client.post(api,json=original_body,headers=submission_headers),201);request_id=submitted['request_id']
                proposal=propose();assert current()['total_amount']=='128.00'
                if phase=='approve':accepted=data(accept(proposal,2))
            original_proposal=proposal
            old_evidence=revision_graph(proposal['revision_id']) if proposal else None
            if changed=='inventory':stock('10')  # 20g total - 5g buffer < 3 * 20g.
            else:price('0')  # Actual rule now prices each pack at 30.
            before=business_snapshot(c);audit_before=audits();reads=case['probe']['selects']
            with Session(ctx.engine) as db:
                quote_columns_before=tuple(db.execute(select(*Quote.__table__.columns).where(Quote.public_id==quoted['quote_id'])).one())
            if phase=='submit':failed=client.post(api,json=original_body,headers=submission_headers)
            elif phase=='accept':failed=accept(proposal,2)
            else:failed=approve(proposal,3)
            expected='STOCK_CHANGED' if changed=='inventory' else 'PRICE_CHANGED' if phase=='submit' else 'PROPOSAL_CHANGED'
            assert failed.status_code==409 and failed.json()['data']['error_code']==expected
            assert business_snapshot(c)==before and preserved_quote(quoted['quote_id'])==quote_before
            with Session(ctx.engine) as db:
                assert tuple(db.execute(select(*Quote.__table__.columns).where(Quote.public_id==quoted['quote_id'])).one())==quote_columns_before
            assert case['probe']['selects']>reads
            audit_after=audits()
            if phase=='approve':
                assert audit_after[:-1]==audit_before
                row=audit_after[-1]._mapping
                assert row['action']=='order.approval_failed' and row['object_public_id']==request_id and row['reason']==expected
                assert row['safe_diff_json']=={'employee_id':ctx.actor}
            else:assert audit_after==audit_before
            # No new accepted terms are invented by retrying a changed price.
            if changed=='inventory':stock('40')
            elif phase=='submit':
                quoted=data(client.post('/api/portal/v1/quotes',json=quote_body,headers=headers),201)
                assert quoted['product_amount']=='90.00'
            elif phase=='accept':
                data(client.post(api+'/'+request_id+'/proposals/'+proposal['revision_id']+'/reject',json={'reason':'Review updated pricing'},headers={**headers,'If-Match':'"2"'}))
                proposal=propose();assert proposal['revision_id']!=original_proposal['revision_id'] and current()['total_amount']=='137.00'
                denied=accept(original_proposal,current()['row_version'])
                assert denied.status_code==409 and denied.json()['data']['error_code']=='PROPOSAL_SUPERSEDED'
            else:
                proposal=propose();assert proposal['revision_id']!=original_proposal['revision_id'] and current()['total_amount']=='137.00'
                pending=current();assert pending['status']=='awaiting_customer'
                snap=business_snapshot(c)
                replay=data(accept(original_proposal,2))
                assert replay['replayed'] and replay['original_receipt']==accepted['original_receipt'] and replay['current_state']=='awaiting_customer'
                assert business_snapshot(c)==snap
                premature=approve(proposal,pending['row_version'])
                assert premature.status_code==409 and premature.json()['data']['error_code']=='CUSTOMER_ACCEPTANCE_REQUIRED'
            if phase=='submit':
                successful_body=submit_body(quoted)
                submitted=data(client.post(api,json=successful_body,headers=submission_headers),201);request_id=submitted['request_id']
                proposal=propose()
            else:successful_body=original_body
            accepted_version=2 if phase=='submit' or (phase=='approve' and changed=='inventory') else current()['row_version']
            accepted=data(accept(proposal,accepted_version))
            approval_version=accepted['row_version']
            approved=data(approve(proposal,approval_version))
            assert approved['current_state']=='invoice_created'
            total=Decimal('137') if changed=='price' else Decimal('128')
            with Session(ctx.engine) as db:
                order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==request_id))
                invoice=db.get(Invoice,order.invoice_id)
                lines=db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id)).all()
                assert order.account_id==c.buyer_id and order.accepted_revision_id==db.scalar(select(Revision.id).where(Revision.public_id==proposal['revision_id']))
                assert invoice.total_amount==total and invoice.sales_user_id==ctx.actor
                assert len(lines)==1 and lines[0].quantity==3 and str(lines[0].product_id)==c.product_id and lines[0].model==c.standard['model'] and lines[0].color==c.standard['color']
                assert lines[0].price_per_piece==(30 if changed=='price' else 27)
                assert len(db.scalars(select(Invoice).where(Invoice.source_order_id==request_id)).all())==1
                assert len(db.scalars(select(Conversion).where(Conversion.request_id==order.id)).all())==1
                assert len(db.scalars(select(Publication).where(Publication.request_id==order.id)).all())==1
                intents=db.scalars(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)).all()
                # Portal PIs skip the creation-time receipt intent draft.
                assert intents==[]
                assert not invoice.outbound_auto_requested and invoice.sync_status=='not_synced' and invoice.xiaoman_order_id is None
            document=pdf_text(client.get(api+'/'+request_id+'/pi'));assert format(total,'.2f') in document
            # Committed original commands recover after both sources deteriorate;
            # no source reads, financial changes or additional PI are permitted.
            stock('0');price('5');before=business_snapshot(c);audit_before=audits();reads=case['probe']['selects'];price_before=dict(price_reads)
            replay=data(client.post(api,json=successful_body,headers=submission_headers))
            assert replay['replayed'] and replay['request_id']==request_id and replay['product_amount']==submitted['product_amount'] and replay['total_amount'] is None
            replay=data(accept(proposal,accepted_version));assert replay['replayed'] and replay['original_receipt']==accepted['original_receipt']
            replay=data(approve(proposal,approval_version));assert replay['replayed'] and replay['original_receipt']==approved['original_receipt']
            if phase=='submit' and changed=='price':
                conflict=client.post(api,json=original_body,headers=submission_headers)
                assert conflict.status_code==409 and conflict.json()['data']['error_code']=='IDEMPOTENCY_CONFLICT'
            assert business_snapshot(c)==before and audits()==audit_before and case['probe']['selects']==reads and price_reads==price_before
            assert pdf_text(client.get(api+'/'+request_id+'/pi'))==document
            if changed=='price' and original_proposal is not None:assert revision_graph(original_proposal['revision_id'])==old_evidence
            assert untouched_sources()==untouched_before
            report={'status':'pass','phase':phase,'sourceChange':changed,'denialCode':expected,'total':format(total,'.2f'),'inventorySelects':case['probe']['selects'],'priceSourceSelects':dict(price_reads),'scope':'Actual main/OTP/JWT/owned mirror SQL/current prices; source updates commit before each HTTP command; no physical race, production importer or browser/UI proof','originalCommandsRecovered':3,'financialGraphUnchangedOnFailureAndReplay':True,'historicalRevisionUnchanged':changed=='price' and original_proposal is not None}
        assert c.calls==[] and c.forbidden_writes==[]
    finally:importer.dispose()
    output=Path(request.config.getoption('portal_mysql_workspace')).resolve()/('source-change-'+phase+'-'+changed+'.json')
    assert not output.exists();output.write_text(json.dumps(report,indent=2),encoding='utf-8')
