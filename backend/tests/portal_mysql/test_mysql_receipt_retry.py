"""Actual receipt retry current permissions/financial state; synthetic fee provider."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import queue
import threading
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.models import ArkUser, ArkRole
from app.invoice.models import Invoice
from app.invoice import okki_client
from app.invoice.settlement_models import SettlementApplication, ShipmentSettlement
from app.portal import authority as portal_authority
from app.receipt import remote
from app.receipt.remote import receipt_info as actual_receipt_info
from app.receipt.models import Receipt, ReceiptLog
from test_mysql_full_application import assembled, boot  # noqa: F401
from test_mysql_receipt_authority import receipt_app, login, change_user  # noqa: F401
from test_mysql_receipt_reads import read_app, read_snapshot as base_snapshot  # noqa: F401
from test_mysql_concurrency import wait_for_lock


@pytest.fixture
def retry_app(read_app,monkeypatch):
    c=read_app;c.fee_io=[]
    metadata=MetaData()
    for model in (SettlementApplication,ShipmentSettlement):
        Table(model.__tablename__,metadata,*(Column(column.name,column.type,
            primary_key=column.primary_key,nullable=False if column.primary_key else True)
            for column in model.__table__.columns))
    metadata.create_all(c.ctx.engine)
    with Session(c.ctx.engine) as db:
        for identity in c.receipts.values():db.get(Receipt,identity).sync_status='failed'
        db.commit()
    def rows(db,order):c.fee_io.append('rows');return []
    def detail(*args,**kwargs):pytest.fail('No remote details in empty synthetic fee snapshot')
    monkeypatch.setattr(remote,'order_receipts',rows)
    monkeypatch.setattr(remote,'receipt_info',detail)
    return c


def read_snapshot(c):
    base=base_snapshot(c)
    with Session(c.ctx.engine) as db:
        return base+tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
            for model in (SettlementApplication,ShipmentSettlement))


def path(c,label='victim'):return '/api/receipts/'+str(c.receipts[label])+'/retry'


def set_auto(c,amount='10.00'):
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim']);row.source='auto';row.amount=Decimal(amount)
        db.get(Invoice,c.invoice_id).surcharge_amount=Decimal('16.00');db.commit()


@pytest.mark.parametrize('revoke',['disabled','roles','write'])
def test_retry_actual_revocation_rejects_old_jwt(retry_app,revoke):
    c=retry_app
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        body={'is_active':False} if revoke=='disabled' else {'role_ids':[]} if revoke=='roles' else {'role_ids':[c.roles['read']]}
        change_user(client,c,root,body);before=read_snapshot(c)
        denied=client.post(path(c),headers=owner)
        assert denied.status_code==403,denied.text
        assert read_snapshot(c)==before and c.fee_io==[] and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':[c.roles['write']]})
        response=client.post(path(c),headers=owner);assert response.status_code==200,response.text
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,c.receipts['victim']);assert row.sync_status=='pending' and row.version==2
            assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action=='retry')).all())==1
        before=read_snapshot(c)
        assert client.post(path(c),headers=owner).status_code==409
        assert read_snapshot(c)==before and c.fee_io==[]


@pytest.mark.parametrize('global_role',['all','super_admin'])
def test_retry_current_scope_removes_old_global_flags(retry_app,global_role):
    c=retry_app
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as db:role=db.scalar(select(ArkRole).where(ArkRole.name=='super_admin'))
        change_user(client,c,root,{'role_ids':[role.id if global_role=='super_admin' else c.roles['all']]})
        owner=login(client,c,c.owner_name)
        change_user(client,c,root,{'role_ids':[c.roles['write'],c.roles['invoice:read_all']]})
        before=read_snapshot(c)
        response=client.post(path(c,'foreign'),headers=owner);assert response.status_code==404,response.text
        assert read_snapshot(c)==before and c.fee_io==[]
        assert client.post(path(c),headers=owner).status_code==200


def test_retry_old_token_uses_current_new_action(retry_app):
    c=retry_app
    with c.app.client() as client:
        root=login(client,c,c.root_name);change_user(client,c,root,{'role_ids':[c.roles['read']]})
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        assert client.post(path(c),headers=owner).status_code==403
        assert read_snapshot(c)==before
        change_user(client,c,root,{'role_ids':[c.roles['write']]})
        response=client.post(path(c),headers=owner);assert response.status_code==200,response.text
        assert c.fee_io==[] and c.calls==[]


@pytest.mark.parametrize('state',[{'sync_status':'pending'},{'sync_status':'uncertain'},
    {'sync_status':'syncing'},{'sync_status':'synced'},{'xiaoman_receipt_id':'1234'},{'status':'voided'}])
def test_retry_keeps_original_no_blind_resend_guards(retry_app,state):
    c=retry_app;set_auto(c)
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim'])
        for name,value in state.items():setattr(row,name,value)
        db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        response=client.post(path(c),headers=owner);assert response.status_code==409,response.text
        assert read_snapshot(c)==before and c.fee_io==[] and c.calls==[]


@pytest.mark.parametrize('amount,charge',[('10.00','1.25'),('118.00','16.00')])
def test_retry_auto_fee_exact_and_once(retry_app,amount,charge):
    c=retry_app;set_auto(c,amount)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name)
        response=client.post(path(c),headers=owner);assert response.status_code==200,response.text
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,c.receipts['victim'])
            assert row.bank_charge==Decimal(charge) and row.amount==Decimal(amount)
            assert row.sync_status=='pending' and row.version==2
            for action in ('fee_allocated','retry'):
                assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action==action)).all())==1
        before=read_snapshot(c)
        assert client.post(path(c),headers=owner).status_code==409
        assert read_snapshot(c)==before and c.fee_io==['rows'] and c.calls==[]


@pytest.mark.parametrize('change',['disabled','write','owner','remote','amount','sibling_uncertain'])
def test_retry_fee_io_reauthorizes_and_rebinds(retry_app,change,monkeypatch):
    c=retry_app;set_auto(c);ready=threading.Event();release=threading.Event()
    original=remote.order_receipts
    def gated(*args,**kwargs):ready.set();assert release.wait(10);return original(*args,**kwargs)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        monkeypatch.setattr(remote,'order_receipts',gated)
        with ThreadPoolExecutor(max_workers=2) as pool:
            response=pool.submit(client.post,path(c),headers=owner)
            try:
                assert ready.wait(5)
                if change in ('disabled','write'):
                    revoked=pool.submit(client.put,'/api/auth/users/'+str(c.ctx.actor),headers=root,
                        json={'is_active':False} if change=='disabled' else {'role_ids':[c.roles['read']]})
                    assert revoked.result(timeout=5).status_code==200
                else:
                    def mutate():
                        with Session(c.ctx.engine) as db:
                            invoice=db.get(Invoice,c.invoice_id);row=db.get(Receipt,c.receipts['victim'])
                            if change=='owner':invoice.sales_user_id=c.other_id
                            elif change=='remote':invoice.xiaoman_order_id='987654321'
                            elif change=='amount':row.amount=Decimal('11.00')
                            else:db.get(Receipt,c.receipts['positive']).sync_status='uncertain'
                            db.commit()
                    future=pool.submit(mutate);future.result(timeout=5)
                assert not response.done();before=read_snapshot(c)
            finally:release.set()
            result=response.result(timeout=5)
        assert result.status_code==(403 if change in ('disabled','write') else 404 if change=='owner' else 409),result.text
        assert read_snapshot(c)==before and c.calls==[]


def test_retry_final_fee_rows_are_current_after_io(retry_app,monkeypatch):
    c=retry_app;set_auto(c);ready=threading.Event();release=threading.Event();started=queue.Queue()
    original=remote.order_receipts
    def gated(*args,**kwargs):ready.set();assert release.wait(10);return original(*args,**kwargs)
    def observe(connection,cursor,statement,parameters,context,executemany):
        if 'FROM ark_invoices' in statement and 'FOR UPDATE' in statement.upper():
            started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);monkeypatch.setattr(remote,'order_receipts',gated)
        with ThreadPoolExecutor(max_workers=1) as pool:
            response=pool.submit(client.post,path(c),headers=owner)
            with Session(c.ctx.engine) as other:
                try:
                    assert ready.wait(5)
                    other.scalar(select(Invoice).where(Invoice.id==c.invoice_id).with_for_update())
                    sibling=other.get(Receipt,c.receipts['positive'])
                    sibling.bank_charge=Decimal('15.99');sibling.amount=Decimal('20.00');other.flush()
                    event.listen(c.ctx.engine,'before_cursor_execute',observe);release.set()
                    wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not response.done()
                    other.commit()
                    result=response.result(timeout=5);assert result.status_code==200,result.text
                finally:
                    release.set();other.rollback()
                    if event.contains(c.ctx.engine,'before_cursor_execute',observe):event.remove(c.ctx.engine,'before_cursor_execute',observe)
        with Session(c.ctx.engine) as db:
            assert db.get(Receipt,c.receipts['victim']).bank_charge==Decimal('0.01')
        assert c.calls==[]


@pytest.mark.parametrize('commit',[True,False])
@pytest.mark.parametrize('enabled',[True,False])
def test_retry_authority_and_original_commit_rollback(retry_app,commit,enabled,monkeypatch):
    from app.receipt import retry_service
    c=retry_app;started=queue.Queue();c.app.settings.PORTAL_ENABLED=enabled
    monkeypatch.setattr(portal_authority,'get_settings',lambda:c.app.settings)
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        with Session(c.ctx.engine) as first:
            row,_=retry_service.retry(first,c.receipts['victim'],{'sub':str(c.ctx.actor)})
            first.flush()
            def observe(connection,cursor,statement,parameters,context,executemany):
                if 'ark_order_portal_auth_barriers' in statement and 'FOR UPDATE' in statement.upper():
                    started.put(connection.scalar(text('SELECT CONNECTION_ID()')))
            event.listen(c.ctx.engine,'before_cursor_execute',observe)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(client.put,'/api/auth/users/'+str(c.ctx.actor),headers=root,json={'is_active':False})
                try:
                    wait_for_lock(c.ctx.engine,started.get(timeout=5));assert not future.done()
                    if commit:first.commit()
                    else:first.rollback()
                    assert future.result(timeout=5).status_code==200
                finally:first.rollback();event.remove(c.ctx.engine,'before_cursor_execute',observe)
            with Session(c.ctx.engine) as db:
                assert db.get(Receipt,c.receipts['victim']).sync_status==('pending' if commit else 'failed')
                assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==c.receipts['victim'],ReceiptLog.action=='retry')).all())==int(commit)
                assert not db.get(ArkUser,c.ctx.actor).is_active


def test_retry_mixed_batch_hidden_and_no_partial_change(retry_app):
    c=retry_app
    with Session(c.ctx.engine) as db:db.get(Receipt,c.receipts['foreign']).batch_id=c.batch_id;db.commit()
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        response=client.post(path(c,'positive'),headers=owner);assert response.status_code==404,response.text
        assert read_snapshot(c)==before and c.fee_io==[]


@pytest.mark.parametrize('change',['paused','released','batch_foreign'])
def test_retry_current_batch_and_settlement_after_fee_io(retry_app,change,monkeypatch):
    c=retry_app;set_auto(c);ready=threading.Event();release=threading.Event()
    with Session(c.ctx.engine) as db:
        row=db.get(Receipt,c.receipts['victim']);row.batch_id=c.batch_id;row.purpose='presale_goods'
        settlement=ShipmentSettlement(invoice_id=c.invoice_id,sequence=1,settlement_no=uuid4().hex,
            state='awaiting_payment',is_final=0,quote={},quote_hash='a'*64,
            request_key=uuid4().hex,request_hash='b'*64,created_by=c.ctx.actor)
        db.add(settlement);db.flush();settlement_id=settlement.id
        app=SettlementApplication(settlement_id=settlement.id,receipt_id=row.id,component='goods',amount=10,status='reserved')
        db.add(app);db.flush();application_id=app.id;db.commit()
    original=remote.order_receipts
    def gated(*args,**kwargs):ready.set();assert release.wait(10);return original(*args,**kwargs)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);monkeypatch.setattr(remote,'order_receipts',gated)
        with ThreadPoolExecutor(max_workers=2) as pool:
            response=pool.submit(client.post,path(c),headers=owner)
            try:
                assert ready.wait(5)
                def mutate():
                    with Session(c.ctx.engine) as db:
                        if change=='paused':db.get(ShipmentSettlement,settlement_id).state='paused'
                        elif change=='released':db.get(SettlementApplication,application_id).status='released'
                        else:db.get(Receipt,c.receipts['foreign']).batch_id=c.batch_id
                        db.commit()
                pool.submit(mutate).result(timeout=5);before=read_snapshot(c)
            finally:release.set()
            result=response.result(timeout=5)
        assert result.status_code==(404 if change=='batch_foreign' else 409),result.text
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('failure',['invalid','provider'])
def test_retry_fee_failure_does_not_use_empty_evidence(retry_app,failure,monkeypatch):
    c=retry_app;set_auto(c);hits=[]
    def broken(*args,**kwargs):
        hits.append(failure)
        if failure=='invalid':raise ValueError('private-evidence-details')
        raise okki_client.OkkiApiError('private-provider-details')
    monkeypatch.setattr(remote,'order_receipts',broken)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        result=client.post(path(c),headers=owner)
        assert hits==[failure] and result.status_code==503,result.text
        assert 'private-' not in result.text and result.headers['cache-control']=='private, no-store'
        assert read_snapshot(c)==before and c.calls==[]


def test_retry_two_fee_commands_apply_only_once(retry_app,monkeypatch):
    c=retry_app;set_auto(c);ready=queue.Queue();release=threading.Event()
    original=remote.order_receipts
    def gated(*args,**kwargs):ready.put(True);assert release.wait(10);return original(*args,**kwargs)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);monkeypatch.setattr(remote,'order_receipts',gated)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(client.post,path(c),headers=owner);second=pool.submit(client.post,path(c),headers=owner)
            try:assert ready.get(timeout=5) and ready.get(timeout=5)
            finally:release.set()
            responses=[first.result(timeout=5),second.result(timeout=5)]
        assert sorted(x.status_code for x in responses)==[200,409],[x.text for x in responses]
        with Session(c.ctx.engine) as db:
            row=db.get(Receipt,c.receipts['victim']);assert row.version==2 and row.bank_charge==Decimal('1.25')
            for action in ('retry','fee_allocated'):
                assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action==action)).all())==1
        assert c.calls==[]


@pytest.mark.parametrize('shape',['not_list','not_dict','missing_id','bad_detail'])
def test_retry_bad_fee_shapes_are_safe(retry_app,shape,monkeypatch):
    c=retry_app;set_auto(c);hits=[]
    def rows(*args,**kwargs):
        hits.append(shape)
        return None if shape=='not_list' else [None] if shape=='not_dict' else [{}] if shape=='missing_id' else [{'cash_collection_id':'987','amount':'10'}]
    monkeypatch.setattr(remote,'order_receipts',rows)
    monkeypatch.setattr(remote,'receipt_info',lambda *args:None)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        result=client.post(path(c),headers=owner)
        assert hits==[shape] and result.status_code==503,result.text
        assert result.headers['cache-control']=='private, no-store'
        assert read_snapshot(c)==before and c.calls==[]


@pytest.mark.parametrize('stage',[1,2,3])
@pytest.mark.parametrize('timing',['before_commit','after_commit'])
def test_retry_phase_commit_failures_preserve_original_facts(retry_app,stage,timing,monkeypatch):
    c=retry_app;set_auto(c);hits=[];metadata=MetaData()
    token=Table('owned_retry_metadata',metadata,Column('id',Integer,primary_key=True),Column('value',String(32)))
    metadata.create_all(c.ctx.engine)
    with c.ctx.engine.begin() as connection:
        connection.execute(token.delete());connection.execute(token.insert().values(id=1,value='original'))
    original=remote.order_receipts
    def rows(db,*args):
        db.execute(token.update().where(token.c.id==1).values(value='refreshed'))
        return original(db,*args)
    monkeypatch.setattr(remote,'order_receipts',rows)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        def fail(db):
            if any(isinstance(row,Receipt) and inspect(row).identity==(c.receipts['victim'],) for row in db.identity_map.values()):
                db.info['owned_retry_session']=True
            # describe() returns scalars; weak identity-map references may disappear before final commit.
            if db.info.get('owned_retry_session'):
                count=db.info.get('owned_retry_commit',0)+1;db.info['owned_retry_commit']=count
                if count==stage and not hits:
                    hits.append((stage,timing));raise OperationalError('private-commit-query',{},Exception('private-driver-ack'))
        event.listen(Session,timing,fail)
        try:result=client.post(path(c),headers=owner)
        finally:event.remove(Session,timing,fail)
        assert hits==[(stage,timing)] and result.status_code==503,result.text
        assert 'private-' not in result.text and result.headers['cache-control']=='private, no-store'
        with c.ctx.engine.connect() as connection:
            value=connection.scalar(select(token.c.value).where(token.c.id==1))
        assert value==('original' if stage==1 or (stage==2 and timing=='before_commit') else 'refreshed')
        committed=stage==3 and timing=='after_commit'
        if not committed:assert read_snapshot(c)==before
        else:
            with Session(c.ctx.engine) as db:
                row=db.get(Receipt,c.receipts['victim']);assert row.sync_status=='pending' and row.bank_charge==Decimal('1.25') and row.version==2
                for action in ('retry','fee_allocated'):
                    assert len(db.scalars(select(ReceiptLog).where(ReceiptLog.receipt_id==row.id,ReceiptLog.action==action)).all())==1
        retry=client.post(path(c),headers=owner)
        assert retry.status_code==(409 if committed else 200),retry.text
        if committed:assert c.fee_io==['rows']
        assert c.calls==[]


@pytest.mark.parametrize('payload',[None,[],"invalid"])
def test_retry_actual_detail_parser_rejects_bad_shape(retry_app,payload,monkeypatch):
    c=retry_app;set_auto(c);hits=[]
    monkeypatch.setattr(remote,'order_receipts',lambda *args:[{'cash_collection_id':'987','amount':'10'}])
    monkeypatch.setattr(remote,'receipt_info',actual_receipt_info)
    def read(db,path,params):
        hits.append((path,params));return payload
    monkeypatch.setattr(remote,'read',read)
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=read_snapshot(c)
        result=client.post(path(c),headers=owner)
        assert hits==[('/v1/invoices/receipt/info',{'cash_collection_id':'987'})]
        assert result.status_code==503,result.text
        assert result.headers['cache-control']=='private, no-store'
        assert read_snapshot(c)==before and c.calls==[]
