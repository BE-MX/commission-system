"""Customer-specific product grants, independent of access activation."""
from sqlalchemy import select

from app.portal import admin_service as admin
from app.portal.domain import require_version
from app.portal.errors import reject
from app.portal.mapping_service import current_projection
from app.portal.models import CatalogGrant, CatalogItem, Quote


def granted_items(db, access):
    return db.scalars(select(CatalogItem).join(CatalogGrant,
        CatalogGrant.catalog_item_id == CatalogItem.id).where(
        CatalogGrant.access_id == access.id, CatalogGrant.status == "enabled",
        CatalogItem.site_id == access.site_id).order_by(CatalogItem.id).limit(5001)).all()


def view(db, access):
    rows = granted_items(db, access)
    if len(rows) > 5000:
        reject("CATALOG_TOO_LARGE", "客户目录超过5000个规格，请由管理员处理。", 422)
    return {**admin.access_view(access), "items": [{"id": row.public_id,
        "model_name": row.display_name, "color_name": row.color_name,
        "length": (row.standard_json or {}).get("length"), "weight": (row.standard_json or {}).get("weight"),
        "sale_unit": row.sale_unit, "status": row.status} for row in rows]}


def get_catalog(db, actor_id, public_id):
    actor = admin.begin(db, actor_id, "portal_access:read")
    access = admin.scoped_access(db, public_id, actor)
    return view(db, access)


def update_catalog(db, actor_id, public_id, expected, body):
    actor = admin.begin(db, actor_id)
    access = admin.scoped_access(db, public_id, actor)
    require_version(access.row_version, expected)
    if access.status == "review_required":
        reject("IDENTITY_REVIEW_REQUIRED", "请先复核客户身份与归属。")
    desired = [str(value) for value in body.catalog_item_ids]
    if len(desired) != len(set(desired)):
        reject("INVALID_INPUT", "商品授权列表有重复项。", 422)
    previous = granted_items(db, access)
    previous_ids = {row.public_id for row in previous}
    rows = db.scalars(select(CatalogItem).where(CatalogItem.site_id == access.site_id,
        CatalogItem.public_id.in_(desired)).execution_options(populate_existing=True)).all()
    # A withdrawn grant can be kept or removed, but never newly granted or revived.
    if len(rows) != len(desired) or any(row.status != "published" and row.public_id not in previous_ids for row in rows):
        reject("INVALID_INPUT", "新增商品必须已发布且属于当前站点。", 422)
    before = access.row_version
    admin.apply_catalog(db, access, rows)
    db.flush()
    # Added products may expose an ambiguity in an already-published alias map.
    # Validate the full effective projection before committing any grant change.
    current_projection(db, access)
    access.row_version += 1
    access.auth_version += 1
    expired = 0
    for quote in db.scalars(select(Quote).where(Quote.access_id == access.id, Quote.status == "valid")).all():
        quote.status = "expired"
        expired += 1
    admin.revoke_sessions(db, access_id=access.id)
    admin.audit(db, actor, access, access, "catalog_access_updated", before=before, reason=body.reason,
        changes={"added": sorted(set(desired) - previous_ids), "removed": sorted(previous_ids - set(desired)),
                 "catalog_version": access.catalog_version, "expired_quotes": expired})
    db.flush()
    return view(db, access)
