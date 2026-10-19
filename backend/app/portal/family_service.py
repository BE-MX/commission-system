"""Product families and color swatches: customer-facing grouping over exact catalog SKUs.

Families own quantity rules in sale units; member items inherit them so the
existing quote/inventory validation keeps working on item columns unchanged.
Grade and family are explicit administrator decisions, never parsed from names.
"""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select

from app.invoice import price_service
from app.portal import admin_service as admin, catalog_admin_service, image_service
from app.portal.domain import normalize_text, require_version
from app.portal.errors import reject
from app.portal.models import AuditEvent, CatalogItem, ColorSwatch, ProductFamily


GRADES = ("standard", "super", "ultra")
STANDARD_SUPER = ["standard", "super"]
# Business defaults from the 2026-10 order-site brief; editable afterwards in the admin page.
DEFAULT_FAMILIES = (
    {"code": "genius_weft_20g", "display_name": "Genius Weft 20g/piece", "sale_unit": "piece",
     "unit_weight_grams": "20", "min_qty": 1, "step_qty": 1, "out_of_stock_below": "30"},
    {"code": "genius_weft_50g", "display_name": "Genius Weft 50g/piece", "sale_unit": "piece",
     "unit_weight_grams": "50", "min_qty": 1, "step_qty": 1, "out_of_stock_below": "8"},
    {"code": "tape_hair", "display_name": "Tape Hair", "sale_unit": "piece",
     "unit_weight_grams": "2.5", "min_qty": 10, "step_qty": 10, "out_of_stock_below": "80"},
    {"code": "k_tip", "display_name": "K Tip", "sale_unit": "strand",
     "unit_weight_grams": "1", "min_qty": 25, "step_qty": 25, "out_of_stock_below": "200"},
    {"code": "nano_tip", "display_name": "Nano Tip", "sale_unit": "strand",
     "unit_weight_grams": "1", "min_qty": 25, "step_qty": 25, "out_of_stock_below": "200"},
    {"code": "butterfly_weft", "display_name": "Butterfly Weft (Genius Holes Weft)", "sale_unit": "piece",
     "unit_weight_grams": "60", "min_qty": 1, "step_qty": 1, "out_of_stock_below": "5"},
    {"code": "invisible_tape_hair", "display_name": "Invisible Tape Hair", "sale_unit": "piece",
     "unit_weight_grams": "2.5", "min_qty": 10, "step_qty": 10, "out_of_stock_below": "80",
     "allowed_grades": ["super"], "status": "disabled"},
)
FAMILY_FIELDS = ("display_name", "unit_weight_grams", "min_qty", "step_qty", "out_of_stock_below",
                 "allowed_grades", "sort_order", "status")


def color_key(value):
    """Same normalization as pricing, plus '-' and '/' treated as one separator."""
    return price_service.normalize_color(normalize_text(value or "")).replace("/", "-").replace(" ", "")


def _fixed(value):
    return format(value, "f") if isinstance(value, Decimal) else value


def family_view(row, counts=None):
    counts = counts or {}
    return {"id": row.public_id, "code": row.code, "row_version": row.row_version, "sale_unit": row.sale_unit,
            **{key: _fixed(getattr(row, key)) for key in FAMILY_FIELDS},
            "item_counts": {grade: counts.get((row.id, grade), {"total": 0, "published": 0}) for grade in GRADES}}


def _audit(db, actor, object_type, public_id, action, before, after, reason, diff):
    db.add(AuditEvent(actor_type="employee", actor_id=actor["id"], object_type=object_type,
        object_public_id=public_id, action=action, before_version=before, after_version=after,
        reason=reason, trace_id=str(uuid4()), safe_diff_json=diff))


def _family(db, site, code, *, lock=False):
    query = select(ProductFamily).where(ProductFamily.site_id == site.id, ProductFamily.code == code)
    if lock:
        query = query.with_for_update()
    row = db.scalar(query.execution_options(populate_existing=True))
    if row is None:
        reject("RESOURCE_NOT_FOUND", "产品族不存在或不属于当前站点。", 404)
    return row


def inherit(item, family):
    """Family quantity rules are authoritative; buffer converts sale units to inventory units."""
    item.min_qty, item.step_qty = family.min_qty, family.step_qty
    item.safety_buffer = Decimal(family.out_of_stock_below) * Decimal(item.conversion_factor)


def list_families(db, actor_id):
    admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    rows = db.scalars(select(ProductFamily).where(ProductFamily.site_id == site.id)
                      .order_by(ProductFamily.sort_order, ProductFamily.id)).all()
    counts = {}
    for family_id, grade, status, total in db.execute(select(CatalogItem.family_id, CatalogItem.grade,
            CatalogItem.status, func.count()).where(CatalogItem.site_id == site.id, CatalogItem.family_id.is_not(None))
            .group_by(CatalogItem.family_id, CatalogItem.grade, CatalogItem.status)):
        entry = counts.setdefault((family_id, grade), {"total": 0, "published": 0})
        entry["total"] += total
        if status == "published":
            entry["published"] += total
    return {"items": [family_view(row, counts) for row in rows]}


def seed_defaults(db, actor_id, reason):
    """Create missing default families only; existing configuration is never overwritten."""
    actor = admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    existing = set(db.scalars(select(ProductFamily.code).where(ProductFamily.site_id == site.id)))
    created = []
    for order, spec in enumerate(DEFAULT_FAMILIES):
        if spec["code"] in existing:
            continue
        row = ProductFamily(site_id=site.id, sort_order=(order + 1) * 10, row_version=1,
            allowed_grades=list(spec.get("allowed_grades", STANDARD_SUPER)), status=spec.get("status", "enabled"),
            **{key: Decimal(value) if key in {"unit_weight_grams", "out_of_stock_below"} else value
               for key, value in spec.items() if key not in {"allowed_grades", "status"}})
        db.add(row)
        db.flush()
        _audit(db, actor, "product_family", row.public_id, "family_created", 0, 1, reason, {"code": row.code})
        created.append(row.code)
    db.flush()
    return {"created": created, **list_families(db, actor_id)}


def update_family(db, actor_id, code, expected, body):
    actor = admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    family = _family(db, site, code, lock=True)
    require_version(family.row_version, expected)
    before = {key: _fixed(getattr(family, key)) for key in FAMILY_FIELDS}
    for key in FAMILY_FIELDS:
        value = getattr(body, key)
        setattr(family, key, Decimal(value) if key in {"unit_weight_grams", "out_of_stock_below"} else value)
    family.row_version += 1
    items = db.scalars(select(CatalogItem).where(CatalogItem.family_id == family.id)
                       .order_by(CatalogItem.id).with_for_update()).all()
    for item in items:
        inherit(item, family)
        item.row_version += 1
    db.flush()
    impact = catalog_admin_service.invalidate_items(db, site.id, [item.id for item in items])
    after = {key: _fixed(getattr(family, key)) for key in FAMILY_FIELDS}
    _audit(db, actor, "product_family", family.public_id, "family_updated", expected, family.row_version,
           body.reason, {"before": before, "after": after, "items": len(items), **impact})
    db.flush()
    return {**family_view(family), "updated_items": len(items), **impact}


def assign_items(db, actor_id, body):
    """All-or-nothing: one mismatched item rejects the whole batch."""
    actor = admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    family = _family(db, site, body.family_code, lock=True) if body.family_code else None
    wanted = [str(value) for value in body.item_ids]
    items = db.scalars(select(CatalogItem).where(CatalogItem.site_id == site.id,
        CatalogItem.public_id.in_(wanted)).order_by(CatalogItem.id).with_for_update()
        .execution_options(populate_existing=True)).all()
    if len(items) != len(wanted):
        reject("RESOURCE_NOT_FOUND", "部分商品不存在或不属于当前站点。", 404)
    if family is not None:
        wrong = [item.display_name for item in items if item.sale_unit != family.sale_unit]
        if wrong:
            reject("INVALID_INPUT", f"销售单位与产品族（{family.sale_unit}）不一致：{', '.join(wrong[:5])}", 422)
    for item in items:
        before = item.row_version
        item.family_id, item.grade = (family.id, body.grade) if family else (None, None)
        if family is not None:
            inherit(item, family)
        item.row_version += 1
        _audit(db, actor, "catalog_item", item.public_id, "catalog_family_assigned", before, item.row_version,
               body.reason, {"family_code": body.family_code, "grade": body.grade})
    db.flush()
    impact = catalog_admin_service.invalidate_items(db, site.id, [item.id for item in items])
    return {"assigned": len(items), "family_code": body.family_code, "grade": body.grade, **impact}


# ── color swatches ────────────────────────────────────────────

def swatch_view(db, row, usage=None):
    color_type, source = price_service.resolve_color_type(db, row.color_code)
    return {"id": row.public_id, "row_version": row.row_version, "color_key": row.color_key,
            "color_code": row.color_code, "display_name": row.display_name, "status": row.status,
            "image_asset_id": row.image_asset_id.split(":", 1)[0] if row.image_asset_id else None,
            "color_type": color_type, "color_type_source": source,
            "item_count": (usage or {}).get(row.color_key, 0)}


def _usage(db, site):
    usage = {}
    for (standard,) in db.execute(select(CatalogItem.standard_json).where(
            CatalogItem.site_id == site.id, CatalogItem.status != "disabled")):
        key = color_key(standard.get("color") if isinstance(standard, dict) else "")
        if key:
            usage[key] = usage.get(key, 0) + 1
    return usage


def list_swatches(db, actor_id, *, keyword=None, missing_image=False):
    admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    query = select(ColorSwatch).where(ColorSwatch.site_id == site.id)
    if keyword:
        query = query.where(ColorSwatch.color_code.contains(keyword, autoescape=True))
    if missing_image:
        query = query.where(ColorSwatch.image_asset_id.is_(None))
    rows = db.scalars(query.order_by(ColorSwatch.color_key).limit(1000)).all()
    usage = _usage(db, site)
    known = {row.color_key for row in db.scalars(select(ColorSwatch).where(ColorSwatch.site_id == site.id))}
    return {"items": [swatch_view(db, row, usage) for row in rows],
            "unregistered_colors": sorted(key for key in usage if key not in known)}


def sync_swatches(db, actor_id, reason):
    """Register every catalog color without a swatch row; images are bound separately."""
    actor = admin.begin(db, actor_id, "portal_site:admin")
    site = admin.site_for_admin(db)
    known = set(db.scalars(select(ColorSwatch.color_key).where(ColorSwatch.site_id == site.id)))
    created = {}
    for (standard,) in db.execute(select(CatalogItem.standard_json).where(
            CatalogItem.site_id == site.id, CatalogItem.status != "disabled").order_by(CatalogItem.id)):
        code = standard.get("color") if isinstance(standard, dict) else None
        key = color_key(code)
        if not key or key in known or key in created or len(key) > 64:
            continue
        display = normalize_text(code)
        created[key] = display if display.startswith("#") else "#" + display
    for key, code in created.items():
        row = ColorSwatch(site_id=site.id, color_key=key, color_code=code[:64], status="enabled", row_version=1)
        db.add(row)
        db.flush()
        _audit(db, actor, "color_swatch", row.public_id, "swatch_registered", 0, 1, reason, {"color_key": key})
    db.flush()
    return {"created": sorted(created)}


def update_swatch(db, actor_id, public_id, expected, body):
    actor = admin.begin(db, actor_id, "portal_site:admin")
    if body.asset_id is not None or not body.keep_image:
        admin.employee_principal(db, actor_id, "asset:admin")
    site = admin.site_for_admin(db)
    row = db.scalar(select(ColorSwatch).where(ColorSwatch.site_id == site.id,
        ColorSwatch.public_id == str(public_id)).with_for_update().execution_options(populate_existing=True))
    if row is None:
        reject("RESOURCE_NOT_FOUND", "色块不存在或不属于当前站点。", 404)
    require_version(row.row_version, expected)
    if color_key(body.color_code) != row.color_key:
        reject("INVALID_INPUT", "色号写法只能调整格式，不能改成其他色号。", 422)
    previous = row.image_asset_id
    if body.asset_id is not None:
        asset = image_service.asset_row(db, body.asset_id)
        reference = image_service.approved_reference(asset, image_service.storage_snapshot(db, asset.storage_path))
        if reference != body.asset_reference:
            reject("IMAGE_CHANGED", "素材版本已变化，请重新预览并确认。", 409)
        row.image_asset_id = reference
    elif not body.keep_image:
        row.image_asset_id = None
    row.color_code, row.display_name, row.status = body.color_code, body.display_name or None, body.status
    row.row_version += 1
    _audit(db, actor, "color_swatch", row.public_id, "swatch_updated", expected, row.row_version, body.reason,
           {"previous_image_asset_id": previous, "image_asset_id": row.image_asset_id, "status": row.status})
    db.flush()
    return swatch_view(db, row)
