"""Nine real price APIs with current authorization on owned MySQL.

Actual app.main/JWT/admin writes; upstream catalog columns are synthetic.
No provider calls, full historical migration or production certification.
"""
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import builtins
import secrets
import re

import httpx
import pytest
from openpyxl import Workbook
from sqlalchemy import delete,event,select,text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.auth import router as employee_router,service as employee_auth,utils
from app.auth.models import ArkPermission,ArkRole,ArkRolePermission,ArkUser,ArkUserRole
from app.invoice.models import Invoice,InvoiceItem,StdPrice,PriceColorType,CustomerPriceRule
from app.invoice import price_authority
from app.portal import authority
from app.portal.models import Quote,OrderRequest,Revision,RequestLine,CommandReceipt,Conversion,Publication,PiAmendment,AuditEvent,OutboxEvent
from app.receipt.models import ReceiptIntent
from test_mysql_application_trade import AuthHeaders
from test_mysql_full_application import assembled,boot  # noqa: F401

OPERATIONS=('accessory_upsert','accessory_delete','std_upsert','std_delete','workbook_import',
            'color_upsert','color_delete','customer_upsert','customer_delete')
MODELS=(Invoice,InvoiceItem,ReceiptIntent,Quote,OrderRequest,Revision,RequestLine,CommandReceipt,
        Conversion,Publication,PiAmendment,AuditEvent,OutboxEvent,StdPrice,PriceColorType,CustomerPriceRule)


class PriceApplication:
    def __repr__(self):return '<Owned current price application>'


@pytest.fixture
def price_app(assembled,service_schema,monkeypatch):
    a=assembled;c=PriceApplication();c.app=a;c.ctx=a.ctx;c.calls=[]
    a.settings.JWT_SECRET_KEY=secrets.token_urlsafe(48)
    for module in (employee_router,employee_auth,utils):monkeypatch.setattr(module,'settings',a.settings)
    c.password=secrets.token_urlsafe(24)
    with Session(c.ctx.engine) as db:
        permissions=[]
        for code in ('invoice:admin','invoice_price:write'):
            permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
            if permission is None:
                module,action=code.split(':');permission=ArkPermission(code=code,module=module,action=action,label=code,kind='action',is_legacy=False,sort=1)
                db.add(permission);db.flush()
            permissions.append(permission.id)
        role=ArkRole(name='owned-price-'+uuid4().hex[:12],label='Owned price maintainer')
        db.add(role);db.flush();c.price_role=role.id;c.sales_role=service_schema.sales_role
        for permission in permissions:db.add(ArkRolePermission(role_id=role.id,permission_id=permission))
        db.add(ArkUserRole(user_id=c.ctx.actor,role_id=role.id))
        owner=db.get(ArkUser,c.ctx.actor);root=db.get(ArkUser,c.ctx.admin)
        owner.password_hash=root.password_hash=utils.hash_password(c.password)
        c.owner_name,c.root_name=owner.username,root.username;db.commit()
    def forbidden(*args,**kwargs):
        c.calls.append('network');raise AssertionError('Unexpected external price HTTP')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',forbidden)
    return c


def login(client,c,name):
    response=client.post('/api/auth/login',json={'username':name,'password':c.password})
    assert response.status_code==200
    return AuthHeaders(Authorization='Bearer '+response.json()['access_token'])


def change_user(client,c,root,body):
    response=client.put('/api/auth/users/'+str(c.ctx.actor),headers=root,json=body)
    assert response.status_code==200


def snapshot(c):
    with Session(c.ctx.engine) as db:
        return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all()) for model in MODELS)


def operation(c,kind,label):
    """Seed exact independent positive/victim identities before authorization."""
    suffix=uuid4().hex[:18];body=None;files=None;method='POST';base='/api/invoice/price/'
    with Session(c.ctx.engine) as db:
        if kind.startswith('accessory'):
            product=1000000+c.ctx.actor*1000+(0 if label=='positive' else 1)
            db.execute(text("INSERT INTO okki_products VALUES (:id,'Tape','TAPE','Clear',NULL,NULL,0)"),{'id':product})
            db.execute(text('INSERT INTO okki_product_skus VALUES (:id,:id,0)'),{'id':product})
            row=StdPrice(product_kind='accessory',product_id=product,sku_id=product,accessory_name='Tape',accessory_model='TAPE',accessory_color='Clear',price=Decimal('8'),currency='USD')
            db.add(row);db.flush()
            body={'id':row.id,'product_id':product,'sku_id':product,'accessory_name':'Tape','accessory_model':'TAPE','accessory_color':'Clear','price':'9.2500','currency':'USD'}
            path=base+'accessories'
            if kind.endswith('delete'):method='DELETE';path+='/'+str(row.id);body=None
        elif kind.startswith('std'):
            grade='Owned '+suffix
            row=StdPrice(product_kind='hair',series_grade=grade,length='20',weight_unit='20g',color_type='solid',price=Decimal('8'),currency='USD')
            db.add(row);db.flush();path=base+'std'
            body={'id':row.id,'series_grade':grade,'length':'20','weight_unit':'20g','color_type':'solid','price':'9.25','currency':'USD'}
            if kind.endswith('delete'):method='DELETE';path+='/'+str(row.id);body=None
        elif kind=='workbook_import':
            book=Workbook();sheet=book.active;sheet.title='价格表'
            sheet.append(['Price List----'+suffix]);sheet.append(['Owned'])
            sheet.append(['Length','Weight','Solid','Piano','Ombre','Balayage'])
            sheet.append(['20','20g',9.25,10.25,11.25,12.25])
            output=BytesIO();book.save(output);book.close()
            files={'file':('owned-prices.xlsx',output.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
            path=base+'import'
        elif kind.startswith('color'):
            row=PriceColorType(color_code=suffix,color_type='solid');db.add(row);db.flush()
            path=base+'color-types';body={'color_code':suffix,'color_type':'piano'}
            if kind.endswith('delete'):method='DELETE';path+='/'+str(row.id);body=None
        else:
            row=CustomerPriceRule(customer_id='owned-'+suffix,customer_name='Owned buyer',adjust_type='percent',adjust_value=Decimal('-10'),enabled=1)
            db.add(row);db.flush();path=base+'customer-rules'
            body={'customer_id':row.customer_id,'customer_name':'Owned buyer','adjust_type':'percent','adjust_value':'-5','enabled':True,'remark':'Owned price update'}
            if kind.endswith('delete'):method='DELETE';path+='/'+str(row.id);body=None
        db.commit()
    return SimpleNamespace(method=method,path=path,body=body,files=files)


def send(client,command,headers):
    values={'headers':headers}
    if command.body is not None:values['json']=command.body
    if command.files is not None:values['files']=command.files
    return client.request(command.method,command.path,**values)


def assert_success(c,before,response,kind):
    assert response.status_code==200 and response.json()['code']==200
    after=snapshot(c)
    assert after[:13]==before[:13]  # No order/PI/financial or portal event mutation.
    index=13 if kind.startswith(('accessory','std')) or kind=='workbook_import' else 14 if kind.startswith('color') else 15
    assert after[index]!=before[index]
    assert all(after[other]==before[other] for other in range(13,16) if other!=index)
    if kind=='workbook_import':assert response.json()['data']['prices_imported']==4 and len(after[index])==len(before[index])+4
    else:assert len(after[index])==len(before[index])-(1 if kind.endswith('delete') else 0)
    assert c.calls==[]


@pytest.mark.parametrize('kind',OPERATIONS)
@pytest.mark.parametrize('mode',['enabled','disabled_storefront'])
@pytest.mark.parametrize('revocation',['disabled','all_roles','write'])
def test_price_old_jwt_rejected_after_actual_admin_revocation(price_app,kind,mode,revocation):
    c=price_app;positive=operation(c,kind,'positive');victim=operation(c,kind,'victim')
    if mode=='disabled_storefront':
        c.app.settings.PORTAL_ENABLED=False;authority.get_settings().PORTAL_ENABLED=False
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);root=login(client,c,c.root_name)
        before=snapshot(c);assert_success(c,before,send(client,positive,owner),kind)
        body={'is_active':False} if revocation=='disabled' else {'role_ids':[]} if revocation=='all_roles' else {'role_ids':[c.sales_role]}
        change_user(client,c,root,body);before=snapshot(c)
        denied=send(client,victim,owner)
        assert denied.status_code==403
        assert denied.headers.get('cache-control')=='private, no-store'
        assert snapshot(c)==before and c.calls==[]
        change_user(client,c,root,{'is_active':True,'role_ids':[c.sales_role,c.price_role]})
        before=snapshot(c);assert_success(c,before,send(client,victim,owner),kind)


@pytest.mark.parametrize('kind',OPERATIONS)
@pytest.mark.parametrize('mode',['enabled','disabled_storefront'])
def test_price_old_jwt_observes_new_current_grant(price_app,kind,mode):
    c=price_app;victim=operation(c,kind,'victim')
    if mode=='disabled_storefront':
        c.app.settings.PORTAL_ENABLED=False;authority.get_settings().PORTAL_ENABLED=False
    with c.app.client() as client:
        root=login(client,c,c.root_name)
        change_user(client,c,root,{'role_ids':[c.sales_role]})
        owner=login(client,c,c.owner_name)
        before=snapshot(c);assert send(client,victim,owner).status_code==403;assert snapshot(c)==before
        change_user(client,c,root,{'role_ids':[c.sales_role,c.price_role]})
        before=snapshot(c);assert_success(c,before,send(client,victim,owner),kind)


@pytest.mark.parametrize('state',['snapshot','dirty','new','deleted'])
def test_price_write_rejects_nonfresh_caller_without_mutating_business(price_app,state):
    from fastapi import HTTPException
    c=price_app;before=snapshot(c)
    with Session(c.ctx.engine) as db:
        if state=='snapshot':db.scalar(select(StdPrice.id).limit(1))
        elif state=='new':db.add(PriceColorType(color_code=uuid4().hex,color_type='solid'))
        else:
            row=db.scalar(select(CustomerPriceRule).limit(1))
            if state=='dirty':row.remark='Must not flush'
            else:db.delete(row)
        with pytest.raises(HTTPException) as error:price_authority.begin_write(db,{'sub':str(c.ctx.actor)},'invoice:admin')
        assert error.value.status_code==409;db.rollback()
    assert snapshot(c)==before


@pytest.mark.parametrize('table',['ark_users','ark_roles','ark_permissions'])
@pytest.mark.parametrize('diagnostic_failure',['none','logger','stdout','both'])
def test_price_authorization_query_failure_is_private_and_recoverable(price_app,monkeypatch,table,diagnostic_failure):
    c=price_app;victim=operation(c,'customer_upsert','victim')
    with c.app.client() as client:
        owner=login(client,c,c.owner_name);before=snapshot(c);probe={'hits':0,'price_writes':0,'logger':0,'stdout':0}
        original_warning=price_authority.logger.warning
        def warning(*args,**kwargs):
            probe['logger']+=1
            if diagnostic_failure in {'logger','both'}:raise RuntimeError('Diagnostic sink unavailable')
            return original_warning(*args,**kwargs)
        def output(*args,**kwargs):
            probe['stdout']+=1
            if diagnostic_failure in {'stdout','both'}:raise RuntimeError('Diagnostic sink unavailable')
            return builtins.print(*args,**kwargs)
        def query(connection,cursor,statement,parameters,context,executemany):
            if re.match(r'\s*(?:INSERT|REPLACE|UPDATE|DELETE)\b',statement,re.I) and re.search(r'\bark_(?:std_prices|price_color_types|customer_price_rules)\b',statement):probe['price_writes']+=1
            if re.match(r'\s*SELECT\b',statement,re.I) and re.search(r'\bFROM\s+[`"]?'+table+r'[`"]?\b',statement,re.I):
                probe['hits']+=1
                raise OperationalError('Owned authorization probe',{},RuntimeError('Owned connection unavailable'))
        event.listen(c.ctx.engine,'before_cursor_execute',query)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(price_authority.logger,'warning',warning)
                patch.setattr(price_authority,'print',output,raising=False)
                response=send(client,victim,owner)
        finally:event.remove(c.ctx.engine,'before_cursor_execute',query)
        assert probe=={'hits':1,'price_writes':0,'logger':1,'stdout':1}
        assert response.status_code==503 and response.headers.get('cache-control')=='private, no-store'
        assert response.json()=={'detail':'价格维护授权暂不可用，请稍后重试'}
        assert snapshot(c)==before and c.calls==[]
        assert_success(c,before,send(client,victim,owner),'customer_upsert')
