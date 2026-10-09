from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context
from app.portal import mapping_service as mapping
from app.portal.models import CatalogItem, CatalogGrant, MappingRevision
from app.portal.schemas import MappingInput
from app.portal.errors import PortalError


@pytest.fixture
def catalog(managed):
    ctx = managed
    items = []
    for number, shade in enumerate(("Black", "Brown"), start=1):
        item = CatalogItem(site_id=ctx.site.id, product_kind="hair", source_namespace="okki:test",
            product_id="101", sku_id=str(number), standard_fingerprint=str(number)*64,
            standard_json={"model_key": "model:101", "color_key": f"color:{number}", "length": "20", "weight": "20"},
            display_name="Standard Straight", color_name=shade, status="published", inventory_unit="g",
            sale_unit="pack", conversion_factor="20")
        ctx.db.add(item)
        ctx.db.flush()
        ctx.db.add(CatalogGrant(access_id=ctx.access.id, catalog_item_id=item.id))
        items.append(item)
    ctx.db.commit()
    return ctx, items


def body(base=0):
    return MappingInput(base_version=base, entries=[
        {"kind": "model", "source_key": "model:101", "display_value": "Silk Collection"},
        {"kind": "color", "source_key": "color:1", "display_value": "Midnight"}])


def test_preview_is_read_only_and_publish_retains_standard_identity(catalog):
    ctx, items = catalog
    originals = [(item.sku_id, deepcopy(item.standard_json), item.standard_fingerprint) for item in items]
    view = mapping.preview(ctx.db, 1, ctx.access.public_id, body())
    ctx.db.commit()
    assert view["items"][0]["model_name"] == "Silk Collection"
    assert view["items"][0]["color_name"] == "Midnight"
    assert ctx.db.scalar(select(func.count()).select_from(MappingRevision)) == 0
    result = mapping.publish(ctx.db, 1, ctx.access.public_id, 1, body())
    ctx.db.commit()
    assert result["mapping_version"] == 1 and ctx.access.row_version == 2
    assert mapping.current_projection(ctx.db, ctx.access)[0]["item_id"] == items[0].public_id
    assert originals == [(item.sku_id, item.standard_json, item.standard_fingerprint) for item in items]


def test_stale_publish_does_not_overwrite_other_editor(catalog):
    ctx, _ = catalog
    mapping.preview(ctx.db, 1, ctx.access.public_id, body())
    ctx.db.commit()
    mapping.publish(ctx.db, 1, ctx.access.public_id, 1, body())
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        mapping.publish(ctx.db, 1, ctx.access.public_id, 1, body())
    assert error.value.code == "VERSION_CONFLICT"
    assert ctx.db.scalar(select(func.count()).select_from(MappingRevision)) == 1


def test_publish_revalidates_conflict_even_after_successful_preview(catalog):
    ctx, _ = catalog
    mapping.preview(ctx.db, 1, ctx.access.public_id, body())
    ctx.db.commit()
    conflict = MappingInput(base_version=0, entries=[
        {"kind": "color", "source_key": "color:1", "display_value": "Natural"},
        {"kind": "color", "source_key": "color:2", "display_value": "Natural"}])
    with pytest.raises(PortalError) as error:
        mapping.publish(ctx.db, 1, ctx.access.public_id, 1, conflict)
    assert error.value.code == "MAPPING_CONFLICT"
    assert ctx.access.mapping_version == 0
    assert ctx.db.scalar(select(func.count()).select_from(MappingRevision)) == 0


def test_new_revision_preserves_previous_projection(catalog):
    ctx, _ = catalog
    mapping.publish(ctx.db, 1, ctx.access.public_id, 1, body())
    ctx.db.commit()
    first = ctx.db.scalar(select(MappingRevision))
    snapshot = deepcopy(first.snapshot_json)
    mapping.publish(ctx.db, 1, ctx.access.public_id, 2, MappingInput(base_version=1, entries=[]))
    ctx.db.commit()
    assert first.snapshot_json == snapshot and first.version == 1
    assert mapping.current_projection(ctx.db, ctx.access)[0]["model_name"] == "Standard Straight"


@pytest.mark.parametrize("operation", ["read", "preview", "publish"])
def test_mapping_rejects_other_salesperson(catalog, operation):
    ctx, _ = catalog
    with pytest.raises(PortalError) as error:
        if operation == "read":
            mapping.get_mapping(ctx.db, 2, ctx.access.public_id)
        elif operation == "preview":
            mapping.preview(ctx.db, 2, ctx.access.public_id, body())
        else:
            mapping.publish(ctx.db, 2, ctx.access.public_id, 1, body())
    assert error.value.status == 404


def test_unknown_sku_cannot_enter_mapping(catalog):
    ctx, _ = catalog
    identifier = str(uuid4())
    invalid = MappingInput(base_version=0, entries=[{"kind": "sku", "source_key": identifier,
        "item_id": identifier, "display_value": "Foreign SKU", "customer_sku": "C-01"}])
    with pytest.raises(PortalError) as error:
        mapping.publish(ctx.db, 1, ctx.access.public_id, 1, invalid)
    assert error.value.status == 404


def test_published_projection_detects_corrupted_snapshot(catalog):
    ctx, _ = catalog
    mapping.publish(ctx.db, 1, ctx.access.public_id, 1, body())
    ctx.db.commit()
    # Deliberately bypass ORM evidence guards to verify persisted digest protection.
    ctx.db.execute(MappingRevision.__table__.update().values(digest="f"*64))
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        mapping.current_projection(ctx.db, ctx.access)
    assert error.value.code == "MAPPING_UNAVAILABLE"


def test_mapping_removal_keeps_remaining_customer_projection(catalog):
    ctx, items = catalog
    mapping.publish(ctx.db, 1, ctx.access.public_id, 1, body())
    ctx.db.commit()
    grant = ctx.db.scalar(select(CatalogGrant).where(CatalogGrant.catalog_item_id == items[0].id))
    grant.status = "disabled"
    ctx.db.commit()
    projected = mapping.current_projection(ctx.db, ctx.access)
    assert len(projected) == 1 and projected[0]["item_id"] == items[1].public_id
    assert projected[0]["model_name"] == "Silk Collection"
    with pytest.raises(PortalError) as error:
        mapping.preview(ctx.db, 1, ctx.access.public_id, body(base=1))
    assert error.value.status == 404  # New edits cannot introduce stale source keys.
    # Admin can still read source and stale entry lists to remove the obsolete alias.
    view = mapping.get_mapping(ctx.db, 1, ctx.access.public_id)
    assert len(view["sources"]) == 1 and len(view["entries"]) == 2
    corrected = MappingInput(base_version=1, entries=[
        {"kind": "model", "source_key": "model:101", "display_value": "Silk Collection"}])
    mapping.publish(ctx.db, 1, ctx.access.public_id, 2, corrected)
    ctx.db.commit()
    assert len(mapping.current_projection(ctx.db, ctx.access)) == 1
    assert mapping.current_projection(ctx.db, ctx.access)[0]["item_id"] == items[1].public_id


def test_mapping_input_rejects_hidden_foreign_item_reference():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MappingInput(base_version=0, entries=[{"kind": "model", "source_key": "model:101",
            "item_id": str(uuid4()), "display_value": "Alias"}])


def test_preview_compares_published_version_and_does_not_mutate_history(catalog):
    ctx, _ = catalog
    first = mapping.preview(ctx.db, 1, ctx.access.public_id, body())
    assert first['change_counts'] == {'added': 2, 'modified': 0, 'removed': 0}
    mapping.publish(ctx.db, 1, ctx.access.public_id, 1, body()); ctx.db.commit()
    saved = deepcopy(ctx.db.scalar(select(MappingRevision)).snapshot_json)
    draft = MappingInput(base_version=1, entries=[
        {'kind': 'model', 'source_key': 'model:101', 'display_value': 'Silk Premium'},
        {'kind': 'color', 'source_key': 'color:2', 'display_value': 'Chocolate'}])
    result = mapping.preview(ctx.db, 1, ctx.access.public_id, draft)
    assert result['base_version'] == 1
    assert result['change_counts'] == {'added': 1, 'modified': 1, 'removed': 1}
    changes = {row['source_key']: row for row in result['changes']}
    assert changes['model:101']['before']['display_value'] == 'Silk Collection'
    assert changes['model:101']['after']['display_value'] == 'Silk Premium'
    assert changes['color:1']['after'] is None
    assert ctx.db.scalar(select(MappingRevision)).snapshot_json == saved
    assert mapping.preview(ctx.db, 1, ctx.access.public_id, body(1))['changes'] == []
    with pytest.raises(PortalError) as error: mapping.preview(ctx.db, 1, ctx.access.public_id, body(0))
    assert error.value.code == 'VERSION_CONFLICT'


def test_mapping_diff_ignores_entry_order_and_normalizes_display():
    old = [{'kind': 'model', 'source_key': 'm', 'display_value': 'Silk'}]
    new = [{'kind': 'model', 'source_key': 'm', 'display_value': ' Silk '}]
    assert mapping.entry_changes(old, new) == []
    old = [{'kind': 'sku', 'source_key': 's', 'display_value': 'Silk', 'customer_sku': 'S1'}]
    new = [{'kind': 'sku', 'source_key': 's', 'display_value': 'Silk', 'customer_sku': 'S2'}]
    change = mapping.entry_changes(old, new)[0]
    assert change['change'] == 'modified' and change['before']['customer_sku'] == 'S1'
    assert change['after']['customer_sku'] == 'S2'
