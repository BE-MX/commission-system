"""Real employee JWT, live mapping permissions and cross-owner notification HTTP scope."""
import asyncio
from datetime import timedelta
import secrets
from uuid import uuid4

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.core.time import beijing_now
from app.auth import utils
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUser, ArkUserRole
from app.customer.models import CustomerAccount, CustomerAssignment, CustomerExternalIdentity
from app.portal import admin_service, mapping_service, notification_worker, notification_admin_service as delivery
from app.portal.models import CustomerAccess, OutboxEvent, AuditEvent
from app.portal.schemas import MappingInput
from test_mysql_mapping_notifications import delivery_context
from test_mysql_decision_recovery import make_app
from test_mysql_notification_process import business_snapshot


def snapshot(ctx):
    with Session(ctx.engine) as db:
        return (business_snapshot(ctx), tuple(db.execute(select(*OutboxEvent.__table__.columns).order_by(OutboxEvent.id)).all()))


def test_real_mapping_notification_http_scope_and_live_revocation(delivery_context, service_schema, monkeypatch):
    ctx=delivery_context
    assert notification_worker.run_once(ctx.factory) == 'expanded'
    app, settings, _, owner_login = make_app(ctx, monkeypatch)
    other_password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        permissions={}
        for code in ('portal_mapping:read','portal_mapping:write','portal_order:read_all'):
            permission=db.scalar(select(ArkPermission).where(ArkPermission.code==code))
            if permission is None:
                module,action=code.split(':')
                permission=ArkPermission(code=code,module=module,action=action,label=code,
                    kind='data' if action=='read_all' else 'action',is_legacy=False,sort=1)
                db.add(permission);db.flush()
            permissions[code]=permission.id
        for code in ('portal_mapping:read','portal_mapping:write'):
            if db.get(ArkRolePermission,(service_schema.sales_role,permissions[code])) is None:
                db.add(ArkRolePermission(role_id=service_schema.sales_role,permission_id=permissions[code]))
        role=ArkRole(name='mapping-outsider-'+uuid4().hex,label='Other salesperson with order read-all')
        other=ArkUser(username='mapping-other-'+uuid4().hex,password_hash=utils.hash_password(other_password),real_name='Other Sales',is_active=True)
        company=CustomerAccount(display_name='Other mapping buyer',canonical_company_name='Other buyer',record_status='active',identity_status='verified')
        db.add_all([role,other,company]);db.flush()
        db.add(ArkUserRole(user_id=other.id,role_id=role.id))
        for permission in permissions.values():db.add(ArkRolePermission(role_id=role.id,permission_id=permission))
        identity=CustomerExternalIdentity(customer_id=company.id,source_system='okki',source_account_key='okki:test',
            identifier_type='company_id',raw_value=str(company.id),normalized_value=str(company.id),identity_strength='strong',
            cardinality='one_to_one',verification_status='verified',status='active')
        assignment=CustomerAssignment(customer_id=company.id,user_id=other.id,assignment_role='primary',assignment_status='active',
            assignment_source='manual',effective_from=beijing_now()-timedelta(days=1))
        db.add_all([identity,assignment]);db.flush()
        access=CustomerAccess(site_id=db.get(CustomerAccess,ctx.access_id).site_id,customer_id=company.id,okki_namespace='okki:test',
            okki_company_id=str(company.id),external_identity_id=identity.id,assignment_id=assignment.id,sales_user_id=other.id,
            status='enabled',can_order=True,can_view_price=True,binding_fingerprint=admin_service.binding_fingerprint(company.id,identity,assignment))
        db.add(access);db.commit()
        foreign=mapping_service.publish(db,ctx.admin,access.public_id,access.row_version,MappingInput(base_version=0,entries=[]));db.commit()
        foreign_access=access.public_id
        foreign_source=db.scalar(select(OutboxEvent).where(OutboxEvent.event_key=='mapping-published:'+foreign['id']))
        foreign_event=foreign_source.public_id
        child=db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id==ctx.access_public_id,OutboxEvent.event_type=='mapping_mail'))
        child.status,child.attempt_count,child.last_error_code='dead',8,'MAIL_TRANSPORT_FAILED'
        child_id=child.public_id
        injected=[]
        for event_type,revision in (('auth_code',ctx.revision_id),('order_submitted',ctx.revision_id),('mapping_published',foreign['id'])):
            row=OutboxEvent(event_key='polluted:'+uuid4().hex,event_type=event_type,aggregate_public_id=ctx.access_public_id,
                payload_json={'access_public_id':ctx.access_public_id,'mapping_revision_public_id':revision,'mapping_version':1},
                status='dead',attempt_count=8,last_error_code='MAIL_TRANSPORT_FAILED',next_attempt_at=beijing_now())
            db.add(row);db.flush();injected.append(row.public_id)
        db.commit()
        request_body={'fingerprint':delivery.fingerprint(child),'reason':'Transport recovered; scoped employee retry'}
        row_versions=(db.get(CustomerAccess,ctx.access_id).mapping_version,db.get(CustomerAccess,ctx.access_id).row_version)
        other_login={'username':other.username,'password':other_password}
        write_permission=permissions['portal_mapping:write'];read_permission=permissions['portal_mapping:read']
    base='/api/portal/admin/v1/customers/'+ctx.access_public_id+'/mapping/notifications'
    foreign_base='/api/portal/admin/v1/customers/'+foreign_access+'/mapping/notifications'
    command_headers={'Idempotency-Key':str(uuid4())}
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            own=await client.post('/api/auth/login',json=owner_login)
            outsider=await client.post('/api/auth/login',json=other_login)
            assert own.status_code==outsider.status_code==200
            owner={'Authorization':'Bearer '+own.json()['access_token']}
            other={'Authorization':'Bearer '+outsider.json()['access_token']}
            initial=snapshot(ctx)
            first=await client.get(base,headers=owner)
            assert first.status_code==200 and first.headers['cache-control']=='private, no-store'
            assert first.json()['data']['access_id']==ctx.access_public_id and first.json()['data']['total']==2
            assert {item['id'] for item in first.json()['data']['items']}=={ctx.source_id,child_id}
            positive=await client.get(foreign_base,headers=other)
            assert positive.status_code==200 and positive.json()['data']['total']==1
            assert positive.json()['data']['items'][0]['id']==foreign_event
            for path,headers in ((base,other),(foreign_base,owner),
                ('/api/portal/admin/v1/customers/'+str(uuid4())+'/mapping/notifications',owner)):
                denied=await client.get(path,headers=headers)
                assert denied.status_code==404 and denied.json()['data']['error_code']=='RESOURCE_NOT_FOUND'
                assert denied.headers['cache-control']=='private, no-store'
            for path,headers in ((base+'/'+child_id+'/retry',other),(foreign_base+'/'+foreign_event+'/retry',owner),
                *((base+'/'+identifier+'/retry',owner) for identifier in injected),
                (base+'/'+str(uuid4())+'/retry',owner),
                ('/api/portal/admin/v1/customers/'+str(uuid4())+'/mapping/notifications/'+child_id+'/retry',owner)):
                denied=await client.post(path,headers={**headers,**command_headers},json=request_body)
                assert denied.status_code==404 and denied.json()['data']['error_code']=='RESOURCE_NOT_FOUND'
            assert snapshot(ctx)==initial
            accepted=await client.post(base+'/'+child_id+'/retry',headers={**owner,**command_headers},json=request_body)
            assert accepted.status_code==200 and accepted.json()['data']['original_receipt']['access_id']==ctx.access_public_id
            assert accepted.json()['data']['current']['status']=='pending'
            with Session(ctx.engine) as db:
                audit=db.scalar(select(AuditEvent).where(AuditEvent.access_id==ctx.access_id,AuditEvent.action=='notification.retry_requested'))
                assert audit.actor_id==ctx.actor
                access=db.get(CustomerAccess,ctx.access_id)
                assert (access.mapping_version,access.row_version)==row_versions
                db.execute(delete(ArkRolePermission).where(ArkRolePermission.role_id==service_schema.sales_role,
                    ArkRolePermission.permission_id==write_permission));db.commit()
            after_write_revoke=snapshot(ctx)
            replay=await client.post(base+'/'+child_id+'/retry',headers={**owner,**command_headers},json=request_body)
            assert replay.status_code==403 and replay.json()['data']['error_code']=='ACTION_FORBIDDEN'
            assert (await client.get(base,headers=owner)).status_code==200
            assert snapshot(ctx)==after_write_revoke
            with Session(ctx.engine) as db:
                db.execute(delete(ArkRolePermission).where(ArkRolePermission.role_id==service_schema.sales_role,
                    ArkRolePermission.permission_id==read_permission));db.commit()
            after_read_revoke=snapshot(ctx)
            denied=await client.get(base,headers=owner)
            assert denied.status_code==403 and denied.json()['data']['error_code']=='ACTION_FORBIDDEN'
            assert snapshot(ctx)==after_read_revoke
    asyncio.run(check())