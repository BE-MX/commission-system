"""Real RBAC and fresh-session invoice summary specifications."""
from datetime import date
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.invoice.models import Invoice,InvoiceDelegateGrant
from test_mysql_full_application import assembled,boot,owner
from test_mysql_receipt_authority import receipt_app,login,change_user,snapshot


from test_mysql_invoice_current_reads import read_roles,assert_current_authorization

def prepare(c,day=7):
    roles=read_roles(c)
    with Session(c.ctx.engine) as db:
        for identity in (c.invoice_id,c.foreign_invoice_id):
            row=db.get(Invoice,identity);row.invoice_date=date(2051,3,day);row.sync_status='synced';row.status='ready'
        db.commit()
    return roles

@pytest.mark.parametrize('change',['disabled','roles','action','read_all','super_admin'])
def test_summary_rechecks_actual_committed_authority(receipt_app,change):
    c=receipt_app;day={'disabled':7,'roles':8,'action':9,'read_all':10,'super_admin':11}[change];roles=prepare(c,day)
    params={'date_from':f'2051-03-{day:02d}','date_to':f'2051-03-{day:02d}'}
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        starting=roles['super_admin'] if change=='super_admin' else roles['global']
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],starting]})
        token=login(client,c,c.owner_name)
        initial=client.get('/api/invoice/invoices/summary',headers=token,params=params)
        assert initial.status_code==200 and initial.json()['data']['order_count']==2
        body=({'is_active':False} if change=='disabled' else {'role_ids':[]} if change=='roles' else
            {'role_ids':[c.sales_role,c.roles['both']]} if change=='action' else
            {'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        change_user(client,c,root,body)
        assert_current_authorization(c,active=change!='disabled',read=change not in {'roles','action'},all_scope=change=='disabled')
        before=snapshot(c)
        result=client.get('/api/invoice/invoices/summary',headers=token,params=params)
        assert snapshot(c)==before and c.calls==[]
        assert result.status_code==(200 if change in {'read_all','super_admin'} else 403)
        if result.status_code==200:assert result.json()['data']['order_count']==1

def test_summary_applies_new_grant_without_reissuing_identity_token(receipt_app):
    c=receipt_app;roles=prepare(c,12)
    params={'date_from':'2051-03-12','date_to':'2051-03-12'}
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both']]})
        assert_current_authorization(c,read=False)
        token=login(client,c,c.owner_name)
        assert client.get('/api/invoice/invoices/summary',headers=token,params=params).status_code==403
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        assert_current_authorization(c)
        before=snapshot(c)
        result=client.get('/api/invoice/invoices/summary',headers=token,params=params)
        assert snapshot(c)==before and c.calls==[]
        assert result.status_code==200 and result.json()['data']['order_count']==1

@pytest.mark.parametrize('withdrawal',['grant','owner_disabled'])
def test_summary_preserves_main_statistics_and_current_delegation(receipt_app,withdrawal):
    c=receipt_app;year=2061 if withdrawal=='grant' else 2062;roles=read_roles(c);prefix='summary-'+uuid4().hex[:16]; ids={}
    with Session(c.ctx.engine) as db:
        grant=InvoiceDelegateGrant(delegate_user_id=c.ctx.actor,sales_user_id=c.other_id,created_by=c.other_id)
        db.add(grant);db.flush();grant_id=grant.id
        def add(label,**kw):
            fields=dict(invoice_no=prefix+'-'+label,order_type='stock',customer_name='Summary buyer',invoice_date=date(year,9,15),
                sales_user_id=c.ctx.actor,created_by=c.ctx.actor,total_amount=Decimal('100'),currency='USD',okki_new_deal=0,sync_status='synced',status='ready',customer_id=prefix+label)
            fields.update(kw);row=Invoice(**fields);db.add(row);db.flush();ids[label]=row.id
        add('A1',invoice_date=date(year,9,1),customer_id=prefix+'A',okki_new_deal=1)
        add('A2',invoice_date=date(year,9,30),customer_id=prefix+'A',total_amount=Decimal('50'),okki_new_deal=1)
        add('B',sales_user_id=c.other_id,total_amount=Decimal('200'),okki_new_deal=1)
        add('EUR',total_amount=Decimal('99'),currency='EUR')
        add('NULL',total_amount=Decimal('40'),okki_new_deal=None)
        add('OTHER',sales_user_id=c.other_id,created_by=c.other_id,total_amount=Decimal('1000'),okki_new_deal=1)
        add('AUG',invoice_date=date(year,8,31),total_amount=Decimal('400'))
        add('DRAFT',sync_status='not_synced',total_amount=Decimal('300'))
        add('PENDING',status='cancel_pending',total_amount=Decimal('500'))
        add('CANCEL',status='cancelled',total_amount=Decimal('500'));db.commit()
    params={'date_from':f'{year}-09-01','date_to':f'{year}-09-30'}
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        token=login(client,c,c.owner_name);before=snapshot(c)
        summary=client.get('/api/invoice/invoices/summary',headers=token,params=params)
        assert summary.status_code==200
        assert summary.json()['data']=={'gmv':390.0,'new_sign_count':2,'unknown_new_sign_count':1,'order_count':5,'average_order_amount':97.5,'non_usd_count':1}
        page=client.get('/api/invoice/invoices',headers=token,params={'page_size':1,'keyword':prefix})
        assert page.status_code==200 and len(page.json()['data']['items'])==1
        assert snapshot(c)==before and c.calls==[]
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],roles['global']]})
        all_rows=client.get('/api/invoice/invoices/summary',headers=token,params=params)
        # Each parameter owns a separate year; exact six excludes other-scope drafts/cancellations/out-of-range rows.
        assert all_rows.status_code==200
        assert all_rows.json()['data']=={'gmv':1390.0,'new_sign_count':3,'unknown_new_sign_count':1,'order_count':6,'average_order_amount':278.0,'non_usd_count':1}
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        if withdrawal=='grant':
            with Session(c.ctx.engine) as db:db.delete(db.get(InvoiceDelegateGrant,grant_id));db.commit()
        else:
            response=client.put('/api/auth/users/'+str(c.other_id),headers=root,json={'is_active':False})
            assert response.status_code==200
        before=snapshot(c)
        reduced=client.get('/api/invoice/invoices/summary',headers=token,params=params)
        assert reduced.status_code==200
        assert reduced.json()['data']=={'gmv':190.0,'new_sign_count':1,'unknown_new_sign_count':1,'order_count':4,'average_order_amount':round(190/3,2),'non_usd_count':1}
        listing=client.get('/api/invoice/invoices',headers=token,params={'page_size':100,'keyword':prefix})
        assert listing.status_code==200 and ids['B'] not in {row['id'] for row in listing.json()['data']['items']}
        assert snapshot(c)==before and c.calls==[]

def test_summary_invalid_and_empty_ranges_keep_current_permission_gate(receipt_app):
    c=receipt_app;roles=read_roles(c)
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both'],roles['private']]})
        token=login(client,c,c.owner_name);before=snapshot(c)
        empty=client.get('/api/invoice/invoices/summary',headers=token,params={'date_from':'2071-10-01','date_to':'2071-10-31'})
        assert empty.status_code==200 and empty.json()['data']=={'gmv':0.0,'new_sign_count':0,'unknown_new_sign_count':0,'order_count':0,'average_order_amount':0.0,'non_usd_count':0}
        reverse=client.get('/api/invoice/invoices/summary',headers=token,params={'date_from':'2071-10-01','date_to':'2071-09-30'})
        assert reverse.status_code==422
        change_user(client,c,root,{'role_ids':[c.sales_role,c.roles['both']]})
        assert client.get('/api/invoice/invoices/summary',headers=token,params={'date_from':'2071-10-01','date_to':'2071-09-30'}).status_code==403
        assert snapshot(c)==before and c.calls==[]
