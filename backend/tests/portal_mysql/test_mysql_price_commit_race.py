"""Real main/JWT price-versus-decision commit order on owned MySQL.

Eight cases cover one customer price rule, acceptance/approval, both leaders,
commit/rollback. Setup uses actual services and controlled upstream data.
No dependency override, provider writes, full migration or other price APIs.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from queue import Queue
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.invoice import price_authority
from app.invoice.models import CustomerPriceRule, Invoice
from app.portal import approval_service, order_service, proposal_decisions, proposal_service, router
from app.portal.models import AuthorityBarrier, CustomerAccess, OrderRequest, Revision
from app.portal.schemas import AcceptInput, ProposalInput
from app.receipt.models import ReceiptIntent
from test_mysql_price_authority import MODELS, login, price_app, snapshot  # noqa: F401
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_services import assert_one_pi


def setup_order(c, phase):
    ctx=c.ctx
    with Session(ctx.engine) as db:
        submitted=order_service.submit(db,ctx.token,ctx.csrf,ctx.key,ctx.body);db.commit()
        body=ProposalInput.model_validate({**ctx.quote_body.model_dump(mode='json'),
            'fees':{'shipping_amount':'45.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
            'payment_terms':'prepaid','valid_for_hours':24,'reason':'Owned confirmed freight'})
        proposal=proposal_service.create(db,ctx.actor,submitted['request_id'],1,body);db.commit()
        revision=proposal['original_receipt']
        if phase=='approve':
            proposal_decisions.decide(db,ctx.token,ctx.csrf,submitted['request_id'],revision['revision_id'],2,
                AcceptInput(proposal_hash=revision['content_hash']),accept=True);db.commit()
        order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==submitted['request_id']))
        target=db.scalar(select(Revision).where(Revision.public_id==revision['revision_id']))
        access=db.get(CustomerAccess,ctx.access_id)
        rule=db.scalar(select(CustomerPriceRule).where(CustomerPriceRule.customer_id==access.okki_company_id))
        return {'request':order.public_id,'order_id':order.id,'revision':target.public_id,'revision_id':target.id,
                'hash':target.content_hash,'rule':rule.id,'customer':access.okki_company_id,
                'authority_code':db.scalar(select(AuthorityBarrier.code).where(AuthorityBarrier.code=='authority'))}


def rows_by_id(model,rows):
    index=list(model.__table__.columns.keys()).index('id')
    return {row[index]:dict(zip(model.__table__.columns.keys(),row)) for row in rows}


def wait_exact_lock(engine,holder,waiter,authority_code):
    """Observe both actual physical connections and the exact PRIMARY record."""
    deadline=monotonic()+5
    while monotonic()<deadline:
        with engine.connect() as observer:
            rows=observer.execute(text('''SELECT r.OBJECT_NAME,r.INDEX_NAME,r.LOCK_TYPE,r.LOCK_DATA,
                b.OBJECT_NAME,b.INDEX_NAME,b.LOCK_TYPE,b.LOCK_DATA
                FROM performance_schema.data_lock_waits w
                JOIN performance_schema.threads rt ON rt.THREAD_ID=w.REQUESTING_THREAD_ID
                JOIN performance_schema.threads bt ON bt.THREAD_ID=w.BLOCKING_THREAD_ID
                JOIN performance_schema.data_locks r ON r.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID
                    AND r.ENGINE=w.ENGINE
                JOIN performance_schema.data_locks b ON b.ENGINE_LOCK_ID=w.BLOCKING_ENGINE_LOCK_ID
                    AND b.ENGINE=w.ENGINE
                WHERE rt.PROCESSLIST_ID=:waiter AND bt.PROCESSLIST_ID=:holder'''),
                {'waiter':waiter,'holder':holder}).all()
        expected=('ark_order_portal_auth_barriers','PRIMARY','RECORD',authority_code)
        def exact(record):return tuple(record[:3])+(str(record[3]).strip("'"),)==expected
        if any(exact(row[:4]) and exact(row[4:]) for row in rows):return
        sleep(.02)
    pytest.fail('Exact owned authority record wait was not observed')


class CommitGate:
    def __init__(self,engine,leader,finalize):
        self.engine=engine;self.leader=leader;self.finalize=finalize
        self.holders=Queue();self.waiters=Queue();self.release=Event()
        self.gated=False;self.flush_complete=False;self.rollback_ids=set();self.commit_ids=set()

    def after_begin(self,session,transaction,connection):
        if transaction.parent is None:
            tag=session.info.get('owned_price_race_kind')
            if tag:connection.info['owned_price_race_kind']=tag
            else:connection.info.pop('owned_price_race_kind',None)

    def before_commit(self,session):
        if session.info.get('owned_price_race_kind')!=self.leader or session.get_nested_transaction() is not None or self.gated:return
        self.gated=True
        session.flush()  # Hold the fully flushed graph, before its root commit.
        connection=session.connection()
        self.flush_complete=True
        self.holders.put(connection.connection.driver_connection.thread_id())
        if not self.release.wait(12):raise AssertionError('Owned commit gate was not released')
        if self.finalize=='rollback':raise HTTPException(409,'Owned commit aborted')

    def before_sql(self,connection,cursor,statement,parameters,context,executemany):
        if (connection.info.get('owned_price_race_kind')!=self.leader
            and connection.info.get('owned_price_race_kind') in {'price','decision'}
            and 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper()):
            self.waiters.put(connection.connection.driver_connection.thread_id())

    def rolled_back(self,connection):self.rollback_ids.add(connection.connection.driver_connection.thread_id())
    def committed(self,connection):self.commit_ids.add(connection.connection.driver_connection.thread_id())

    def install(self):
        for target,name,fn in self.listeners():event.listen(target,name,fn)

    def listeners(self):return ((Session,'after_begin',self.after_begin),(Session,'before_commit',self.before_commit),
        (self.engine,'before_cursor_execute',self.before_sql),(self.engine,'rollback',self.rolled_back),
        (self.engine,'commit',self.committed))

    def remove(self):
        for target,name,fn in self.listeners():event.remove(target,name,fn)


def assert_graph(c,target,before,after,phase,decision_committed,price_committed,failed_approval):
    """All columns of old rows stay fixed, except explicit lifecycle fields."""
    for index,model in enumerate(MODELS):
        old=rows_by_id(model,before[index]);new=rows_by_id(model,after[index])
        assert old.keys()<=new.keys()
        for identity,original in old.items():
            allowed=set()
            if model is CustomerPriceRule and identity==target['rule'] and price_committed:
                allowed={'adjust_value','customer_name','remark','updated_at','updated_by'}
            if model is OrderRequest and identity==target['order_id'] and decision_committed:
                allowed={'status','row_version','updated_at','accepted_revision_id'} if phase=='accept' else {
                    'status','row_version','updated_at','invoice_id'}
            if model is Revision and identity==target['revision_id'] and phase=='accept' and decision_committed:
                allowed={'customer_accepted_by','customer_accepted_at','updated_at'}
            changed=[key for key,value in original.items() if key not in allowed and new[identity][key]!=value]
            if changed:c.race_evidence['unexpected_old_row_fields']={'model':model.__name__,'fields':changed}
            assert not changed
        additions=set(new)-set(old)
        # Only the target decision's graph/event rows may be added.
        expected=0
        if decision_committed:
            if model.__name__ in {'CommandReceipt','AuditEvent','OutboxEvent'}:expected=1
            if phase=='approve' and model.__name__ in {'Invoice','InvoiceItem','Conversion','Publication','PiAmendment'}:expected=1
        if model.__name__=='AuditEvent' and failed_approval:expected+=1
        assert len(additions)==expected
        for identity in additions:
            row=new[identity]
            if model.__name__=='AuditEvent':
                assert row['object_public_id']==target['request']
                expected_action='order.accepted' if phase=='accept' else 'order.invoice_created'
                assert row['action'] in ({'order.approval_failed'} if failed_approval else {expected_action})
            if model.__name__=='CommandReceipt':assert row['object_public_id']==target['request'] and row['action']==phase
            if model.__name__=='OutboxEvent':assert row['aggregate_public_id']==target['request'] and row['event_type']==('order_accepted' if phase=='accept' else 'order_invoice_created')
    with Session(c.ctx.engine) as db:
        rule=db.get(CustomerPriceRule,target['rule'])
        assert rule.adjust_value==Decimal('-5' if price_committed else '-10')
        if price_committed:assert rule.updated_by==c.ctx.actor
        order=db.get(OrderRequest,target['order_id']);revision=db.get(Revision,target['revision_id'])
        assert revision.content_hash==target['hash'] and revision.total_amount==Decimal('128.00')
        assert order.status==('ready_for_review' if phase=='accept' else 'invoice_created') if decision_committed else order.status==('awaiting_customer' if phase=='accept' else 'ready_for_review')
        assert order.row_version==(3 if phase=='accept' else 4) if decision_committed else order.row_version==(2 if phase=='accept' else 3)
        assert order.accepted_revision_id==(target['revision_id'] if phase=='approve' or decision_committed else None)
        if phase=='accept':
            assert revision.customer_accepted_by==(c.ctx.account_id if decision_committed else None)
            assert (revision.customer_accepted_at is not None)==decision_committed
        if phase=='approve' and decision_committed:
            invoice=db.get(Invoice,order.invoice_id)
            assert invoice.total_amount==Decimal('128.00') and invoice.sales_user_id==c.ctx.actor
            # Portal PIs skip the creation-time receipt intent draft.
            assert db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id)) is None
        else:assert order.invoice_id is None
    if phase=='approve' and decision_committed:assert_one_pi(c.ctx,target['request'])
    assert c.calls==[]


@pytest.mark.parametrize('phase',['accept','approve'])
@pytest.mark.parametrize('leader',['price','decision'])
@pytest.mark.parametrize('finalize',['commit','rollback'])
def test_customer_rule_and_real_http_decision_obey_commit_order(price_app,monkeypatch,request,phase,leader,finalize):
    c=price_app;target=setup_order(c,phase);gate=CommitGate(c.ctx.engine,leader,finalize)
    c.race_evidence={'phase':phase,'leader':leader,'finalize':finalize,'exact_authority_lock_observed':False,
                     'fully_flushed_uncommitted_snapshot_unchanged':False,'all_graph_assertions_passed':False}
    request.node.user_properties.append(('owned_price_race',c.race_evidence))
    original_price=price_authority.begin_write
    def price(db,*args,**kwargs):
        db.info['owned_price_race_kind']='price';return original_price(db,*args,**kwargs)
    monkeypatch.setattr(price_authority,'begin_write',price)
    decision_module=proposal_decisions if phase=='accept' else approval_service
    decision_name='decide' if phase=='accept' else 'execute'
    original_decision=getattr(decision_module,decision_name)
    def decision(db,*args,**kwargs):
        db.info['owned_price_race_kind']='decision';return original_decision(db,*args,**kwargs)
    monkeypatch.setattr(decision_module,decision_name,decision)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        client.cookies.set(router.cookie_name('session'),c.ctx.token,domain='orders.example.test',path='/')
        def call(kind):
            if kind=='price':return client.post('/api/invoice/price/customer-rules',headers=owner,json={
                'customer_id':target['customer'],'customer_name':'Owned buyer','adjust_type':'percent',
                'adjust_value':'-5','enabled':True,'remark':'Owned concurrent price'})
            if phase=='accept':return client.post('/api/portal/v1/orders/'+target['request']+'/proposals/'+target['revision']+'/accept',
                headers={'X-Portal-CSRF':c.ctx.csrf,'If-Match':'"2"'},json={'proposal_hash':target['hash']})
            return client.post('/api/portal/admin/v1/orders/'+target['request']+'/approve',
                headers={**owner,'If-Match':'"3"'},json={'accepted_revision_id':target['revision']})
        before=snapshot(c);gate.install()
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(call,leader)
                try:
                    holder=gate.holders.get(timeout=6)
                    second=pool.submit(call,'decision' if leader=='price' else 'price')
                    waiter=gate.waiters.get(timeout=4)
                    assert holder!=waiter and gate.flush_complete
                    wait_exact_lock(c.ctx.engine,holder,waiter,target['authority_code'])
                    c.race_evidence['exact_authority_lock_observed']=True
                    assert not first.done() and not second.done()
                    assert snapshot(c)==before  # Fully flushed leader graph is still uncommitted.
                    c.race_evidence['fully_flushed_uncommitted_snapshot_unchanged']=True
                finally:gate.release.set()
                first_response=first.result(timeout=8);second_response=second.result(timeout=8)
        finally:gate.release.set();gate.remove()
        c.race_evidence.update(first_http_status=first_response.status_code,second_http_status=second_response.status_code,
            owned_abort_body_matches=first_response.json()=={'detail':'Owned commit aborted'},
            leader_root_rollback_observed=holder in gate.rollback_ids,leader_root_commit_observed=holder in gate.commit_ids)
        if finalize=='rollback':
            assert first_response.status_code==409
            if leader=='decision' and phase=='approve':
                # AdminRoute deliberately localizes any HTTPException to its
                # authentication envelope; the actual rollback event proves abort.
                assert first_response.json()['code']==409 and first_response.json()['data']['error_code']=='AUTH_REQUIRED'
                assert first_response.headers['Cache-Control']=='private, no-store'
            else:assert first_response.json()=={'detail':'Owned commit aborted'}
            assert holder in gate.rollback_ids and holder not in gate.commit_ids
        else:
            assert first_response.status_code==200 and first_response.json()['code']==200
            assert holder in gate.commit_ids
        decision_committed=(leader=='decision' and finalize=='commit') or (leader=='price' and finalize=='rollback')
        price_committed=(leader=='price' and finalize=='commit') or leader=='decision'
        if leader=='price' and finalize=='commit':
            assert second_response.status_code==409 and second_response.json()['data']['error_code']=='PROPOSAL_CHANGED'
        else:assert second_response.status_code==200 and second_response.json()['code']==200
        after=snapshot(c)
        assert_graph(c,target,before,after,phase,decision_committed,price_committed,
                     phase=='approve' and leader=='price' and finalize=='commit')
        if leader=='decision' and finalize=='rollback':
            # A later retry revalidates current pricing, without reviving aborted writes.
            retry=call('decision');assert retry.status_code==409 and retry.json()['data']['error_code']=='PROPOSAL_CHANGED'
            assert_graph(c,target,after,snapshot(c),phase,False,True,phase=='approve')
        c.race_evidence['all_graph_assertions_passed']=True
