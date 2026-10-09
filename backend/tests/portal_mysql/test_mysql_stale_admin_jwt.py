"""A genuine old super-admin JWT cannot preserve revoked portal authority."""
import asyncio
import secrets
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import router as auth_router, service as auth_service, utils, admin_router as employee_admin
from app.auth.admin_schemas import UserUpdateRequest
from app.auth.models import ArkUser, ArkRole, ArkUserRole
from app.core.database import get_db
from app.invoice.models import Invoice
from app.portal import admin_router
from app.portal.models import OrderRequest, Revision, CommandReceipt, AuditEvent, OutboxEvent, Conversion, Publication
from test_mysql_services import accepted_request


@pytest.mark.parametrize('revocation', ['roles', 'disabled'])
def test_old_super_admin_jwt_rechecks_live_authority(trade, monkeypatch, revocation):
    ctx = trade
    request_id, accepted = accepted_request(ctx)
    settings = SimpleNamespace(JWT_SECRET_KEY=secrets.token_urlsafe(48), JWT_ALGORITHM='HS256',
        JWT_EXPIRE_MINUTES=15, REFRESH_TOKEN_EXPIRE_DAYS=1, COOKIE_SECURE=False,
        LOGIN_LOCK_MINUTES=30, LOGIN_MAX_FAIL=5)
    for module in (auth_router,auth_service,utils): monkeypatch.setattr(module,'settings',settings)
    password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        owner = db.get(ArkUser,ctx.actor)
        owner.password_hash = utils.hash_password(password); username = owner.username
        super_role = db.scalar(select(ArkRole).where(ArkRole.name == 'super_admin'))
        db.add(ArkUserRole(user_id=ctx.actor,role_id=super_role.id))
        empty_role = ArkRole(name='revoked-'+uuid4().hex,label='No portal permissions')
        db.add(empty_role); db.flush(); empty_role_id = empty_role.id; db.commit()
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (OrderRequest,Revision,CommandReceipt,OutboxEvent,Invoice,Conversion,Publication))
    app = FastAPI(); app.include_router(auth_router.router,prefix='/api/auth')
    app.include_router(admin_router.router,prefix='/api/portal/admin/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    proposal = {**ctx.quote_body.model_dump(mode='json'),
        'fees':{'shipping_amount':'45.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
        'payment_terms':'prepaid','valid_for_hours':24,'reason':'Review current commercial terms'}
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            login = await client.post('/api/auth/login',json={'username':username,'password':password})
            assert login.status_code == 200
            token = login.json()['access_token']
            assert 'super_admin' in utils.decode_access_token(token)['roles']
            client.headers.update({'Authorization':'Bearer '+token,'If-Match':chr(34)+'3'+chr(34)})
            path = '/api/portal/admin/v1/orders/'+request_id
            assert (await client.get(path)).status_code == 200
            assert (await client.post(path+'/proposal-preview',json=proposal)).status_code == 200
            with Session(ctx.engine) as db:
                result = employee_admin.update_user(ctx.actor,
                    UserUpdateRequest(role_ids=[empty_role_id]) if revocation == 'roles' else UserUpdateRequest(is_active=False),
                    db,{'sub':str(ctx.admin)})
                assert result.code == 200
                roles, permissions = auth_service.get_live_user_authorization(db,ctx.actor)
                assert 'super_admin' not in roles and permissions == []
            # The bearer still carries super_admin and is not expired/replaced.
            assert 'super_admin' in utils.decode_access_token(token)['roles']
            baseline = snapshot()
            with Session(ctx.engine) as db:
                audit_before = tuple(db.execute(select(*AuditEvent.__table__.columns).order_by(AuditEvent.id)).all())
            for route in ('/api/portal/admin/v1/orders',path,path+'/audit'):
                response = await client.get(route)
                assert response.status_code == 403 and response.json()['data']['error_code'] == 'ACTION_FORBIDDEN'
            for tail, body in (('/proposal-preview',proposal),('/proposals',proposal),
                    ('/reject',{'reason':'Reject request'}),('/approve',accepted.model_dump(mode='json'))):
                response = await client.post(path+tail,json=body)
                assert response.status_code == 403 and response.json()['data']['error_code'] == 'ACTION_FORBIDDEN'
            assert snapshot() == baseline
            with Session(ctx.engine) as db:
                audits = tuple(db.execute(select(*AuditEvent.__table__.columns).order_by(AuditEvent.id)).all())
                assert audits[:-1] == audit_before
                event = db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc())).first()
                assert event.action == 'order.approval_failed' and event.actor_id is None and event.actor_type == 'system'
                assert event.object_public_id == request_id and event.reason == 'ACTION_FORBIDDEN'
                assert event.safe_diff_json == {'employee_id':ctx.actor}
    asyncio.run(run())