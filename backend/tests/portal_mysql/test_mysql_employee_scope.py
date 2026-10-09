"""Live employee scope and read-all permission never confer write authority."""
import asyncio
import secrets
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import router as auth_router, service as auth_service, utils
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.core.database import get_db
from app.invoice.models import Invoice
from app.portal import admin_router
from app.portal.authority import lock_authority
from app.portal.models import OrderRequest, Revision, CommandReceipt, AuditEvent, OutboxEvent, Conversion, Publication
from test_mysql_services import accepted_request


@pytest.mark.parametrize('write_capable', [False, True])
def test_employee_scope_and_read_all_do_not_grant_write(trade, monkeypatch, write_capable):
    ctx = trade
    request_id, accepted = accepted_request(ctx)
    settings = SimpleNamespace(JWT_SECRET_KEY=secrets.token_urlsafe(48), JWT_ALGORITHM='HS256',
        JWT_EXPIRE_MINUTES=15, REFRESH_TOKEN_EXPIRE_DAYS=1, COOKIE_SECURE=False,
        LOGIN_LOCK_MINUTES=30, LOGIN_MAX_FAIL=5)
    for module in (auth_router, auth_service, utils): monkeypatch.setattr(module, 'settings', settings)
    password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        role = ArkRole(name='portal-reader-' + uuid4().hex, label='Order reader')
        outsider = ArkUser(username='outsider-' + uuid4().hex, real_name='Other salesperson',
            password_hash=utils.hash_password(password), is_active=True)
        db.add_all([role, outsider]); db.flush()
        permissions = {}
        for code in ('portal_order:read', 'portal_order:read_all', 'portal_order:write', 'invoice:write'):
            permission = db.scalar(select(ArkPermission).where(ArkPermission.code == code))
            if permission is None:
                permission = ArkPermission(code=code, module='portal_order', action=code.split(':')[1],
                    label=code, kind='action', is_legacy=False, sort=1)
                db.add(permission); db.flush()
            permissions[code] = permission.id
        db.add_all([ArkUserRole(user_id=outsider.id, role_id=role.id),
            ArkRolePermission(role_id=role.id, permission_id=permissions['portal_order:read'])])
        if write_capable:
            for code in ('portal_order:write', 'invoice:write'):
                db.add(ArkRolePermission(role_id=role.id, permission_id=permissions[code]))
        owner = db.get(ArkUser, ctx.actor)
        owner.password_hash = utils.hash_password(password)
        owner_name = owner.username
        name, role_id, outsider_id = outsider.username, role.id, outsider.id
        db.commit()
    def snapshot():
        with Session(ctx.engine) as db:
            return tuple(tuple(db.execute(select(*model.__table__.columns).order_by(model.id)).all())
                for model in (OrderRequest, Revision, CommandReceipt, OutboxEvent, Invoice, Conversion, Publication))
    app = FastAPI()
    app.include_router(auth_router.router, prefix='/api/auth')
    app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    proposal = {**ctx.quote_body.model_dump(mode='json'),
        'fees':{'shipping_amount':'45.00','packaging_amount':'2.00','surcharge_amount':'0.00'},
        'payment_terms':'prepaid','valid_for_hours':24,'reason':'Review foreign customer'}
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            owner_login = await client.post('/api/auth/login', json={'username':owner_name, 'password':password})
            assert owner_login.status_code == 200
            positive = await client.post('/api/portal/admin/v1/orders/' + request_id + '/proposal-preview', json=proposal,
                headers={'Authorization':'Bearer ' + owner_login.json()['access_token'], 'If-Match':chr(34)+'3'+chr(34)})
            assert positive.status_code == 200
            login = await client.post('/api/auth/login', json={'username':name, 'password':password})
            assert login.status_code == 200
            headers = {'Authorization':'Bearer ' + login.json()['access_token'], 'If-Match':chr(34)+'3'+chr(34)}
            path = '/api/portal/admin/v1/orders/' + request_id
            mutations = (('/proposal-preview', proposal), ('/proposals', proposal),
                ('/approve', accepted.model_dump(mode='json')), ('/reject', {'reason':'Reject foreign order'}))
            for all_orders in (False, True):
                if all_orders:
                    with Session(ctx.engine) as db:
                        lock_authority(db)
                        db.add(ArkRolePermission(role_id=role_id, permission_id=permissions['portal_order:read_all']))
                        db.commit()
                baseline = snapshot()
                with Session(ctx.engine) as db:
                    audit_before = tuple(db.execute(select(*AuditEvent.__table__.columns).order_by(AuditEvent.id)).all())
                me = await client.get('/api/auth/me', headers=headers)
                expected_permissions = {'portal_order:read'} | ({'portal_order:read_all'} if all_orders else set()) | ({'portal_order:write', 'invoice:write'} if write_capable else set())
                assert set(me.json()['permissions']) == expected_permissions
                response = await client.get(path, headers=headers)
                assert response.status_code == (200 if all_orders else 404)
                if all_orders:
                    assert response.json()['data']['request_id'] == request_id
                listing = await client.get('/api/portal/admin/v1/orders', headers=headers)
                assert listing.status_code == 200
                visible = [item['request_id'] for item in listing.json()['data']['items']]
                assert (request_id in visible) is all_orders
                for tail, body in mutations:
                    response = await client.post(path + tail, headers=headers, json=body)
                    assert response.status_code == (404 if write_capable else 403)
                assert snapshot() == baseline
                with Session(ctx.engine) as db:
                    audit_after = tuple(db.execute(select(*AuditEvent.__table__.columns).order_by(AuditEvent.id)).all())
                    assert audit_after[:-1] == audit_before
                    last = db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
                    assert last.action == 'order.approval_failed' and last.reason == ('RESOURCE_NOT_FOUND' if write_capable else 'ACTION_FORBIDDEN')
                    assert last.object_public_id == request_id and last.safe_diff_json == {'employee_id': outsider_id}
    asyncio.run(run())