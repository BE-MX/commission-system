"""Actual assembled application: two identities, scoped commerce and real PI PDF.

Owned upstream fixtures remain synthetic; no provider/mail delivery or jobs run.
"""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import re
import secrets
import smtplib
import urllib.request
from uuid import uuid4

import httpx
import pytest
import reportlab
from pypdf import PdfReader
from sqlalchemy import delete, select, event
from sqlalchemy.orm import Session

from app.auth import router as employee_router, service as employee_auth, utils
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole, ArkLoginLog, ArkRefreshToken
from app.core.time import beijing_now
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
from app.invoice import okki_client, xiaoman_service, outbound_task_service
from app.invoice.models import Invoice, InvoiceItem
from app.portal import admin_service, pi_pdf, router
from app.portal.models import (Account, Membership, CustomerAccess, CatalogGrant, CatalogItem,
    OrderRequest, Revision, RequestLine, CommandReceipt, Conversion, Publication, OutboxEvent, AuditEvent)
from app.portal.security import open_secret
from app.receipt.models import ReceiptIntent
from test_mysql_full_application import assembled, boot  # noqa: F401


class Secret(str):
    def __repr__(self):return '<Owned test secret>'


class AuthHeaders(dict):
    def __repr__(self):return '<Owned employee headers>'


class CommerceFixture:
    def __repr__(self):return '<Owned actual application commerce>'


@pytest.fixture
def commerce(assembled,service_schema,monkeypatch,request):
    a=assembled;c=CommerceFixture();c.app=a;c.calls=[]
    a.settings.JWT_SECRET_KEY=secrets.token_urlsafe(48)
    a.settings.PDF_CJK_FONT_PATH=str(Path(reportlab.__file__).parent/'fonts'/'Vera.ttf')
    for module in (employee_router,employee_auth,utils):
        monkeypatch.setattr(module,'settings',a.settings)
    monkeypatch.setattr(pi_pdf,'get_settings',lambda:a.settings)
    password=secrets.token_urlsafe(24)
    c.password=password
    c.invited_email=uuid4().hex[:16]+"@example.test"
    with Session(a.ctx.engine) as db:
        permissions=[]
        for code in ('portal_order:read','portal_order:write','invoice:write','portal_mapping:read','portal_mapping:write','portal_access:read'):
            permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
            if permission is None:
                module,action=code.split(':')
                permission=ArkPermission(code=code,module=module,action=action,label=code,kind='action',is_legacy=False,sort=1)
                db.add(permission);db.flush()
            permissions.append(permission.id)
        role=ArkRole(name='commerce-own-'+uuid4().hex[:12],label='Owned salesperson')
        other_role=ArkRole(name='commerce-other-'+uuid4().hex[:12],label='Other salesperson')
        other=ArkUser(username='commerce-other-'+uuid4().hex[:12],real_name='Other Sales',
            password_hash=utils.hash_password(password),is_active=True)
        company=CustomerAccount(display_name='Other buyer',canonical_company_name='Other Company',record_status='active',identity_status='verified')
        db.add_all([role,other_role,other,company]);db.flush()
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id==a.ctx.actor))
        for employee,assigned in ((a.ctx.actor,role.id),(other.id,other_role.id)):
            db.add(ArkUserRole(user_id=employee,role_id=assigned))
        for assigned in (role.id,other_role.id):
            for permission in permissions:db.add(ArkRolePermission(role_id=assigned,permission_id=permission))
        own=db.get(ArkUser,a.ctx.actor);root=db.get(ArkUser,a.ctx.admin)
        own.password_hash=root.password_hash=utils.hash_password(password)
        c.owner_name,c.root_name,c.other_name=own.username,root.username,other.username
        c.other_id=other.id
        own_access=db.get(CustomerAccess,a.ctx.access_id)
        identity=CustomerExternalIdentity(customer_id=company.id,source_system='okki',source_account_key='okki:test',
            identifier_type='company_id',raw_value=str(company.id),normalized_value=str(company.id),identity_strength='strong',
            cardinality='one_to_one',verification_status='verified',status='active')
        assignment=CustomerAssignment(customer_id=company.id,user_id=other.id,assignment_role='primary',assignment_status='active',
            assignment_source='manual',effective_from=beijing_now()-timedelta(days=1))
        db.add_all([identity,assignment]);db.flush()
        other_access=CustomerAccess(site_id=own_access.site_id,customer_id=company.id,okki_namespace='okki:test',okki_company_id=str(company.id),
            external_identity_id=identity.id,assignment_id=assignment.id,sales_user_id=other.id,status='enabled',can_order=True,can_view_price=True,
            binding_fingerprint=admin_service.binding_fingerprint(company.id,identity,assignment))
        db.add(other_access);db.flush()
        c.other_access_id=other_access.public_id
        item=db.scalar(select(CatalogItem).where(CatalogItem.public_id==a.ctx.item_id))
        db.add(CatalogGrant(access_id=other_access.id,catalog_item_id=item.id))
        c.item_id=item.public_id;c.product_id=item.product_id;c.standard=dict(item.standard_json)
        c.catalog_model=item.display_name;c.catalog_color=item.color_name
        c.access_id=own_access.public_id;c.access_version=own_access.row_version
        accounts=[]
        for access in (own_access,other_access):
            account=Account(email_normalized=uuid4().hex[:16]+'@example.test',email_display='Buyer@example.test',
                contact_name='Buyer',status='active',verified_at=beijing_now())
            db.add(account);db.flush();db.add(Membership(site_id=access.site_id,account_id=account.id,access_id=access.id,status='active'))
            accounts.append((account.id,account.email_normalized))
        c.buyer_id,c.buyer_email=accounts[0];c.other_buyer_id,c.other_buyer_email=accounts[1]
        forwarded = Account(email_normalized=uuid4().hex[:16]+'@example.test', email_display='Forwarded@example.test',
            contact_name='Valid foreign buyer', status='active', verified_at=beijing_now())
        db.add(forwarded);db.flush()
        forwarded_member = Membership(site_id=other_access.site_id, account_id=forwarded.id, access_id=other_access.id, status='active')
        db.add(forwarded_member);db.flush()
        c.forwarded_id,c.forwarded_email,c.forwarded_member_id=forwarded.id,forwarded.email_normalized,forwarded_member.id
        db.commit()
        c.forwarded_graph = tuple(tuple(db.execute(select(*model.__table__.columns).where(model.id == identifier)).one())
            for model, identifier in ((Account, c.forwarded_id), (Membership, c.forwarded_member_id)))
        if getattr(request, 'param', None) == 'other_scope_admin':
            admin_permission = db.scalar(select(ArkPermission).where(ArkPermission.code == 'portal_access:admin'))
            assert admin_permission is not None
            db.add(ArkRolePermission(role_id=other_role.id, permission_id=admin_permission.id))
            ready = CustomerAccount(customer_code='ONBOARD-'+uuid4().hex[:12], display_name='New scoped buyer',
                canonical_company_name='New scoped buyer', record_status='active', identity_status='verified')
            blocked = CustomerAccount(customer_code='BLOCKED-'+uuid4().hex[:12], display_name='Missing identity buyer',
                canonical_company_name='Missing identity buyer', record_status='active', identity_status='provisional')
            db.add_all([ready,blocked]);db.flush()
            ready_assignment = CustomerAssignment(customer_id=ready.id,user_id=a.ctx.actor,assignment_role='primary',assignment_status='active',
                assignment_source='manual',effective_from=beijing_now()-timedelta(days=1))
            blocked_assignment = CustomerAssignment(customer_id=blocked.id,user_id=a.ctx.actor,assignment_role='primary',assignment_status='active',
                assignment_source='manual',effective_from=beijing_now()-timedelta(days=1))
            ready_identity = CustomerExternalIdentity(customer_id=ready.id,source_system='okki',source_account_key='okki:test',
                identifier_type='company_id',raw_value=str(ready.id),normalized_value=str(ready.id),identity_strength='strong',
                cardinality='one_to_one',verification_status='verified',status='active')
            db.add_all([ready_assignment,blocked_assignment,ready_identity]);db.flush()
            c.onboard_customer_id,c.onboard_customer_code=ready.id,ready.customer_code
            c.blocked_customer_id,c.blocked_customer_code=blocked.id,blocked.customer_code
            c.onboard_assignment_id,c.onboard_identity_id=ready_assignment.id,ready_identity.id
            c.onboard_invited_email=uuid4().hex[:16]+'@example.test'
            db.commit()
    def forbidden(name):
        def reject_call(*args,**kwargs):
            c.calls.append(name)
            raise AssertionError('Forbidden external side effect: '+name)
        return reject_call
    for module,name in ((okki_client,'push_order'),(okki_client,'push_outbound'),
        (xiaoman_service,'sync_invoice'),(outbound_task_service,'enqueue_outbound_task')):
        monkeypatch.setattr(module,name,forbidden(name))
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',forbidden('HTTP network'))
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',forbidden('Async HTTP network'))
    monkeypatch.setattr(urllib.request,'urlopen',forbidden('urllib network'))
    monkeypatch.setattr(smtplib.SMTP,'sendmail',forbidden('SMTP send'))
    c.db_writes=[];c.forbidden_writes=[]
    allowed={model.__tablename__ for model in (ArkUser,ArkLoginLog,ArkRefreshToken,ArkUserRole,
        Invoice,InvoiceItem,ReceiptIntent)}
    def inspect_write(connection,cursor,statement,parameters,context,executemany):
        match=re.match(r'\s*(?:INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+[`\"]?(\w+)',statement,re.I)
        if not match:return
        table=match.group(1);c.db_writes.append(table)
        if table not in allowed and not table.startswith('ark_order_portal_'):
            c.forbidden_writes.append(table)
            raise AssertionError('Unexpected commerce DML: '+table)
    event.listen(a.ctx.engine,'before_cursor_execute',inspect_write)
    try:yield c
    finally:event.remove(a.ctx.engine,'before_cursor_execute',inspect_write)


def employee_login(client,c,name):
    response=client.post('/api/auth/login',json={'username':name,'password':c.password})
    assert response.status_code==200
    return AuthHeaders(Authorization='Bearer '+response.json()['access_token'])


def customer_login(client,c,email):
    bootstrap=client.get('/api/portal/v1/auth/bootstrap');assert bootstrap.status_code==200
    csrf=bootstrap.json()['data']['csrf_token']
    cookies=bootstrap.headers.get('set-cookie','').lower()
    assert 'httponly' in cookies and 'secure' in cookies and 'samesite=lax' in cookies
    challenge=client.post('/api/portal/v1/auth/challenges',json={'email':email,'purpose':'login'},headers={'X-Portal-CSRF':csrf})
    assert challenge.status_code==202
    challenge_id=challenge.json()['data']['challenge_id']
    with Session(c.app.ctx.engine) as db:
        event=db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id==challenge_id))
        code=open_secret(c.app.settings.PORTAL_MAIL_KEYS['v1'],event.secret_envelope,
            event_key=event.event_key,purpose='login',object_id=challenge_id)
    wrong='000000' if code!='000000' else '111111'
    invalid=client.post('/api/portal/v1/auth/verify',json={'challenge_id':challenge_id,'code':wrong},headers={'X-Portal-CSRF':csrf})
    assert invalid.status_code==401 and invalid.json()['data']['error_code']=='AUTH_FAILED'
    verified=client.post('/api/portal/v1/auth/verify',json={'challenge_id':challenge_id,'code':code},headers={'X-Portal-CSRF':csrf})
    assert verified.status_code==200
    return Secret(verified.json()['data']['csrf_token']),Secret(client.cookies.get(router.cookie_name('session')))


def customer_cookie(client,token):
    client.cookies.set(router.cookie_name('session'),token,domain='orders.example.test',path='/')


def submit_http(client,c,csrf):
    quoted=client.post('/api/portal/v1/quotes',json=c.app.ctx.quote_body.model_dump(mode='json'),headers={'X-Portal-CSRF':csrf})
    assert quoted.status_code==201,quoted.text
    quote=quoted.json()['data']
    body={'quote_id':quote['quote_id'],'quote_content_hash':quote['content_hash'],'customer_po':c.app.ctx.quote_body.customer_po,'remark':''}
    headers={'X-Portal-CSRF':csrf,'Idempotency-Key':str(uuid4())}
    changed=client.post('/api/portal/v1/orders',json={**body,'customer_po':'CHANGED-PO'},headers=headers)
    assert changed.status_code==409 and changed.json()['data']['error_code']=='QUOTE_CHANGED'
    submitted=client.post('/api/portal/v1/orders',json=body,headers=headers)
    assert submitted.status_code==201,submitted.text
    replay=client.post('/api/portal/v1/orders',json=body,headers=headers)
    assert replay.status_code==200 and replay.json()['data']['request_id']==submitted.json()['data']['request_id']
    return submitted.json()['data']['request_id']


def proposal_body(c):
    return {**c.app.ctx.quote_body.model_dump(mode='json'),
        'fees':{'shipping_amount':'45.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
        'payment_terms':'prepaid','valid_for_hours':24,'reason':'Confirmed full commercial terms'}


def propose_and_accept(client,c,owner,request_id,csrf,before_accept=None):
    path='/api/portal/admin/v1/orders/'+request_id
    proposed=client.post(path+'/proposals',headers={**owner,'If-Match':'"1"'},json=proposal_body(c))
    assert proposed.status_code==200,proposed.text
    receipt=proposed.json()['data']['original_receipt']
    pending=client.get('/api/portal/v1/orders/'+request_id)
    assert pending.status_code==200 and pending.json()['data']['total_amount']=='128.00'
    premature=client.post(path+'/approve',headers={**owner,'If-Match':'"2"'},json={'accepted_revision_id':receipt['revision_id']})
    assert premature.status_code==409 and premature.json()['data']['error_code']=='CUSTOMER_ACCEPTANCE_REQUIRED'
    if before_accept is not None:before_accept(receipt)
    accepted=client.post('/api/portal/v1/orders/'+request_id+'/proposals/'+receipt['revision_id']+'/accept',
        json={'proposal_hash':receipt['content_hash']},headers={'X-Portal-CSRF':csrf,'If-Match':'"2"'})
    assert accepted.status_code==200,accepted.text
    return path,{'accepted_revision_id':receipt['revision_id']}


def business_snapshot(c):
    with Session(c.app.ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
            for model in (OrderRequest,Revision,RequestLine,Invoice,InvoiceItem,ReceiptIntent,CommandReceipt,Conversion,Publication,OutboxEvent))


def pdf_text(response):
    assert response.status_code==200 and response.headers['content-type']=='application/pdf'
    assert response.headers['cache-control']=='no-store' and response.content.startswith(b'%PDF-')
    return '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)


def test_actual_application_commercial_chain_aliases_and_historical_pi(commerce):
    c=commerce
    with c.app.client() as client:
        owner=employee_login(client,c,c.owner_name)
        entries=[{'kind':'sku','source_key':c.item_id,'item_id':c.item_id,'display_value':'Buyer Signature Straight','customer_sku':'BUYER-ST-20'},
            {'kind':'color','source_key':c.standard['color_key'],'display_value':'Buyer Natural Black'}]
        mapping_path='/api/portal/admin/v1/customers/'+c.access_id+'/mapping/publish'
        published=client.post(mapping_path,headers={**owner,'If-Match':'"'+str(c.access_version)+'"'},json={'base_version':0,'entries':entries})
        assert published.status_code==201,published.text
        csrf,token=customer_login(client,c,c.buyer_email)
        catalogue=client.get('/api/portal/v1/catalog')
        assert catalogue.status_code==200 and 'Buyer Signature Straight' in catalogue.text and 'Buyer Natural Black' in catalogue.text
        request_id=submit_http(client,c,csrf)
        path,body=propose_and_accept(client,c,owner,request_id,csrf)
        before_approval=client.get('/api/portal/v1/orders/'+request_id+'/pi')
        assert before_approval.status_code==409
        approved=client.post(path+'/approve',headers={**owner,'If-Match':'"3"'},json=body)
        assert approved.status_code==200,approved.text
        committed=business_snapshot(c)
        replay=client.post(path+'/approve',headers={**owner,'If-Match':'"3"'},json=body)
        assert replay.status_code==200 and replay.json()['data']['replayed'] is True
        assert replay.json()['data']['original_receipt']==approved.json()['data']['original_receipt']
        assert business_snapshot(c)==committed
        with Session(c.app.ctx.engine) as db:
            assert len(db.scalars(select(AuditEvent).where(AuditEvent.object_public_id==request_id,AuditEvent.action=='order.invoice_created')).all())==1
            assert len(db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_public_id==request_id,OutboxEvent.event_type=='order_invoice_created')).all())==1
        text=pdf_text(client.get('/api/portal/v1/orders/'+request_id+'/pi'))
        assert all(value in text for value in ('Buyer Signature Straight','Buyer Natural Black','BUYER-ST-20','128.00','Payment before shipment'))
        entries[0]['display_value']='Buyer New Straight';entries[0]['customer_sku']='BUYER-NEW-20'
        updated=client.post(mapping_path,headers={**owner,'If-Match':'"'+str(published.json()['data']['row_version'])+'"'},
            json={'base_version':1,'entries':entries})
        assert updated.status_code==201,updated.text
        assert 'Buyer New Straight' in client.get('/api/portal/v1/catalog').text
        historical=client.get('/api/portal/v1/orders/'+request_id)
        assert historical.status_code==200 and historical.json()['data']['items'][0]['display_snapshot']['model_name']=='Buyer Signature Straight'
        assert pdf_text(client.get('/api/portal/v1/orders/'+request_id+'/pi'))==text
        with Session(c.app.ctx.engine) as db:
            order=db.scalar(select(OrderRequest).where(OrderRequest.public_id==request_id))
            invoices=db.scalars(select(Invoice).where(Invoice.source_order_id==request_id)).all()
            assert len(invoices)==1 and invoices[0].id==order.invoice_id
            invoice=invoices[0]
            assert invoice.total_amount==Decimal('128.00') and invoice.sales_user_id==c.app.ctx.actor
            assert invoice.outbound_auto_requested==0 and invoice.sync_status=='not_synced' and invoice.xiaoman_order_id is None
            line=db.scalar(select(InvoiceItem).where(InvoiceItem.invoice_id==invoice.id))
            assert str(line.product_id)==c.product_id and line.model==c.standard['model'] and line.color==c.standard['color']
    assert c.calls==[] and c.forbidden_writes==[] and c.app.events.count('dispose')==1


def test_actual_application_cross_company_sales_scope_and_live_disable(commerce):
    c=commerce
    with c.app.client() as client:
        owner=employee_login(client,c,c.owner_name);other=employee_login(client,c,c.other_name);root=employee_login(client,c,c.root_name)
        csrf,token=customer_login(client,c,c.buyer_email)
        request_id=submit_http(client,c,csrf)
        other_csrf,other_token=customer_login(client,c,c.other_buyer_email)
        other_request=submit_http(client,c,other_csrf)
        for employee,own,foreign in ((owner,request_id,other_request),(other,other_request,request_id)):
            listing=client.get('/api/portal/admin/v1/orders',headers=employee)
            assert listing.status_code==200 and listing.json()['data']['total']==1
            assert listing.json()['data']['items'][0]['request_id']==own
            assert client.get('/api/portal/admin/v1/orders/'+own,headers=employee).status_code==200
            denied=client.get('/api/portal/admin/v1/orders/'+foreign,headers=employee)
            assert denied.status_code==404 and denied.json()['data']['error_code']=='RESOURCE_NOT_FOUND'
        for customer,foreign in ((token,other_request),(other_token,request_id)):
            customer_cookie(client,customer)
            for tail in ('','/pi'):
                denied=client.get('/api/portal/v1/orders/'+foreign+tail)
                assert denied.status_code==404 and denied.json()['data']['error_code']=='RESOURCE_NOT_FOUND'
        customer_cookie(client,token)
        def deny_foreign_decisions(receipt):
            baseline=business_snapshot(c)
            customer_cookie(client,other_token)
            base='/api/portal/v1/orders/'+request_id
            commands=(('/proposals/'+receipt['revision_id']+'/accept',{'proposal_hash':receipt['content_hash']}),
                ('/proposals/'+receipt['revision_id']+'/reject',{'reason':'Foreign rejection attempt'}),('/cancel',{'reason':'Foreign cancellation attempt'}))
            for tail,payload in commands:
                denied=client.post(base+tail,json=payload,headers={'X-Portal-CSRF':other_csrf,'If-Match':'"2"'})
                assert denied.status_code==404 and denied.json()['data']['error_code']=='RESOURCE_NOT_FOUND'
                assert business_snapshot(c)==baseline
            customer_cookie(client,token)
        path,body=propose_and_accept(client,c,owner,request_id,csrf,before_accept=deny_foreign_decisions)
        baseline=business_snapshot(c)
        foreign_approval=client.post(path+'/approve',headers={**other,'If-Match':'"3"'},json=body)
        assert foreign_approval.status_code==404 and foreign_approval.json()['data']['error_code']=='RESOURCE_NOT_FOUND'
        assert business_snapshot(c)==baseline
        disabled=client.put('/api/auth/users/'+str(c.app.ctx.actor),headers=root,json={'is_active':False})
        assert disabled.status_code==200
        assert 'invoice:write' in utils.decode_access_token(owner['Authorization'][7:])['permissions']
        baseline=business_snapshot(c)
        revoked=client.post(path+'/approve',headers={**owner,'If-Match':'"3"'},json=body)
        assert revoked.status_code==403 and revoked.json()['data']['error_code']=='ACTION_FORBIDDEN'
        assert client.get(path,headers=owner).status_code==403
        assert business_snapshot(c)==baseline
        enabled=client.put('/api/auth/users/'+str(c.app.ctx.actor),headers=root,json={'is_active':True})
        assert enabled.status_code==200
        approved=client.post(path+'/approve',headers={**owner,'If-Match':'"3"'},json=body)
        assert approved.status_code==200,approved.text
        with Session(c.app.ctx.engine) as db:
            chosen=db.scalar(select(OrderRequest).where(OrderRequest.public_id==request_id))
            foreign=db.scalar(select(OrderRequest).where(OrderRequest.public_id==other_request))
            assert chosen.status=='invoice_created' and foreign.status=='submitted' and foreign.invoice_id is None
            accepted=db.get(Revision,chosen.accepted_revision_id)
            assert accepted.customer_accepted_by==c.buyer_id
    assert c.calls==[] and c.forbidden_writes==[] and c.app.events.count('dispose')==1
