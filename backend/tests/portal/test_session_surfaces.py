"""Same-origin credential confusion through real HTTP routes, isolated SQLite only.

The employee JWT signature/decoder and customer OTP/session are real. Upstream
columns are a thin fixture; managed.employee_principal supplies effective roles.
This does not establish production cookies, browser caching or employee RBAC.
"""
import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select

from test_admin_service import managed, portal_metadata, auth_context
from test_auth_service import send_code, verify
from app.auth import utils as jwt_utils
from app.core.database import get_db
from app.core.time import beijing_now
from app.portal import access_policy, admin_router, router as customer_router
from app.portal.access_policy import validate_binding as real_validate_binding
from app.portal.models import AuditEvent, MappingRevision, OutboxEvent, PortalSession, Quote


def test_same_origin_employee_customer_credentials_and_preview_are_not_interchangeable(managed, monkeypatch):
    ctx = managed
    monkeypatch.setattr(access_policy, 'validate_binding', real_validate_binding)
    monkeypatch.setattr(customer_router, 'get_settings', lambda: ctx.settings)
    monkeypatch.setattr(jwt_utils, 'settings', SimpleNamespace(
        JWT_SECRET_KEY='isolated-credential-surface-key' * 2, JWT_ALGORITHM='HS256', JWT_EXPIRE_MINUTES=10))
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    ctx.account.verified_at = beijing_now(); ctx.db.commit()
    challenge, code = send_code(ctx)
    _, _, opaque = verify(ctx, challenge, code)
    employee = jwt_utils.create_access_token({'sub': '1', 'roles': ['sales'], 'permissions': ['portal_mapping:read']})
    other_employee = jwt_utils.create_access_token({'sub': '2', 'roles': ['super_admin'], 'permissions': ['*']})
    app = FastAPI()
    app.include_router(customer_router.router, prefix='/api/portal/v1')
    app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    customer_session = '/api/portal/v1/session'
    staff_list = '/api/portal/admin/v1/customers'

    def counts():
        return tuple(ctx.db.scalar(select(func.count()).select_from(model))
                     for model in (PortalSession, Quote, MappingRevision, AuditEvent, OutboxEvent))

    async def scenario():
        transport = httpx.ASGITransport(app=app, client=('127.0.0.1', 31000))
        async with httpx.AsyncClient(transport=transport, base_url=ctx.settings.PORTAL_ORIGIN,
                headers={'X-Real-IP': '203.0.113.1'}) as client:
            signed = {'Authorization': 'Bearer ' + employee}
            # Establish a valid employee token; rejected customer requests aren't invalid-JWT tests.
            staff = await client.get(staff_list, headers=signed)
            assert staff.status_code == 200 and staff.json()['data']['total'] == 1
            assert staff.headers['cache-control'] == 'private, no-store'
            assert 'set-cookie' not in staff.headers
            denied = await client.get(customer_session, headers=signed)
            assert denied.status_code == 401 and denied.headers['cache-control'] == 'no-store'
            assert 'me' not in denied.json()['data']
            client.cookies.set('__Host-portal_session', employee)
            denied = await client.get(customer_session)
            assert denied.status_code == 401
            client.cookies.set('__Host-portal_session', opaque)
            current = await client.get(customer_session)
            assert current.status_code == 200
            identity = current.json()['data']['me']['account_public_id']
            assert identity == ctx.account.public_id
            mixed = await client.get(customer_session, headers={'Authorization': 'Bearer ' + other_employee})
            assert mixed.status_code == 200 and mixed.json()['data']['me']['account_public_id'] == identity
            assert mixed.headers['cache-control'] == 'no-store'
            cookie_only = await client.get(staff_list)
            assert cookie_only.status_code == 403 and cookie_only.json()['data']['error_code'] == 'AUTH_REQUIRED'
            assert cookie_only.headers['cache-control'] == 'private, no-store'
            opaque_bearer = await client.get(staff_list, headers={'Authorization': 'Bearer ' + opaque})
            assert opaque_bearer.status_code == 401 and opaque_bearer.json()['data']['error_code'] == 'AUTH_REQUIRED'
            before = counts()
            preview = await client.post('/api/portal/admin/v1/customers/' + ctx.access.public_id + '/preview',
                                        headers=signed, json={})
            assert preview.status_code == 200 and preview.json()['data']['preview'] is True
            assert preview.json()['data']['access_id'] == ctx.access.public_id
            assert preview.headers['cache-control'] == 'private, no-store' and 'set-cookie' not in preview.headers
            assert counts() == before
            client.cookies.clear()
            still_no_customer = await client.get(customer_session, headers=signed)
            assert still_no_customer.status_code == 401 and counts() == before
    asyncio.run(scenario())