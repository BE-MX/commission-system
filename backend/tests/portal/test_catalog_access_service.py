import pytest
from sqlalchemy import select
from test_mapping_service import catalog
from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context, send_code, verify
from app.portal import catalog_access_service as service, mapping_service
from app.portal.errors import PortalError
from app.portal.models import CatalogGrant, AuditEvent
from app.portal.schemas import CustomerCatalogUpdate, MappingInput


def body(items):
    return CustomerCatalogUpdate(catalog_item_ids=[item.public_id for item in items], reason='Review authorized catalog')


def test_read_includes_withdrawn_but_only_safe_fields(catalog):
    ctx, items = catalog
    items[1].status = 'disabled'; ctx.db.commit()
    result = service.get_catalog(ctx.db, 1, ctx.access.public_id)
    assert len(result['items']) == 2 and result['items'][1]['status'] == 'disabled'
    assert set(result['items'][0]) == {'id', 'model_name', 'color_name', 'length', 'weight', 'sale_unit', 'status'}
    with pytest.raises(PortalError) as caught:
        service.get_catalog(ctx.db, 2, ctx.access.public_id)
    assert caught.value.status == 404


def test_catalog_edit_preserves_draft_and_capabilities(catalog):
    ctx, items = catalog
    ctx.access.status = 'draft'; ctx.access.can_order = False; ctx.db.commit()
    version, auth_version, catalog_version = ctx.access.row_version, ctx.access.auth_version, ctx.access.catalog_version
    result = service.update_catalog(ctx.db, 1, ctx.access.public_id, version, body(items[:1])); ctx.db.commit()
    assert result['status'] == 'draft' and result['capabilities']['can_order'] is False
    assert result['row_version'] == version + 1 and result['catalog_version'] == catalog_version + 1
    assert ctx.access.auth_version == auth_version + 1
    event = ctx.db.scalar(select(AuditEvent).where(AuditEvent.action == 'catalog_access_updated'))
    assert event.safe_diff_json['removed'] == [items[1].public_id]


def test_keep_withdrawn_remove_then_cannot_regrant(catalog):
    ctx, items = catalog
    items[1].status = 'disabled'; ctx.db.commit()
    service.update_catalog(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, body(items)); ctx.db.commit()
    assert len(service.get_catalog(ctx.db, 1, ctx.access.public_id)['items']) == 2
    service.update_catalog(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, body(items[:1])); ctx.db.commit()
    with pytest.raises(PortalError) as caught:
        service.update_catalog(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, body(items))
    assert caught.value.status == 422
    ctx.db.rollback()


def test_versions_scope_and_duplicate_ids_are_enforced(catalog):
    ctx, items = catalog
    for actor, version, desired, status in [(2, 1, items, 404), (3, 1, items, 403), (1, 0, items, 409), (1, 1, [items[0], items[0]], 422)]:
        with pytest.raises(PortalError) as caught:
            service.update_catalog(ctx.db, actor, ctx.access.public_id, version, body(desired))
        assert caught.value.status == status
        ctx.db.rollback()


def test_explicit_empty_catalog_revokes_sessions(catalog):
    ctx, _ = catalog
    challenge, code = send_code(ctx)
    _, session, _ = verify(ctx, challenge, code)
    result = service.update_catalog(ctx.db, 1, ctx.access.public_id, ctx.access.row_version, body([])); ctx.db.commit()
    assert result['items'] == [] and session.revoked_at


def test_adding_product_cannot_break_published_alias_projection(catalog):
    ctx, items = catalog
    second = ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id == items[1].id))
    second.status = 'disabled'; ctx.db.commit()
    mapping_service.publish(ctx.db, 1, ctx.access.public_id, ctx.access.row_version,
        MappingInput(base_version=0, entries=[{'kind': 'color', 'source_key': 'color:1', 'display_value': 'Brown'}]))
    ctx.db.commit()
    version = ctx.access.row_version
    with pytest.raises(PortalError) as caught:
        service.update_catalog(ctx.db, 1, ctx.access.public_id, version, body(items))
    assert caught.value.code == 'MAPPING_CONFLICT'
    ctx.db.rollback()
    assert second.status == 'disabled' and ctx.access.row_version == version
    assert len(mapping_service.current_projection(ctx.db, ctx.access)) == 1
