import pytest
from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context, send_code, verify
from app.portal import admin_service as admin, auth_service as auth
from app.portal.models import CatalogGrant, CatalogItem
from app.portal.schemas import CustomerUpdate
from app.portal.errors import PortalError


def withdrawn_grant(ctx):
    item = CatalogItem(site_id=ctx.access.site_id, product_kind='hair', source_namespace='okki:test',
        product_id='1', sku_id='1', standard_fingerprint='a'*64, standard_json={},
        display_name='Withdrawn product', color_name='Black', status='disabled', inventory_unit='g',
        sale_unit='pack', conversion_factor='20')
    ctx.db.add(item)
    ctx.db.flush()
    grant = CatalogGrant(access_id=ctx.access.id, catalog_item_id=item.id, status='enabled')
    ctx.db.add(grant)
    ctx.db.commit()
    return item, grant


def test_suspension_preserves_withdrawn_grants_and_revokes_sessions(managed):
    ctx = managed
    _, grant = withdrawn_grant(ctx)
    challenge, code = send_code(ctx)
    _, session, token = verify(ctx, challenge, code)
    version = ctx.access.catalog_version
    admin.update_customer(ctx.db, 1, ctx.access.public_id, ctx.access.row_version,
        CustomerUpdate(status='suspended', capabilities={'can_view_price': False, 'can_order': False}, reason='suspend access'))
    ctx.db.commit()
    assert grant.status == 'enabled' and ctx.access.catalog_version == version
    assert session.revoked_at and ctx.access.status == 'suspended'
    with pytest.raises(PortalError):
        auth.authenticate(ctx.db, token)


def test_explicit_empty_list_removes_grants_but_disabled_item_cannot_be_regranted(managed):
    ctx = managed
    item, grant = withdrawn_grant(ctx)
    body = dict(status='enabled', capabilities={'can_view_price': True, 'can_order': True}, reason='remove grant')
    with pytest.raises(PortalError) as caught:
        admin.update_customer(ctx.db, 1, ctx.access.public_id, ctx.access.row_version,
            CustomerUpdate(**body, catalog_item_ids=[item.public_id]))
    assert caught.value.status == 422
    ctx.db.rollback()
    version = ctx.access.catalog_version
    admin.update_customer(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, CustomerUpdate(**body, catalog_item_ids=[]))
    ctx.db.commit()
    assert grant.status == 'disabled' and ctx.access.catalog_version == version + 1


def test_preserve_grants_still_enforces_scope_and_review_gate(managed):
    ctx = managed
    withdrawn_grant(ctx)
    body = CustomerUpdate(status='suspended', capabilities={'can_view_price': False, 'can_order': False}, reason='review')
    with pytest.raises(PortalError) as caught:
        admin.update_customer(ctx.db, 2, ctx.access.public_id, ctx.access.row_version, body)
    assert caught.value.status == 404
    ctx.db.rollback()
    ctx.access.status = 'review_required'
    ctx.db.commit()
    with pytest.raises(PortalError):
        admin.update_customer(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, body)
    assert ctx.access.status == 'review_required'
