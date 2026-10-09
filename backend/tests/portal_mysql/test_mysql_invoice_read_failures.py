"""Fail-closed current invoice read authority before business queries."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.auth.models import ArkRole
from app.invoice import read_authority,service
from test_mysql_full_application import assembled,boot,owner
from test_mysql_receipt_authority import receipt_app,login,change_user,snapshot
from test_mysql_invoice_current_reads import read_roles

@pytest.mark.parametrize('sink',['normal','logger','stdout','both'])
def test_current_read_database_failure_is_private_and_precedes_invoice_queries(receipt_app,monkeypatch,sink):
    c=receipt_app;roles=read_roles(c);business=[];auth=[];diagnostics=[]
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        token=login(client,c,c.owner_name)
        assert client.get('/api/invoice/invoices',headers=token).status_code==200
        before=snapshot(c)
        def unavailable(db,actor):
            auth.append(True);raise OperationalError('owned authorization failure',{},Exception('PRIVATE_AUTHORIZATION_CONTEXT'))
        def forbidden(*args,**kwargs):business.append(True);raise AssertionError('Business query before current authorization')
        def broken(*args,**kwargs):diagnostics.append(True);raise RuntimeError('PRIVATE_DIAGNOSTIC_CONTEXT')
        monkeypatch.setattr(read_authority,'get_live_user_authorization',unavailable)
        monkeypatch.setattr(service,'list_invoices',forbidden);monkeypatch.setattr(service,'summarize_invoices',forbidden)
        if sink in {'logger','both'}:monkeypatch.setattr(read_authority.logger,'warning',broken)
        if sink in {'stdout','both'}:monkeypatch.setattr(read_authority,'print',broken,raising=False)
        for path,params in (('/api/invoice/invoices',{}),('/api/invoice/invoices/summary',{'date_from':'2071-10-01','date_to':'2071-10-31'})):
            response=client.get(path,headers=token,params=params)
            assert response.status_code==503
            assert response.headers['Cache-Control']=='private, no-store' and response.headers['Pragma']=='no-cache'
            assert 'PRIVATE_' not in response.text
        assert len(auth)==2 and business==[] and snapshot(c)==before and c.calls==[]
        assert len(diagnostics)=={'normal':0,'logger':2,'stdout':2,'both':4}[sink]

@pytest.mark.parametrize('state',['transaction','pending'])
def test_current_read_refuses_borrowed_or_pending_session_before_authority(receipt_app,monkeypatch,state):
    c=receipt_app;called=[];before=snapshot(c)
    def forbidden(*args,**kwargs):called.append(True);raise AssertionError('Borrowed transaction accepted')
    monkeypatch.setattr(read_authority,'get_live_user_authorization',forbidden)
    with Session(c.ctx.engine) as db:
        if state=='transaction':db.execute(select(ArkRole.id).limit(1))
        else:db.add(ArkRole(name='uncommitted-read-probe',label='Uncommitted'))
        with pytest.raises(HTTPException) as error:read_authority.current_user(db,{'sub':str(c.ctx.actor)})
        assert error.value.status_code==409 and error.value.headers['Cache-Control']=='private, no-store'
        db.rollback()
    assert called==[] and snapshot(c)==before and c.calls==[]

@pytest.mark.parametrize('identity',[None,'not-an-id','0','-1'])
def test_current_read_rejects_invalid_claim_identity_before_database(receipt_app,monkeypatch,identity):
    c=receipt_app;called=[];before=snapshot(c)
    def forbidden(*args,**kwargs):called.append(True);raise AssertionError('Invalid identity reached authorization DB')
    monkeypatch.setattr(read_authority,'get_live_user_authorization',forbidden)
    with Session(c.ctx.engine) as db:
        with pytest.raises(HTTPException) as error:read_authority.current_user(db,{'sub':identity,'roles':['super_admin'],'permissions':['invoice:read_all']})
        assert error.value.status_code==403 and error.value.headers['Cache-Control']=='private, no-store'
    assert called==[] and snapshot(c)==before and c.calls==[]
