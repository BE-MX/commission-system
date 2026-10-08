"""Actual registered invoice/JWT HTTP and MySQL linked phase authorization.

The shared editor overrides only its DB Session dependency. Provider POST,
GET evidence and downstream outbound executor are explicit substitutes.
"""
import asyncio
from copy import deepcopy
from datetime import timedelta
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest
import httpx
from sqlalchemy import select,text,event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser,ArkUserRole
from app.auth import admin_router as employee_admin
from app.core.time import beijing_now
from app.invoice import edit_authority, linked_execution, linked_sync_service as linked
from app.invoice import order_push_facts as facts, linked_outbound_service, okki_client
from app.invoice.models import InvoiceLinkedSync
from app.portal.authority import get_settings,lock_authority
from app.receipt import remote
from app.receipt.models import ReceiptAttachment,ReceiptIntent
from test_mysql_order_push_execution import setup_push,audit


def prepared(e,monkeypatch,tmp_path):
    e.app.include_router(employee_admin.router,prefix='/api/auth')
    c=setup_push(e,monkeypatch,tmp_path,editing=True)
    route,body,method=e.prepare('linked')
    with Session(e.ctx.engine) as db:
        lock_authority(db);invoice=edit_authority.lock_document(db,e.invoice_id)
        invoice.xiaoman_order_id=c.target
        intent=db.scalar(select(ReceiptIntent).where(ReceiptIntent.invoice_id==invoice.id))
        for identity in intent.attachment_ids:db.get(ReceiptAttachment,identity).created_by=e.ctx.actor
        db.commit()
    response=asyncio.run(e.write(route,body,method));assert response.status_code==200
    identity=response.json()['data']['operation']['id']
    c.identity=identity;c.run_route=route+'/'+identity+'/run';c.get_route=route
    c.reads=[]
    def order(db,path,params=None):
        assert not db.in_transaction();c.reads.append('outbound')
        return {'order_id':c.target,'create_time':'2026-10-07 10:00:00'}
    def outbound(db,invoice,order):
        return {'status':'manual','message':'Controlled outbound documents need human review'}
    def receipt(db,invoice):
        assert not db.in_transaction();c.reads.append('receipt')
        return {'rows':[],'exchange_rate':None,'invoice_binding':remote.invoice_binding(invoice)}
    monkeypatch.setattr(remote,'read',order);monkeypatch.setattr(linked_outbound_service,'summarize',outbound)
    monkeypatch.setattr(remote,'order_snapshot',receipt)
    return c


@pytest.fixture(autouse=True)
def finite_responses(editor,request,monkeypatch):
    observations=[];request.node.user_properties.append(('owned_linked_responses',observations))
    original=editor.write
    async def observed(path,body,method,*args,**kwargs):
        response=await original(path,body,method,*args,**kwargs)
        try:payload=response.json()
        except ValueError:payload={}
        allowed={
            '关联同步授权必须从新事务开始':'entry_not_fresh',
            '关联同步阶段存在未提交事务':'phase_not_fresh',
            '该修改版本已结束或订单已变化，请核对原任务':'initial_binding',
            '原推单存在未核对执行记录，请先恢复原任务':'unresolved_push',
            '当前订单、库存或回款资料不允许推送':'order_state_reject',
            '发票未通过同步前校验':'invoice_validation',
            '产品映射、业务归属或推单设置尚未完整核对':'mapping_incomplete',
            '取证期间发票、映射或本地执行资料已变化':'push_binding_changed',
            '关联同步对应的订单版本已变化，请核对原任务':'linked_binding_changed',
            '当前账号无权核对此发票':'current_authority_denied',
        }
        observations.append({'kind':'admin' if path.startswith('/api/auth') else 'get' if method=='GET' else 'save' if path.endswith('/linked-sync') else 'run',
            'http_status':response.status_code,'fixed_detail_class':allowed.get(payload.get('detail'),'other_or_absent')})
        return response
    monkeypatch.setattr(editor,'write',observed)


def request(c,path=None,method='POST',body=None):
    return asyncio.run(c.e.write(path or c.run_route,body or {},method))


def revoke(c,kind):
    if kind=='inactive':body={'is_active':False}
    else:body={'role_ids':[]}
    result=asyncio.run(c.e.write('/api/auth/users/'+str(c.e.ctx.actor),body,'PUT',c.e.admin_token))
    assert result.status_code==200


def frozen(c):return c.e.snapshot()


@pytest.mark.parametrize('mode',['on','off'])
@pytest.mark.parametrize('change',['inactive','roles'])
def test_linked_current_run_and_expiring_get_reject_old_jwt(editor,monkeypatch,tmp_path,mode,change):
    e=editor;c=prepared(e,monkeypatch,tmp_path)
    if mode=='off':monkeypatch.setattr(get_settings(),'PORTAL_ENABLED',False)
    with Session(e.ctx.engine) as db:
        row=db.get(InvoiceLinkedSync,c.identity);row.status='running';row.run_token='owned-expired-token'
        row.lease_until=beijing_now()-timedelta(seconds=1);db.commit()
    revoke(c,change);before=frozen(c)
    for path,method in [(c.run_route,'POST'),(c.get_route,'GET')]:
        response=request(c,path,method)
        assert response.status_code==403 and response.headers['Cache-Control']=='private, no-store'
        assert frozen(c)==before and c.posts==c.tokens==c.reads==c.followups==[]


@pytest.mark.parametrize('mode',['on','off'])
def test_complete_linked_run_single_post_current_scoped_replay(editor,monkeypatch,tmp_path,mode):
    e=editor;c=prepared(e,monkeypatch,tmp_path)
    if mode=='off':monkeypatch.setattr(get_settings(),'PORTAL_ENABLED',False)
    response=request(c);assert response.status_code==200
    result=response.json()['data'];assert result['status']=='manual'
    assert result['steps']['order']['status']=='done' and result['steps']['receipt']['status']=='done'
    assert len(c.posts)==1 and c.reads==['outbound','receipt'] and c.followups==[e.invoice_id]
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id);row=db.get(InvoiceLinkedSync,c.identity)
        assert invoice.sync_status=='synced' and invoice.xiaoman_order_id==c.target and invoice.linked_sync_id is None
        assert row.status=='manual' and row.run_token is None and row.lease_until is None
        assert invoice.total_amount==128 and linked.snapshot(invoice)==row.after
    original=frozen(c);posts=len(c.posts);reads=list(c.reads)
    assert request(c).status_code==200
    assert request(c,c.get_route,'GET').status_code==200
    assert frozen(c)==original and len(c.posts)==posts and c.reads==reads
    revoke(c,'roles');after_revoke=frozen(c)
    assert request(c).status_code==403 and frozen(c)==after_revoke
    evidence=audit(e);assert [kind for kind,data in evidence].count(facts.START)==1
    assert [kind for kind,data in evidence].count(facts.FACT)==1 and [kind for kind,data in evidence].count(facts.FINISH)==1


@pytest.mark.parametrize('change',['inactive','roles'])
def test_post_acceptance_fact_survives_revocation_without_commercial_finish(editor,monkeypatch,tmp_path,change):
    e=editor;c=prepared(e,monkeypatch,tmp_path);base_post=c.post;captured={}
    def post(url,**kwargs):
        with Session(e.ctx.engine) as db:
            db.execute(text('SET SESSION innodb_lock_wait_timeout=1'));lock_authority(db)
            edit_authority.lock_document(db,e.invoice_id);db.commit()
        revoke(c,change);captured['after_revoke']=frozen(c)
        return base_post(url,**kwargs)
    monkeypatch.setattr(okki_client.httpx,'post',post)
    result=request(c);assert result.status_code==403
    assert len(c.posts)==1 and c.reads==c.followups==[]
    after=frozen(c);before=captured['after_revoke']
    # Immutable original observation + its original fact sync log may commit;
    # invoice, linked step and every other business row remain at the claim.
    assert after[0:2]==before[0:2] and after[3:12]==before[3:12] and after[13:]==before[13:]
    assert len(after[2])==len(before[2])+1 and after[2][:len(before[2])]==before[2]
    assert len(after[12])==len(before[12])+1 and after[12][:len(before[12])]==before[12]
    evidence=audit(e);assert [kind for kind,data in evidence].count(facts.START)==1
    assert [kind for kind,data in evidence].count(facts.FACT)==1 and [kind for kind,data in evidence].count(facts.FINISH)==0
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id);row=db.get(InvoiceLinkedSync,c.identity)
        assert invoice.sync_status=='sync_uncertain' and invoice.sync_attempt is not None
        assert row.status=='running' and row.steps['order']['status']=='sending'


@pytest.mark.parametrize('point',['outbound','receipt','followup'])
@pytest.mark.parametrize('change',['inactive','owner','raw_line','lease'])
def test_external_evidence_has_no_business_locks_and_final_phase_rechecks(editor,monkeypatch,tmp_path,point,change):
    e=editor;c=prepared(e,monkeypatch,tmp_path);captured={}
    from app.invoice import outbound_followup_service
    module,name=(outbound_followup_service,'safely_run') if point=='followup' else (remote,'read' if point=='outbound' else 'order_snapshot')
    original=getattr(module,name)
    def evidence(db,*args,**kwargs):
        assert not db.in_transaction()
        with Session(e.ctx.engine) as other:
            other.execute(text('SET SESSION innodb_lock_wait_timeout=1'));lock_authority(other)
            invoice=edit_authority.lock_document(other,e.invoice_id)
            if change=='owner':invoice.sales_user_id=e.ctx.admin
            elif change=='raw_line':invoice.items[0].color='changed-owned-color'
            elif change=='lease':other.get(InvoiceLinkedSync,c.identity).lease_until=beijing_now()-timedelta(seconds=1)
            other.commit()
        if change=='inactive':revoke(c,change)
        captured['after_change']=frozen(c)
        return original(db,*args,**kwargs)
    monkeypatch.setattr(module,name,evidence)
    result=request(c);assert result.status_code==({'inactive':403,'owner':404}.get(change,409))
    assert len(c.posts)==1 and c.followups==([e.invoice_id] if point=='followup' else []) and frozen(c)==captured['after_change']


def test_live_linked_runner_is_not_sent_twice(editor,monkeypatch,tmp_path):
    e=editor;c=prepared(e,monkeypatch,tmp_path);ready,release=Event(),Event();original=c.post
    def paused(url,**kwargs):
        ready.set();assert release.wait(10);return original(url,**kwargs)
    monkeypatch.setattr(okki_client.httpx,'post',paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(request,c)
        try:
            assert ready.wait(6)
            waiting=request(c);assert waiting.status_code==200 and waiting.json()['data']['status']=='running'
            assert not future.done() and c.posts==[]
        finally:release.set()
        completed=future.result(timeout=8);assert completed.status_code==200
    assert len(c.posts)==1 and c.reads==['outbound','receipt']


@pytest.mark.parametrize('outcome',['unknown','rejected'])
def test_linked_unknown_push_stays_uncertain_and_is_not_automatically_replayed(editor,monkeypatch,tmp_path,outcome):
    e=editor;c=prepared(e,monkeypatch,tmp_path)
    def post(url,**kwargs):
        c.posts.append(deepcopy(kwargs['json']))
        if outcome=='unknown':return httpx.Response(200,json={'code':200,'data':{'order_id':'wrong-original-order'}})
        return httpx.Response(400,json={'code':400,'message':'Controlled explicit rejection'})
    monkeypatch.setattr(okki_client.httpx,'post',post)
    response=request(c);assert response.status_code==200
    expected='uncertain' if outcome=='unknown' else 'failed'
    assert response.json()['data']['status']==expected
    assert len(c.posts)==1 and c.reads==c.followups==[]
    with Session(e.ctx.engine) as db:
        invoice=edit_authority.lock_document(db,e.invoice_id);row=db.get(InvoiceLinkedSync,c.identity)
        assert invoice.linked_sync_id==c.identity and row.status==expected
        assert bool(facts.unresolved(db,invoice))==(outcome=='unknown')
    if outcome=='unknown':
        before=frozen(c);assert request(c).status_code==200 and frozen(c)==before and len(c.posts)==1


def test_current_read_expires_only_linked_lease_without_sending(editor,monkeypatch,tmp_path):
    e=editor;c=prepared(e,monkeypatch,tmp_path)
    with Session(e.ctx.engine) as db:
        row=db.get(InvoiceLinkedSync,c.identity);row.status='running';row.run_token='owned-expired-token'
        row.lease_until=beijing_now()-timedelta(seconds=1);db.commit()
    before=frozen(c);result=request(c,c.get_route,'GET');assert result.status_code==200 and result.json()['data']['status']=='uncertain'
    after=frozen(c);assert before[:5]==after[:5] and before[6:]==after[6:]
    with Session(e.ctx.engine) as db:
        row=db.get(InvoiceLinkedSync,c.identity);assert row.status=='uncertain' and row.run_token=='owned-expired-token'
    assert c.posts==c.tokens==c.reads==c.followups==[]


@pytest.mark.parametrize('query',['ark_users','ark_roles','ark_permissions'])
def test_linked_initial_authority_query_unavailable_is_private_without_writes(editor,monkeypatch,tmp_path,query):
    e=editor;c=prepared(e,monkeypatch,tmp_path);before=frozen(c);hits=[]
    def fail(connection,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT') and ('FROM '+query) in statement:
            hits.append(True);raise OperationalError('Owned unavailable authority query',None,Exception('Owned query unavailable'))
    event.listen(e.ctx.engine,'before_cursor_execute',fail)
    try:response=request(c)
    finally:event.remove(e.ctx.engine,'before_cursor_execute',fail)
    assert hits==[True] and response.status_code==503 and response.headers['Cache-Control']=='private, no-store'
    assert response.json()=={'detail':'关联同步的当前授权暂不可确认，请稍后读取原任务'}
    assert frozen(c)==before and c.posts==c.tokens==c.reads==c.followups==[]
    assert request(c).status_code==200
