"""Current salesperson contact projection with real MySQL identity/assignment."""
import asyncio

import httpx
from fastapi import FastAPI
import pytest
from sqlalchemy.orm import Session

from app.auth.models import ArkUser
from app.customer.models import CustomerAssignment
from app.core.database import get_db
from app.portal import admin_service, site_service, router
from app.portal.authority import lock_authority
from app.portal.models import CustomerAccess, Site
from app.portal.schemas import SitePolicy, SiteUpdate, SalesContact


@pytest.mark.parametrize('change', ['assignment', 'employee', 'approval'])
def test_real_mysql_contact_http_revokes_old_profile(trade, monkeypatch, change):
    ctx = trade
    settings = admin_service.get_settings()
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    monkeypatch.setattr(site_service, 'get_settings', lambda: settings)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        site = db.get(Site, access.site_id)
        policy = SitePolicy.model_validate(site.policy_json)
        policy.sales_contacts = [SalesContact(user_id=str(ctx.actor), display_name='Approved Representative',
            email='approved@example.com', approved=True)]
        version = site.policy_version
        body = SiteUpdate(name=site.name, status=site.status, policy=policy, reason='Approve public contact')
        saved = site_service.update_settings(db, ctx.admin, site.row_version, body)
        db.commit()
        assert saved['policy_version'] == version
        assignment_id = access.assignment_id
    app = FastAPI()
    app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.PORTAL_ORIGIN,
                headers={'X-Real-IP': '203.0.113.8'}) as client:
            path = '/api/portal/v1/sales-contact'
            assert (await client.get(path)).status_code == 401
            client.cookies.set('__Host-portal_session', ctx.token)
            response = await client.get(path, params={'user_id': str(ctx.admin)})
            assert response.status_code == 200
            assert response.json()['data']['contact'] == {'display_name': 'Approved Representative', 'email': 'approved@example.com', 'whatsapp': None}
            assert response.headers['cache-control'] == 'no-store'
            assert 'user_id' not in response.text and 'contact_employee_options' not in response.text
            with Session(ctx.engine) as writer:
                lock_authority(writer)
                if change == 'assignment':
                    writer.get(CustomerAssignment, assignment_id).user_id = ctx.admin
                elif change == 'employee':
                    writer.get(ArkUser, ctx.actor).is_active = False
                else:
                    body.policy.sales_contacts[0].approved = False
                    site_service.update_settings(writer, ctx.admin, saved['row_version'], body)
                writer.commit()
            response = await client.get(path)
            assert 'approved@example.com' not in response.text
            assert 'Approved Representative' not in response.text
            if change == 'approval':
                assert response.status_code == 200 and response.json()['data']['contact'] is None
            else:
                assert response.status_code == 409
                assert response.json()['data']['error_code'] == 'ASSIGNMENT_CHANGED'
    asyncio.run(scenario())


def test_real_mysql_full_contact_transfer_and_new_login(trade, monkeypatch):
    from datetime import timedelta
    from sqlalchemy import select
    from app.core.time import beijing_now
    from app.portal import auth_service, ownership_service, binding_review_service
    from app.portal.models import Account, OutboxEvent, PortalSession
    from app.portal.schemas import TransferInput, CustomerUpdate
    from app.portal.security import open_secret
    ctx = trade
    settings = admin_service.get_settings()
    settings.PORTAL_TRUSTED_PROXY_IPS = ['127.0.0.1']
    monkeypatch.setattr(router, 'get_settings', lambda: settings)
    monkeypatch.setattr(site_service, 'get_settings', lambda: settings)
    with Session(ctx.engine) as db:
        access = db.get(CustomerAccess, ctx.access_id)
        site = db.get(Site, access.site_id)
        replacement = ArkUser(username='replacement-' + ctx.item_id, password_hash='not-a-login', real_name='New Representative', is_active=True)
        db.add(replacement); db.flush()
        replacement_id = replacement.id
        policy = SitePolicy.model_validate(site.policy_json)
        policy.sales_contacts = [SalesContact(user_id=str(ctx.actor), display_name='Old Representative', email='old@example.com', approved=True),
            SalesContact(user_id=str(replacement.id), display_name='New Representative', email='new@example.com', approved=True)]
        site_service.update_settings(db, ctx.admin, site.row_version,
            SiteUpdate(name=site.name, status=site.status, policy=policy, reason='Approve both profiles'))
        email = db.get(Account, ctx.account_id).email_normalized
        access_public_id = access.public_id
        db.commit()
    app = FastAPI(); app.include_router(router.router, prefix='/api/portal/v1')
    def database():
        with Session(ctx.engine) as db: yield db
    app.dependency_overrides[get_db] = database
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.PORTAL_ORIGIN,
                headers={'X-Real-IP': '203.0.113.8', 'Origin': settings.PORTAL_ORIGIN}) as client:
            path = '/api/portal/v1/sales-contact'
            client.cookies.set('__Host-portal_session', ctx.token)
            assert (await client.get(path)).json()['data']['contact']['email'] == 'old@example.com'
            with Session(ctx.engine) as writer:
                lock_authority(writer)
                access = writer.get(CustomerAccess, ctx.access_id)
                old = writer.get(CustomerAssignment, access.assignment_id)
                old.assignment_status = 'ended'; old.effective_to = beijing_now()
                new = CustomerAssignment(customer_id=access.customer_id, user_id=replacement_id,
                    assignment_role='primary', assignment_status='active', assignment_source='manual', effective_from=beijing_now() - timedelta(minutes=1))
                writer.add(new); writer.flush(); assignment_id = new.id; writer.commit()
            denied = await client.get(path)
            assert denied.status_code == 409 and 'old@example.com' not in denied.text
            with Session(ctx.engine) as writer:
                review = binding_review_service.context(writer, ctx.admin, access_public_id)
                result = ownership_service.transfer_customer(writer, ctx.admin, access_public_id, review['row_version'],
                    TransferInput(review_fingerprint=review['review_fingerprint'], assignment_id=str(assignment_id),
                        pending_request_ids=[], history_policy='remove', reason='Reviewed customer handoff'))
                writer.commit()
                assert result['status'] == 'suspended' and result['requires_enable']
                assert writer.get(PortalSession, ctx.session_id).revoked_at is not None
            assert (await client.get(path)).status_code == 401
            with Session(ctx.engine) as writer:
                admin_service.update_customer(writer, ctx.admin, access_public_id, result['row_version'],
                    CustomerUpdate(status='enabled', capabilities={'can_order': True, 'can_view_price': True}, reason='Reopen reviewed customer'))
                writer.commit()
            assert (await client.get(path)).status_code == 401
            # Advance only the auth clock past the legitimate OTP resend window.
            auth_time = beijing_now() + timedelta(seconds=61)
            monkeypatch.setattr(auth_service, 'beijing_now', lambda: auth_time)
            client.cookies.clear()
            bootstrap = await client.get('/api/portal/v1/auth/bootstrap')
            assert bootstrap.status_code == 200
            csrf = bootstrap.json()['data']['csrf_token']
            challenge = await client.post('/api/portal/v1/auth/challenges', headers={'X-Portal-CSRF': csrf},
                json={'email': email, 'purpose': 'login'})
            assert challenge.status_code == 202, challenge.text
            challenge_id = challenge.json()['data']['challenge_id']
            with Session(ctx.engine) as db:
                event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == challenge_id))
                assert event is not None
                code = open_secret(settings.PORTAL_MAIL_KEYS['v1'], event.secret_envelope,
                    event_key=event.event_key, purpose='login', object_id=challenge_id)
            verified = await client.post('/api/portal/v1/auth/verify', headers={'X-Portal-CSRF': csrf},
                json={'challenge_id': challenge_id, 'code': code})
            assert verified.status_code == 200, verified.text
            assert verified.json()['data']['me']['sales_contact']['email'] == 'new@example.com'
            contact = await client.get(path, params={'user_id': str(ctx.actor)})
            assert contact.status_code == 200
            assert contact.json()['data']['contact']['email'] == 'new@example.com'
            assert 'old@example.com' not in contact.text
    asyncio.run(scenario())
