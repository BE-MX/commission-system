"""Read-only customer projection with real JWT, RBAC and MySQL scope."""
import asyncio
import secrets
from types import SimpleNamespace
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import router as auth_router, service as auth_service, utils
from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
from app.core.database import get_db
from app.portal import admin_router, mapping_service
from app.portal.authority import lock_authority
from app.portal.models import CustomerAccess, MappingRevision, Quote, AuditEvent, OutboxEvent, PortalSession
from app.portal.schemas import MappingInput


def test_real_jwt_read_only_preview_scope_and_revocation(trade, monkeypatch):
    ctx = trade
    suffix = uuid4().hex[:12]
    settings = SimpleNamespace(JWT_SECRET_KEY=secrets.token_urlsafe(48), JWT_ALGORITHM='HS256',
        JWT_EXPIRE_MINUTES=15, REFRESH_TOKEN_EXPIRE_DAYS=1, COOKIE_SECURE=False,
        LOGIN_LOCK_MINUTES=30, LOGIN_MAX_FAIL=5)
    for module in (auth_router, auth_service, utils): monkeypatch.setattr(module, 'settings', settings)
    password = secrets.token_urlsafe(24)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        mapping_service.publish(db, ctx.admin, access.public_id, access.row_version,
            MappingInput(base_version=0, entries=[{'kind': 'sku', 'source_key': ctx.item_id, 'item_id': ctx.item_id, 'display_value': 'Customer Silk'}]))
        actor = db.get(ArkUser, ctx.actor); actor.password_hash = utils.hash_password(password)
        outsider = ArkUser(username='preview-outside-' + suffix, real_name='Other employee', password_hash=utils.hash_password(password), is_active=True)
        role = ArkRole(name='preview-reader-' + suffix, label='Mapping reader')
        permission = db.scalar(select(ArkPermission).where(ArkPermission.code == 'portal_mapping:read'))
        if permission is None:
            permission = ArkPermission(code='portal_mapping:read', module='portal_mapping', action='read', label='Read mapping', kind='action', is_legacy=False, sort=1)
            db.add(permission)
        db.add_all([outsider, role]); db.flush()
        db.execute(delete(ArkUserRole).where(ArkUserRole.user_id == actor.id))
        db.add_all([ArkUserRole(user_id=actor.id, role_id=role.id), ArkUserRole(user_id=outsider.id, role_id=role.id), ArkRolePermission(role_id=role.id, permission_id=permission.id)])
        actor_name, outsider_name = actor.username, outsider.username
        access_public_id, role_id, permission_id = access.public_id, role.id, permission.id
        db.commit()
    def counts():
        with Session(ctx.engine) as db:
            return tuple(db.scalar(select(func.count()).select_from(model))
                for model in (MappingRevision, Quote, AuditEvent, OutboxEvent, PortalSession))
    app = FastAPI()
    app.include_router(auth_router.router, prefix='/api/auth')
    app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            async def login(name):
                response = await client.post('/api/auth/login', json={'username': name, 'password': password})
                assert response.status_code == 200
                return {'Authorization': 'Bearer ' + response.json()['access_token']}
            owner = await login(actor_name); outside = await login(outsider_name)
            path = f'/api/portal/admin/v1/customers/{access_public_id}'
            me = await client.get('/api/auth/me', headers=owner)
            assert set(me.json()['permissions']) == {'portal_mapping:read'}
            before = counts()
            response = await client.post(path + '/preview', json={}, headers=owner)
            assert response.status_code == 200
            assert response.json()['data']['items'][0]['model_name'] == 'Customer Silk'
            assert 'set-cookie' not in response.headers and 'no-store' in response.headers['cache-control']
            assert counts() == before
            response = await client.post(path + '/preview', json={}, headers=outside)
            assert response.status_code == 404
            assert 'Customer Silk' not in response.text
            response = await client.post(path + '/mapping/preview', json={'base_version': 1, 'entries': []}, headers=owner)
            assert response.status_code == 403
            with Session(ctx.engine) as writer:
                lock_authority(writer)
                writer.execute(delete(ArkRolePermission).where(ArkRolePermission.role_id == role_id, ArkRolePermission.permission_id == permission_id))
                writer.commit()
            response = await client.post(path + '/preview', json={}, headers=owner)
            assert response.status_code == 403 and 'Customer Silk' not in response.text
            assert counts() == before
    asyncio.run(run())
