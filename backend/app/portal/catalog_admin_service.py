"""Site administrators import exact source SKUs; publication is a separate action."""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import object_session

from app.core.config import get_settings
from app.portal import admin_service as admin, mapping_service, sku_source
from app.portal.domain import require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CatalogGrant, CatalogItem, CustomerAccess, ProductFamily, Quote


CONFIG_FIELDS = ("display_name", "color_name", "inventory_unit", "sale_unit",
                 "conversion_factor", "safety_buffer", "min_qty", "step_qty")


def view(item):
    return {"id": item.public_id, "row_version": item.row_version, "status": item.status,
            "product_id": item.product_id, "sku_id": item.sku_id, "image_asset_id": item.image_asset_id.split(":", 1)[0] if item.image_asset_id else None,
            "product_kind": item.product_kind, "source_namespace": item.source_namespace,
            "standard_json": item.standard_json, "standard_fingerprint": item.standard_fingerprint,
            **{key: format(getattr(item, key), "f") if isinstance(getattr(item, key), Decimal)
               else getattr(item, key) for key in CONFIG_FIELDS}}


def list_items(db, actor_id, *, page=1, page_size=20, status=None, keyword=None, family=None):
    admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    families = {row.id: row.code for row in db.scalars(select(ProductFamily).where(ProductFamily.site_id == site.id))}
    query = select(CatalogItem).where(CatalogItem.site_id == site.id)
    if status is not None:
        query = query.where(CatalogItem.status == status)
    if family == "unassigned":
        query = query.where(CatalogItem.family_id.is_(None))
    elif family is not None:
        family_id = next((key for key, code in families.items() if code == family), None)
        query = query.where(CatalogItem.family_id == family_id) if family_id else query.where(false())
    if keyword:
        query = query.where(or_(CatalogItem.display_name.contains(keyword, autoescape=True),
            CatalogItem.color_name.contains(keyword, autoescape=True),
            CatalogItem.product_id == keyword, CatalogItem.sku_id == keyword))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(CatalogItem.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{**view(row), "family_code": families.get(row.family_id), "grade": row.grade} for row in rows],
            "total": total, "page": page, "page_size": page_size}


def get_item(db, actor_id, public_id):
    admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    item = db.scalar(select(CatalogItem).where(CatalogItem.site_id == site.id,
        CatalogItem.public_id == str(public_id)).execution_options(populate_existing=True))
    if item is None:
        reject("RESOURCE_NOT_FOUND", "商品不存在或不属于当前站点。", 404)
    return view(item)


def inspect_source(db, actor_id, *, product_id, sku_id, product_kind):
    admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    namespace = get_settings().PORTAL_OKKI_NAMESPACE
    product_id, sku_id = sku_source._identity(product_id), sku_source._identity(sku_id)
    existing = db.scalar(select(CatalogItem).where(CatalogItem.site_id == site.id,
        CatalogItem.source_namespace == namespace, CatalogItem.product_id == product_id,
        CatalogItem.sku_id == sku_id).execution_options(populate_existing=True))
    if existing is not None and existing.product_kind != product_kind:
        reject("INVALID_INPUT", "已导入商品不能更换类别。", 422)
    snapshot = sku_source.load_snapshot(db, namespace=namespace, product_id=product_id,
                                       sku_id=sku_id, product_kind=product_kind)
    return {"source": snapshot, "existing_item": view(existing) if existing else None,
            "expected_version": existing.row_version if existing else 0}


def lookup_import(db, actor_id, *, product_id, sku_id):
    # Readback must work even when the mirror is unavailable after a lost response.
    admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    product_id, sku_id = sku_source._identity(product_id), sku_source._identity(sku_id)
    item = db.scalar(select(CatalogItem).where(CatalogItem.site_id == site.id,
        CatalogItem.source_namespace == get_settings().PORTAL_OKKI_NAMESPACE,
        CatalogItem.product_id == product_id, CatalogItem.sku_id == sku_id)
        .execution_options(populate_existing=True))
    return {"found": item is not None, "item": view(item) if item is not None else None}


def _apply(item, body):
    for key in CONFIG_FIELDS:
        value = getattr(body, key)
        setattr(item, key, Decimal(value) if key in {"conversion_factor", "safety_buffer"} else value)
    if item.family_id is not None:
        from app.portal.family_service import inherit
        family = object_session(item).get(ProductFamily, item.family_id)
        if family.sale_unit != item.sale_unit:
            reject("INVALID_INPUT", f"商品属于产品族，销售单位须为 {family.sale_unit}。", 422)
        inherit(item, family)


def _invalidate(db, item):
    return invalidate_items(db, item.site_id, [item.id])


def invalidate_items(db, site_id, item_ids):
    """Bump catalog versions of every customer granted any of the items, once each."""
    if not item_ids:
        return {"affected_customers": 0, "expired_quotes": 0}
    accesses = db.scalars(select(CustomerAccess).where(CustomerAccess.site_id == site_id,
        CustomerAccess.id.in_(select(CatalogGrant.access_id).where(
            CatalogGrant.catalog_item_id.in_(item_ids), CatalogGrant.status == "enabled")))
        .order_by(CustomerAccess.id).with_for_update()).all()
    for access in accesses:
        access.catalog_version += 1
        access.row_version += 1
    quotes = db.scalars(select(Quote).where(Quote.access_id.in_([access.id for access in accesses]),
                                          Quote.status == "valid")).all()
    for quote in quotes:
        quote.status = "expired"
    return {"affected_customers": len(accesses), "expired_quotes": len(quotes)}


def _audit(db, actor, item, action, before, reason, impact):
    db.add(AuditEvent(actor_type="employee", actor_id=actor["id"], object_type="catalog_item",
        object_public_id=item.public_id, action=action, before_version=before,
        after_version=item.row_version, reason=reason, trace_id=str(uuid4()),
        safe_diff_json={"status": item.status, **impact}))


def import_item(db, actor_id, expected, body):
    actor = admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    namespace = get_settings().PORTAL_OKKI_NAMESPACE
    # Canonical IDs are checked before lookup, not silently normalized to another key.
    product_id, sku_id = sku_source._identity(body.product_id), sku_source._identity(body.sku_id)
    item = db.scalar(select(CatalogItem).where(CatalogItem.site_id == site.id,
        CatalogItem.source_namespace == namespace, CatalogItem.product_id == product_id,
        CatalogItem.sku_id == sku_id).with_for_update().execution_options(populate_existing=True))
    require_version(item.row_version if item else 0, expected)
    if item is not None and item.product_kind != body.product_kind:
        reject("INVALID_INPUT", "已导入商品不能更换类别。", 422)
    snapshot = sku_source.load_snapshot(db, namespace=namespace, product_id=product_id,
                                       sku_id=sku_id, product_kind=body.product_kind)
    if snapshot["standard_fingerprint"] != body.standard_fingerprint:
        reject("SKU_CHANGED", "标准规格已变化，请重新预览并核对单位换算。")
    before = item.row_version if item else 0
    if item is None:
        item = CatalogItem(site_id=site.id, **snapshot, status="draft")
        db.add(item)
    else:
        item.standard_json = snapshot["standard_json"]
        item.standard_fingerprint = snapshot["standard_fingerprint"]
        item.status = "draft"
        item.row_version += 1
    _apply(item, body)
    db.flush()
    impact = _invalidate(db, item)
    _audit(db, actor, item, "catalog_imported", before, body.reason, impact)
    db.flush()
    return {**view(item), **impact}


def update_item(db, actor_id, public_id, expected, body):
    actor = admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    item = db.scalar(select(CatalogItem).where(CatalogItem.site_id == site.id,
        CatalogItem.public_id == str(public_id)).with_for_update().execution_options(populate_existing=True))
    if item is None:
        reject("RESOURCE_NOT_FOUND", "商品不存在或不属于当前站点。", 404)
    require_version(item.row_version, expected)
    if body.status == "published":
        sku_source.revalidate(db, item)
    before = item.row_version
    _apply(item, body)
    item.status = body.status
    item.row_version += 1
    if item.status == "published":
        db.flush()
        accesses = db.scalars(select(CustomerAccess).where(CustomerAccess.site_id == item.site_id,
            CustomerAccess.id.in_(select(CatalogGrant.access_id).where(
                CatalogGrant.catalog_item_id == item.id, CatalogGrant.status == "enabled")))).all()
        for access in accesses:
            mapping_service.current_projection(db, access)
    impact = _invalidate(db, item)
    _audit(db, actor, item, "catalog_updated", before, body.reason, impact)
    db.flush()
    return {**view(item), **impact}
