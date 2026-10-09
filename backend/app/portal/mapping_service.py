"""Versioned customer aliases; authoritative SKU and pricing fields never change."""
from sqlalchemy import select

from app.core.time import beijing_now
from app.portal import admin_service as admin
from app.portal.domain import content_hash, normalize_text, require_version
from app.portal.errors import reject
from app.portal.mapping import analyze_mapping, project_mapping
from app.portal.models import CatalogGrant, CatalogItem, MappingRevision, OutboxEvent, Quote


SOURCE_FIELDS = ("model_key", "color_key", "length", "weight")


def catalog_sources(db, access):
    rows = db.scalars(select(CatalogItem).join(CatalogGrant,
        CatalogGrant.catalog_item_id == CatalogItem.id).where(
        CatalogGrant.access_id == access.id, CatalogGrant.status == "enabled",
        CatalogItem.site_id == access.site_id, CatalogItem.status == "published")
        .order_by(CatalogItem.id).limit(5001)).all()
    if len(rows) > 5000:
        reject("CATALOG_TOO_LARGE", "客户目录超过首版支持的5000个规格，请调整目录。", 422)
    sources = []
    for row in rows:
        standard = row.standard_json
        if not isinstance(standard, dict) or any(field not in standard for field in SOURCE_FIELDS):
            reject("STANDARD_DATA_UNAVAILABLE", "标准商品规格不完整，请先修复商品配置。", 503)
        if not all(isinstance(standard[field], str) and standard[field] for field in ("model_key", "color_key")):
            reject("STANDARD_DATA_UNAVAILABLE", "标准型号或颜色标识不可用。", 503)
        sources.append({"item_id": row.public_id, "model_key": standard["model_key"],
            "color_key": standard["color_key"], "model_name": row.display_name, "color_name": row.color_name,
            "length": standard["length"], "weight": standard["weight"], "unit": row.sale_unit,
            "product_kind": row.product_kind})
    return sources


def published_entries(db, access):
    if access.mapping_version == 0:
        return []
    revision = db.scalar(select(MappingRevision).where(MappingRevision.access_id == access.id,
        MappingRevision.version == access.mapping_version, MappingRevision.status == "published"))
    if revision is None or not isinstance(revision.snapshot_json, dict) or (
        revision.snapshot_json.get("snapshot_schema") != 1
        or not isinstance(revision.snapshot_json.get("entries"), list)
        or not isinstance(revision.snapshot_json.get("projection"), list)
    ):
        reject("MAPPING_UNAVAILABLE", "客户映射版本不可用，请联系管理员。", 503)
    if content_hash(revision.snapshot_json) != revision.digest:
        reject("MAPPING_UNAVAILABLE", "客户映射完整性校验失败。", 503)
    return revision.snapshot_json["entries"]


def current_projection(db, access):
    # This internal function expects an already authenticated/scoped access object.
    sources = catalog_sources(db, access)
    allowed = {"sku": {row["item_id"] for row in sources},
               "model": {row["model_key"] for row in sources},
               "color": {row["color_key"] for row in sources}}
    entries = published_entries(db, access)
    # Withdrawal must hide that product, not break the remaining customer catalog.
    # Retain the immutable revision; new preview/publish inputs are still strict.
    applicable = [entry for entry in entries
                  if entry.get("source_key") in allowed.get(entry.get("kind"), set())]
    return project_mapping(sources, applicable)


def get_mapping(db, actor_id, public_id):
    actor = admin.begin(db, actor_id, "portal_mapping:read")
    access = admin.scoped_access(db, public_id, actor)
    return {"access_id": access.public_id, "row_version": access.row_version,
        "mapping_version": access.mapping_version, "sources": catalog_sources(db, access),
        "entries": published_entries(db, access), "draft": None}


def customer_preview(db, actor_id, public_id):
    """Read published display projection without issuing a customer session."""
    actor = admin.begin(db, actor_id, "portal_mapping:read")
    access = admin.scoped_access(db, public_id, actor)
    return {"preview": True, "access_id": access.public_id,
        "mapping_version": access.mapping_version, "catalog_version": access.catalog_version,
        "access_status": access.status, "items": current_projection(db, access)}


def entry_changes(before, after):
    """Compare explicit aliases against the immutable published baseline."""
    def values(entries):
        return {(entry['kind'], entry['source_key']): {
            'display_value': normalize_text(entry['display_value']),
            'customer_sku': normalize_text(entry['customer_sku']) if entry.get('customer_sku') else None,
        } for entry in entries}
    old, new = values(before), values(after)
    changes = []
    for kind, source in sorted(old.keys() | new.keys()):
        previous, current = old.get((kind, source)), new.get((kind, source))
        if previous != current:
            changes.append({'kind': kind, 'source_key': source,
                'change': 'added' if previous is None else 'removed' if current is None else 'modified',
                'before': previous, 'after': current})
    return changes


def preview(db, actor_id, public_id, body):
    actor = admin.begin(db, actor_id, "portal_mapping:write")
    access = admin.scoped_access(db, public_id, actor)
    require_version(access.mapping_version, body.base_version)
    sources = catalog_sources(db, access)
    entries = [entry.model_dump(mode="json", exclude_none=True) for entry in body.entries]
    projected, conflicts = analyze_mapping(sources, entries)
    changes = entry_changes(published_entries(db, access), entries)
    return {"access_id": access.public_id, "base_version": access.mapping_version,
        "row_version": access.row_version, "items": projected, "affected_sku_count": len(projected),
        "valid": not conflicts, "conflicts": conflicts, "changes": changes,
        "change_counts": {kind: sum(row["change"] == kind for row in changes)
                          for kind in ("added", "modified", "removed")}}


def publish(db, actor_id, public_id, expected, body):
    actor = admin.begin(db, actor_id, "portal_mapping:write")
    access = admin.scoped_access(db, public_id, actor)
    require_version(access.row_version, expected)
    require_version(access.mapping_version, body.base_version)
    sources = catalog_sources(db, access)
    entries = [entry.model_dump(mode="json", exclude_none=True) for entry in body.entries]
    projected = project_mapping(sources, entries)  # Never trust a previous browser preview.
    snapshot = {"snapshot_schema": 1, "entries": entries, "projection": projected}
    before = access.row_version
    revision = MappingRevision(access_id=access.id, version=access.mapping_version + 1,
        status="published", created_by=actor["id"], published_at=beijing_now(),
        base_version=access.mapping_version, snapshot_json=snapshot, digest=content_hash(snapshot))
    db.add(revision)
    access.mapping_version += 1
    access.row_version += 1
    expired = 0
    for quote in db.scalars(select(Quote).where(Quote.access_id == access.id, Quote.status == "valid")).all():
        quote.status = "expired"
        expired += 1
    admin.audit(db, actor, access, access, "mapping_published", before=before,
        changes={"mapping_version": access.mapping_version, "affected_sku_count": len(projected), "expired_quotes": expired})
    db.flush()  # Assign the revision public ID before writing its durable notification.
    db.add(OutboxEvent(event_key=f"mapping-published:{revision.public_id}", event_type="mapping_published",
        aggregate_public_id=access.public_id, payload_json={"access_public_id": access.public_id,
            "mapping_revision_public_id": revision.public_id, "mapping_version": revision.version},
        next_attempt_at=beijing_now()))
    db.flush()
    return {"id": revision.public_id, "mapping_version": access.mapping_version,
        "row_version": access.row_version, "affected_sku_count": len(projected), "expired_quotes": expired}
