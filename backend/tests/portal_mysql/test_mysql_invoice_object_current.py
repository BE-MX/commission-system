"""Actual JWT/admin invoice object reads; no export/provider substitutions."""
import pytest
from sqlalchemy import Column,MetaData,Table,select
from sqlalchemy.orm import Session
from app.invoice import service,xiaoman_service,export_service
from app.invoice.models import Invoice,InvoiceSyncLog,InvoiceDelegateGrant
from test_mysql_full_application import assembled,boot,owner
from test_mysql_receipt_authority import receipt_app,login,change_user,snapshot
from test_mysql_invoice_current_reads import read_roles,assert_current_authorization

@pytest.fixture
def object_app(receipt_app,monkeypatch):
    c=receipt_app
    metadata=MetaData()
    Table(InvoiceSyncLog.__tablename__,metadata,*(Column(column.name,column.type,
        primary_key=column.primary_key,nullable=False if column.primary_key else True)
        for column in InvoiceSyncLog.__table__.columns))
    metadata.create_all(c.ctx.engine)
    with Session(c.ctx.engine) as db:
        for identity in (c.invoice_id,c.foreign_invoice_id):
            db.add(InvoiceSyncLog(invoice_id=identity,action='create',success=1,operator_id=c.ctx.actor))
        db.commit()
    c.render_calls=[]
    for module,name,kind in ((service,'serialize_detail','detail'),(xiaoman_service,'list_sync_logs','logs'),
        (export_service,'build_invoice_workbook','excel'),(export_service,'build_print_html','print'),
        (export_service,'build_invoice_pdf','pdf')):
        original=getattr(module,name)
        def observe(*args,_original=original,_kind=kind,**kwargs):
            c.render_calls.append(_kind)
            return _original(*args,**kwargs)
        monkeypatch.setattr(module,name,observe)
    return c


def log_snapshot(c):
    with Session(c.ctx.engine) as db:
        return tuple(db.execute(select(*InvoiceSyncLog.__table__.columns).order_by(InvoiceSyncLog.id)).all())

KINDS=('detail','logs','excel','print','pdf')
def path(identity,kind):
    suffix={'detail':'','logs':'/sync-logs','excel':'/export/excel','print':'/export/print','pdf':'/export/pdf'}[kind]
    return '/api/invoice/invoices/'+str(identity)+suffix

def positive(response,kind):
    assert response.status_code==200
    if kind=='logs':assert len(response.json()['data']['items'])==1
    if kind=='pdf':assert response.content.startswith(b'%PDF')
    if kind=='excel':assert response.content.startswith(b'PK')
    if kind=='print':assert 'text/html' in response.headers['content-type']

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('change',['disabled','roles','action','read_all','super_admin'])
def test_object_read_rechecks_actual_current_employee_scope(object_app,kind,change):
    c=object_app;roles=read_roles(c)
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        starting=roles['super_admin'] if change=='super_admin' else roles['global']
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],starting]})
        token=login(client,c,c.owner_name)
        initial=snapshot(c);logs_before=log_snapshot(c)
        positive(client.get(path(c.foreign_invoice_id,kind),headers=token),kind)
        assert snapshot(c)==initial and log_snapshot(c)==logs_before and c.calls==[]
        assert c.render_calls==[kind];c.render_calls.clear()
        body=({'is_active':False} if change=='disabled' else {'role_ids':[]} if change=='roles' else
              {'role_ids':[c.sales_role,c.roles['both']]} if change=='action' else
              {'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        change_user(client,c,root,body)
        assert_current_authorization(c,active=change!='disabled',read=change not in {'roles','action'},all_scope=change=='disabled')
        before=snapshot(c)
        result=client.get(path(c.foreign_invoice_id,kind),headers=token)
        assert snapshot(c)==before and log_snapshot(c)==logs_before and c.calls==[]
        assert c.render_calls==[]
        assert result.status_code==(404 if change in {'read_all','super_admin'} else 403)
        if change in {'read_all','super_admin'}:
            positive(client.get(path(c.invoice_id,kind),headers=token),kind)
            assert snapshot(c)==before and log_snapshot(c)==logs_before and c.calls==[]
            assert c.render_calls==[kind]

@pytest.mark.parametrize('kind',KINDS)
def test_object_read_accepts_current_new_grant_without_token_reissue(object_app,kind):
    c=object_app;roles=read_roles(c)
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both']]})
        token=login(client,c,c.owner_name)
        assert_current_authorization(c,read=False)
        assert client.get(path(c.invoice_id,kind),headers=token).status_code==403
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        assert c.render_calls==[]
        assert_current_authorization(c);before=snapshot(c);logs_before=log_snapshot(c)
        result=client.get(path(c.invoice_id,kind),headers=token)
        assert snapshot(c)==before and log_snapshot(c)==logs_before and c.calls==[]
        positive(result,kind)
        assert c.render_calls==[kind]

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('withdrawal',['grant','owner_disabled'])
def test_object_read_requires_current_delegation_and_active_owner(object_app,kind,withdrawal):
    c=object_app;roles=read_roles(c)
    with Session(c.ctx.engine) as db:
        foreign=db.get(Invoice,c.foreign_invoice_id);foreign.created_by=c.ctx.actor
        db.add(InvoiceDelegateGrant(delegate_user_id=c.ctx.actor,sales_user_id=c.other_id,created_by=c.ctx.admin))
        db.commit()
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        token=login(client,c,c.owner_name);before=snapshot(c);logs_before=log_snapshot(c)
        positive(client.get(path(c.foreign_invoice_id,kind),headers=token),kind)
        assert c.render_calls==[kind] and snapshot(c)==before and log_snapshot(c)==logs_before and c.calls==[]
        c.render_calls.clear()
        if withdrawal=='grant':
            result=client.put('/api/invoice/delegations/users/'+str(c.ctx.actor),headers=root,json={'sales_user_ids':[]})
        else:
            result=client.put('/api/auth/users/'+str(c.other_id),headers=root,json={'is_active':False})
        assert result.status_code==200
        with Session(c.ctx.engine) as db:
            if withdrawal=='grant':
                assert db.scalar(select(InvoiceDelegateGrant.id).where(InvoiceDelegateGrant.delegate_user_id==c.ctx.actor,
                    InvoiceDelegateGrant.sales_user_id==c.other_id)) is None
            else:
                from app.auth.models import ArkUser
                assert db.get(ArkUser,c.other_id).is_active is False
        assert_current_authorization(c)
        result=client.get(path(c.foreign_invoice_id,kind),headers=token)
        assert result.status_code==404 and c.render_calls==[]
        assert snapshot(c)==before and log_snapshot(c)==logs_before and c.calls==[]
        positive(client.get(path(c.invoice_id,kind),headers=token),kind)
        assert c.render_calls==[kind] and snapshot(c)==before and log_snapshot(c)==logs_before and c.calls==[]
