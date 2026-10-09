import pytest
from sqlalchemy import func, select
from test_mapping_service import catalog
from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context
from app.portal import mapping_service
from app.portal.errors import PortalError
from app.portal.models import MappingRevision
from app.portal.schemas import MappingInput


def conflict_body(items):
    return MappingInput(base_version=0, entries=[
        {'kind': 'color', 'source_key': f'color:{i}', 'display_value': 'Natural'} for i in (1, 2)
    ] + [{'kind': 'sku', 'source_key': item.public_id, 'item_id': item.public_id,
          'display_value': 'Same model', 'customer_sku': 'CUSTOM-01'} for item in items])


def test_preview_reports_all_conflict_types_without_publishing(catalog):
    ctx, items = catalog
    result = mapping_service.preview(ctx.db, 1, ctx.access.public_id, conflict_body(items))
    ctx.db.commit()
    assert result['valid'] is False
    assert {row['code'] for row in result['conflicts']} == {'COLOR_AMBIGUOUS', 'SPEC_AMBIGUOUS', 'CUSTOMER_SKU_DUPLICATE'}
    assert all(set(row['item_ids']) == {item.public_id for item in items} for row in result['conflicts'])
    assert len(result['items']) == 2 and result['base_version'] == 0
    assert ctx.access.mapping_version == 0
    assert ctx.db.scalar(select(func.count()).select_from(MappingRevision)) == 0
    with pytest.raises(PortalError) as caught:
        mapping_service.publish(ctx.db, 1, ctx.access.public_id, 1, conflict_body(items))
    assert caught.value.code == 'MAPPING_CONFLICT' and caught.value.issues == []


def test_preview_conflicts_never_bypass_employee_scope(catalog):
    ctx, items = catalog
    with pytest.raises(PortalError) as caught:
        mapping_service.preview(ctx.db, 2, ctx.access.public_id, conflict_body(items))
    assert caught.value.status == 404 and caught.value.issues == []


def test_valid_preview_explicitly_allows_publication(catalog):
    ctx, _ = catalog
    body = MappingInput(base_version=0, entries=[])
    preview = mapping_service.preview(ctx.db, 1, ctx.access.public_id, body)
    assert preview['valid'] is True and preview['conflicts'] == []
    result = mapping_service.publish(ctx.db, 1, ctx.access.public_id, preview['row_version'], body)
    ctx.db.commit()
    assert result['mapping_version'] == 1
