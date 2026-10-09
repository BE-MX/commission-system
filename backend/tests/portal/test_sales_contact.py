from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from test_site_service import configured, managed, portal_metadata, auth_context, settings_body
from app.portal import site_service, contact_service
from app.portal.schemas import SalesContact, SitePolicy
from app.portal.errors import PortalError


def profile(**values):
    return {'user_id': '1', 'display_name': 'April', 'email': 'april@example.com',
            'whatsapp': '+8613800000000', 'approved': True, **values}


def test_profile_is_explicit_current_owner_and_whitelisted(configured):
    ctx = configured
    principal = SimpleNamespace(site=ctx.site, access=ctx.access)
    assert contact_service.contact_view(principal) is None
    body = settings_body()
    body.policy.sales_contacts = [SalesContact(**profile()), SalesContact(**profile(user_id='2', approved=False))]
    result = site_service.update_settings(ctx.db, 1, 1, body); ctx.db.commit()
    assert result['contact_employee_options'][0]['id'] == '1'
    view = contact_service.contact_view(principal)
    assert view == {'display_name': 'April', 'email': 'april@example.com', 'whatsapp': '+8613800000000'}
    assert not {'user_id', 'approved'} & view.keys()
    # Changing the selected owner can never return the previous owner's profile.
    other = SimpleNamespace(site=ctx.site, access=SimpleNamespace(sales_user_id=2))
    assert contact_service.contact_view(other) is None
    version = ctx.site.policy_version
    body.policy.sales_contacts[0].approved = False
    site_service.update_settings(ctx.db, 1, 2, body); ctx.db.commit()
    assert contact_service.contact_view(principal) is None
    assert ctx.site.policy_version == version  # Contacts do not change accepted commercial terms.


def test_approved_contact_requires_active_employee(configured, portal_metadata):
    ctx = configured
    body = settings_body(); body.policy.sales_contacts = [SalesContact(**profile(user_id='999'))]
    with pytest.raises(PortalError) as caught: site_service.update_settings(ctx.db, 1, 1, body)
    assert caught.value.code == 'CONTACT_EMPLOYEE_UNAVAILABLE'
    assert ctx.site.row_version == 1
    user = portal_metadata.tables['ark_users']
    ctx.db.execute(user.update().where(user.c.id == 1).values(is_active=False)); ctx.db.commit()
    with pytest.raises(PortalError): contact_service.validate_contacts(ctx.db, [SalesContact(**profile())])


@pytest.mark.parametrize('values', [
    {'display_name': '<script>'}, {'display_name': 'April\nsecret'}, {'email': 'x@example.com?bcc=other@example.com'},
    {'email': 'x@example.com\r\nBcc:x@y.com'}, {'email': 'javascript:alert(1)'},
    {'whatsapp': 'javascript:alert(1)'}, {'whatsapp': '+00123'}, {'email': None, 'whatsapp': None},
])
def test_invalid_public_contact_is_rejected(values):
    with pytest.raises(ValidationError): SalesContact(**profile(**values))


def test_duplicate_owner_profiles_are_rejected():
    with pytest.raises(ValidationError): SitePolicy(sales_contacts=[profile(), profile()])


def test_customer_contact_http_session_and_revoked_approval(configured, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from test_auth_service import send_code, verify
    from app.core.database import get_db
    from app.portal import router as customer_http
    ctx = configured
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(customer_http, 'get_settings', lambda: ctx.settings)
    body = settings_body(); body.policy.sales_contacts = [SalesContact(**profile())]
    site_service.update_settings(ctx.db, 1, 1, body); ctx.db.commit()
    challenge, code = send_code(ctx)
    _, _, token = verify(ctx, challenge, code)
    app = FastAPI(); app.include_router(customer_http.router, prefix='/api/portal/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
                headers={'X-Real-IP': '203.0.113.1'}) as client:
            path = '/api/portal/v1/sales-contact'
            assert (await client.get(path)).status_code == 401
            client.cookies.set('__Host-portal_session', token)
            response = await client.get(path, params={'user_id': '999'})
            assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
            assert response.json()['data']['contact']['display_name'] == 'April'
            assert 'user_id' not in response.text and 'contact_employee_options' not in response.text
            body.policy.sales_contacts[0].approved = False
            site_service.update_settings(ctx.db, 1, 2, body); ctx.db.commit()
            assert (await client.get(path)).json()['data']['contact'] is None
            ctx.account.status = 'disabled'; ctx.db.commit()
            assert (await client.get(path)).status_code == 401
    asyncio.run(scenario())
