"""Independent customer copy, atomic recovery and template authority boundaries."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from test_onboarding_service import onboarding, add_customer, managed, portal_metadata, auth_context
from test_mapping_service import catalog
from app.portal import access_copy_service as service
from app.portal.errors import PortalError
from app.portal.models import Account, AuditEvent, CatalogGrant, CustomerAccess, Membership, OutboxEvent
from app.portal.schemas import CustomerCopy


def body(ctx, **patch):
    return CustomerCopy(**{'binding_fingerprint': ctx.selection_fingerprint,
        'canonical_customer_id': '2', 'assignment_id': '2', 'okki_identity_id': '2',
        'source_version': ctx.access.row_version, 'source_catalog_version': ctx.access.catalog_version,
        'email': 'new-buyer@example.com', 'password': ' New-password-2026 ', **patch})


def test_copy_grants_to_independent_customer_and_replay_after_template_change(onboarding, catalog):
    ctx, items = catalog
    ctx.account.delivery_json = {'contact_name': 'Private old buyer'}
    ctx.db.commit()
    key, request = uuid4(), body(ctx)
    result = service.copy(ctx.db, 1, ctx.access.public_id, key, request, 'test-hash')
    ctx.db.commit()
    assert result['status'] == 'enabled' and result['canonical_customer_id'] == '2'
    target = ctx.db.scalar(select(CustomerAccess).where(CustomerAccess.public_id == result['id']))
    assert target.id != ctx.access.id and target.can_order == ctx.access.can_order
    assert set(ctx.db.scalars(select(CatalogGrant.catalog_item_id).where(CatalogGrant.access_id == target.id))) == {item.id for item in items}
    account = ctx.db.scalar(select(Account).where(Account.public_id == result['account_id']))
    assert account.status == 'active' and account.password_hash == 'test-hash' and account.delivery_json is None
    assert ctx.db.scalar(select(Membership.access_id).where(Membership.account_id == account.id)) == target.id
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    audit = str([row.safe_diff_json for row in ctx.db.scalars(select(AuditEvent))])
    assert request.password.get_secret_value() not in audit
    ctx.access.row_version += 1; ctx.db.commit()
    replay = service.copy(ctx.db, 1, ctx.access.public_id, key, request, 'another-hash')
    assert replay['id'] == result['id'] and replay['replayed']
    assert ctx.db.scalar(select(func.count()).select_from(CustomerAccess)) == 2
    with pytest.raises(PortalError, match='同一操作标识'):
        service.copy(ctx.db, 1, ctx.access.public_id, key, body(ctx, email='other@example.com'), 'x')


@pytest.mark.parametrize('change,code', [('stale', 'VERSION_CONFLICT'), ('catalog', 'VERSION_CONFLICT'),
    ('disabled', 'ACCESS_NOT_ENABLED'), ('foreign', 'RESOURCE_NOT_FOUND'), ('withdrawn', 'CATALOG_REVIEW_REQUIRED')])
def test_copy_rechecks_source_and_never_creates_on_failure(onboarding, catalog, change, code):
    ctx, items = catalog
    request = body(ctx)
    actor = 1
    if change == 'stale': ctx.access.row_version += 1
    if change == 'catalog': ctx.access.catalog_version += 1
    if change == 'disabled': ctx.access.status = 'suspended'
    if change == 'foreign': actor = 2
    if change == 'withdrawn': items[0].status = 'draft'
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.copy(ctx.db, actor, ctx.access.public_id, uuid4(), request, 'x')
    ctx.db.rollback()
    assert caught.value.code == code
    assert ctx.db.scalar(select(func.count()).select_from(CustomerAccess)) == 1


def test_existing_email_failure_rolls_back_new_customer_and_grants(onboarding, catalog):
    ctx, _ = catalog
    with pytest.raises(PortalError) as caught:
        service.copy(ctx.db, 1, ctx.access.public_id, uuid4(), body(ctx, email=ctx.account.email_normalized), 'x')
    ctx.db.rollback()
    assert caught.value.code == 'ACCOUNT_ALREADY_EXISTS'
    assert ctx.db.scalar(select(func.count()).select_from(CustomerAccess)) == 1


def test_copy_target_cannot_be_another_salespersons_customer(onboarding, portal_metadata):
    ctx = onboarding
    ctx.db.execute(portal_metadata.tables['ark_customer_assignments'].update().where(
        portal_metadata.tables['ark_customer_assignments'].c.id == 2).values(user_id=2))
    ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.copy(ctx.db, 1, ctx.access.public_id, uuid4(), body(ctx), 'x')
    ctx.db.rollback()
    assert caught.value.status == 404


def test_copy_http_requires_key_and_returns_one_atomic_result(onboarding, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal import admin_router
    ctx = onboarding
    app = FastAPI(); app.include_router(admin_router.router, prefix='/api/portal/admin/v1')
    app.dependency_overrides[get_db] = lambda: ctx.db
    app.dependency_overrides[get_current_user] = lambda: {'sub': '1'}
    request = body(ctx).model_dump(mode='json', exclude={'password'})
    request['password'] = 'Synthetic-password-2026'
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            path = f'/api/portal/admin/v1/customers/{ctx.access.public_id}/copy'
            assert (await client.post(path, json=request)).status_code == 428
            headers = {'Idempotency-Key': str(uuid4())}
            first = await client.post(path, json=request, headers=headers)
            assert first.status_code == 201
            second = await client.post(path, json=request, headers=headers)
            assert second.status_code == 200
            assert first.json()['data']['id'] == second.json()['data']['id']
            assert second.json()['data']['replayed']
            assert request['password'] not in first.text
    asyncio.run(scenario())
