import pytest
from sqlalchemy import select
from pydantic import ValidationError

from test_auth_service import auth_context, send_code, verify
from app.portal import auth_service, delivery_profile_service as service
from app.portal.errors import PortalError
from app.portal.models import Account, Membership
from app.portal.schemas import DeliveryProfileInput


DELIVERY = {'contact_name': 'Buyer', 'phone': '123456', 'address_line1': 'Address 1', 'country_code': 'US'}


def session(ctx):
    challenge, code = send_code(ctx)
    principal, row, token = verify(ctx, challenge, code)
    return token, auth_service.session_view(principal, row)['csrf_token']


def test_profile_persists_without_revoking_session_and_detects_stale_update(auth_context):
    ctx = auth_context
    token, csrf = session(ctx)
    original_auth_version = ctx.account.auth_version
    assert service.read(ctx.db, token)['delivery'] is None
    request = DeliveryProfileInput(delivery=DELIVERY)
    result = service.save(ctx.db, token, csrf, ctx.account.row_version, request)
    ctx.db.commit()
    assert result['delivery']['address_line1'] == 'Address 1'
    ctx.db.expire_all()
    assert service.read(ctx.db, token) == result
    assert ctx.account.auth_version == original_auth_version
    with pytest.raises(PortalError) as caught:
        service.save(ctx.db, token, csrf, result['row_version'] - 1, request)
    assert caught.value.code == 'VERSION_CONFLICT'


def test_profile_is_account_scoped_even_for_same_company(auth_context):
    ctx = auth_context
    token, csrf = session(ctx)
    service.save(ctx.db, token, csrf, ctx.account.row_version, DeliveryProfileInput(delivery=DELIVERY))
    other = Account(email_normalized='other@example.com', email_display='other@example.com', contact_name='Other', status='active')
    ctx.db.add(other); ctx.db.flush()
    ctx.db.add(Membership(site_id=ctx.site.id, access_id=ctx.access.id, account_id=other.id, status='active'))
    ctx.db.commit()
    ctx.preauth, ctx.token, ctx.csrf = auth_service.bootstrap(ctx.db, '127.0.0.1')
    ctx.db.commit()
    challenge, code = send_code(ctx, 'other@example.com')
    _, _, other_token = verify(ctx, challenge, code)
    assert service.read(ctx.db, other_token)['delivery'] is None
    assert service.read(ctx.db, token)['delivery']['contact_name'] == 'Buyer'


def test_profile_rejects_csrf_revocation_and_foreign_identity_input(auth_context):
    ctx = auth_context
    token, csrf = session(ctx)
    with pytest.raises(PortalError):
        service.save(ctx.db, token, 'wrong', ctx.account.row_version, DeliveryProfileInput(delivery=DELIVERY))
    ctx.db.rollback()
    assert ctx.account.delivery_json is None
    with pytest.raises(ValidationError):
        DeliveryProfileInput(delivery=DELIVERY, account_id='2')
    ctx.account.status = 'disabled'; ctx.db.commit()
    with pytest.raises(PortalError): service.read(ctx.db, token)


def test_profile_migration_preserves_existing_account():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    path = Path(__file__).resolve().parents[2] / 'alembic/versions/204_portal_delivery_profile.py'
    spec = importlib.util.spec_from_file_location('delivery_migration', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE ark_order_portal_accounts (id INTEGER PRIMARY KEY, email_display TEXT)')
        connection.exec_driver_sql("INSERT INTO ark_order_portal_accounts VALUES (1, 'existing@example.com')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert 'delivery_json' in {column['name'] for column in inspect(connection).get_columns('ark_order_portal_accounts')}
        assert connection.execute(text('SELECT email_display, delivery_json FROM ark_order_portal_accounts')).one() == ('existing@example.com', None)
    engine.dispose()


def test_profile_http_enforces_customer_session_csrf_and_version(auth_context, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http
    ctx = auth_context
    token, csrf = session(ctx)
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(http, 'get_settings', lambda: ctx.settings)
    app = FastAPI(); app.include_router(http.router, prefix='/api/portal/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
                headers={'X-Real-IP': '203.0.113.1'}) as client:
            path = '/api/portal/v1/delivery-profile'
            assert (await client.get(path)).status_code == 401
            client.cookies.set('__Host-portal_session', token)
            assert (await client.get(path)).json()['data']['delivery'] is None
            headers = {'Origin': ctx.settings.PORTAL_ORIGIN, 'X-Portal-CSRF': csrf}
            assert (await client.put(path, headers=headers, json={'delivery': DELIVERY})).status_code == 428
            headers['If-Match'] = '"1"'
            response = await client.put(path, headers=headers, json={'delivery': DELIVERY})
            assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
            assert (await client.get(path)).json()['data']['delivery']['country_code'] == 'US'
            assert (await client.put(path, headers=headers, json={'delivery': DELIVERY})).status_code == 409
            headers['If-Match'] = '"2"'; headers['X-Portal-CSRF'] = 'wrong'
            assert (await client.put(path, headers=headers, json={'delivery': DELIVERY})).status_code == 403
    asyncio.run(scenario())
