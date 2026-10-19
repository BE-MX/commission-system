"""Customer view of product families: grade x length x color variants of granted SKUs.

Built entirely on catalog_service.projected_items, so authorization, customer
aliases, pricing and fail-closed inventory are identical to the flat catalog.
"""
import re

from sqlalchemy import select

from app.invoice import price_service
from app.portal import catalog_service
from app.portal.errors import reject
from app.portal.family_service import color_key
from app.portal.models import ColorSwatch, ProductFamily

GRADE_ORDER = {"standard": 0, "super": 1, "ultra": 2}
GRADE_LABELS = {"standard": "Standard Double Drawn", "super": "Super Double Drawn", "ultra": "Ultra Double Drawn"}
COLOR_TYPES = ("solid", "piano", "ombre", "balayage")


def _families(db, principal):
    return {row.id: row for row in db.scalars(select(ProductFamily).where(
        ProductFamily.site_id == principal.site.id, ProductFamily.status == "enabled"))}


def _visible(families):
    return lambda row: row.family_id in families and row.grade in families[row.family_id].allowed_grades


def _swatches(db, principal):
    return {row.color_key: row for row in db.scalars(select(ColorSwatch).where(
        ColorSwatch.site_id == principal.site.id, ColorSwatch.status == "enabled"))}


def _swatch_url(swatch):
    if swatch is None or not swatch.image_asset_id:
        return None
    return f"/api/portal/v1/catalog/swatches/{swatch.public_id}/image?version={swatch.row_version}"


def _length_key(value):
    match = re.match(r"\s*(\d+(?:\.\d+)?)", str(value or ""))
    return (0, float(match.group(1)), "") if match else (1, 0.0, str(value or ""))


def _family_head(family):
    return {"code": family.code, "display_name": family.display_name, "sale_unit": family.sale_unit,
            "unit_weight_grams": format(family.unit_weight_grams.normalize(), "f"),
            "min_order_qty": family.min_qty, "step_qty": family.step_qty}


def list_families(db, principal):
    principal.require("catalog")
    families = _families(db, principal)
    visible = _visible(families)
    rows = catalog_service.authorized_items(db, principal)
    ungrouped = sum(1 for row in rows if not visible(row))
    members = {}
    for row in rows:
        if visible(row):
            members.setdefault(row.family_id, []).append(row)
    swatches = _swatches(db, principal)
    result = []
    for family in sorted(families.values(), key=lambda value: (value.sort_order, value.id)):
        items = members.get(family.id)
        if not items:
            continue
        cover = next((f"/api/portal/v1/catalog/{row.public_id}/image?version={row.row_version}"
                      for row in items if row.image_asset_id), None)
        if cover is None:
            cover = next(filter(None, (_swatch_url(swatches.get(color_key((row.standard_json or {}).get("color"))))
                                       for row in items)), None)
        result.append({**_family_head(family), "image_url": cover, "variant_count": len(items),
            "grades": [grade for grade in sorted(family.allowed_grades, key=GRADE_ORDER.get)
                       if any(row.grade == grade for row in items)],
            "lengths": sorted({str((row.standard_json or {}).get("length") or "") for row in items} - {""},
                              key=_length_key)})
    return {"items": result, "ungrouped_count": ungrouped,
            "catalog_version": principal.access.catalog_version}


def _family_or_404(db, principal, code):
    family = db.scalar(select(ProductFamily).where(ProductFamily.site_id == principal.site.id,
        ProductFamily.code == code, ProductFamily.status == "enabled"))
    if family is None:
        reject("RESOURCE_NOT_FOUND", "This product is not available.", 404)
    return family


def family_detail(db, principal, code):
    family = _family_or_404(db, principal, code)
    families = {family.id: family}
    projected = catalog_service.projected_items(db, principal, keep=_visible(families))
    if not projected:
        reject("RESOURCE_NOT_FOUND", "This product is not available.", 404)
    swatches, color_types, variants = _swatches(db, principal), {}, []
    for row, item in projected:
        standard = row.standard_json or {}
        key = color_key(standard.get("color"))
        swatch = swatches.get(key)
        if key not in color_types:
            resolved, _ = price_service.resolve_color_type(db, standard.get("color") or "")
            color_types[key] = resolved if resolved in COLOR_TYPES else None
        catalog_service.with_price(db, principal, row, item)
        variants.append({**item, "grade": row.grade, "grade_label": GRADE_LABELS[row.grade],
            "length": str(standard.get("length") or item["length_display"]), "color_key": key,
            "color_code": swatch.color_code if swatch else item["color_name"],
            "color_label": (swatch.display_name if swatch and swatch.display_name else item["color_name"]),
            "color_type": color_types[key], "swatch_url": _swatch_url(swatch),
            "unit_weight_grams": format(family.unit_weight_grams.normalize(), "f")})
    variants.sort(key=lambda value: (GRADE_ORDER[value["grade"]], _length_key(value["length"]),
                                     COLOR_TYPES.index(value["color_type"]) if value["color_type"] else 9,
                                     value["color_code"], value["item_id"]))
    return {**_family_head(family), "grades": [grade for grade in GRADE_ORDER if any(v["grade"] == grade for v in variants)],
            "grade_labels": GRADE_LABELS, "variants": variants,
            "catalog_version": principal.access.catalog_version, "mapping_version": principal.access.mapping_version}


def family_availability(db, principal, code):
    """Stock-only refresh for polling: no price resolution, same validation path."""
    family = _family_or_404(db, principal, code)
    projected = catalog_service.projected_items(db, principal, keep=_visible({family.id: family}))
    return {"items": [{"item_id": item["item_id"], "availability": item["availability"],
                       "stock_display": item["stock_display"], "inventory_observed_at": item["inventory_observed_at"]}
                      for _, item in projected],
            "catalog_version": principal.access.catalog_version}
