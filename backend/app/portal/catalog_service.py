"""Customer-scoped catalog projection; raw source IDs and quantities never escape."""
from sqlalchemy import select

from app.core.config import get_settings
from app.core.time import beijing_now
from app.portal import mapping_service, pricing
from app.portal.domain import normalize_text
from app.portal.errors import PortalError, reject
from app.portal.inventory import validate_observation
from app.portal.models import CatalogGrant, CatalogItem


def load_observations(db, items):
    from app.portal.inventory_source import load
    return load(db, items)


def authorized_items(db, principal):
    return db.scalars(select(CatalogItem).join(CatalogGrant,
        CatalogGrant.catalog_item_id == CatalogItem.id).where(
        CatalogGrant.access_id == principal.access.id, CatalogGrant.status == "enabled",
        CatalogItem.site_id == principal.site.id, CatalogItem.status == "published")
        .order_by(CatalogItem.id).limit(5001)).all()


def availability(item, observation):
    if observation is None:
        return "unknown", None
    quantity = ((item.min_qty + item.step_qty - 1) // item.step_qty) * item.step_qty
    try:
        validate_observation(observation, now=beijing_now(),
            max_age_seconds=get_settings().PORTAL_INVENTORY_MAX_AGE_SECONDS,
            quantity=quantity, inventory_unit=item.inventory_unit,
            conversion_factor=item.conversion_factor, safety_buffer=item.safety_buffer,
            minimum=item.min_qty, step=item.step_qty)
    except PortalError as error:
        if error.code == "STOCK_CHANGED":
            return "unavailable", observation.observed_at.isoformat()
        if error.code in {"INVENTORY_UNAVAILABLE", "INVALID_INPUT"}:
            return "unknown", None
        raise
    return "available", observation.observed_at.isoformat()


def projected_items(db, principal):
    principal.require("catalog")
    rows = authorized_items(db, principal)
    try:
        projection = mapping_service.current_projection(db, principal.access)
    except PortalError as error:
        reject(error.code, "The catalog configuration needs review. Please contact your representative.", error.status)
    by_id = {entry["item_id"]: entry for entry in projection}
    observations = load_observations(db, rows)
    result = []
    for row in rows:
        alias = by_id[row.public_id]
        state, observed_at = availability(row, observations.get(row.public_id))
        item = {"item_id": row.public_id, "category": row.product_kind,
            "model_name": alias["model_name"], "color_name": alias["color_name"],
            "customer_sku": alias["customer_sku"], "length_display": str(alias["length"]),
            "weight_display": str(alias["weight"]), "sale_unit": row.sale_unit,
            "image_url": f"/api/portal/v1/catalog/{row.public_id}/image?version={row.row_version}" if row.image_asset_id else None, "availability": state, "inventory_observed_at": observed_at,
            "min_order_qty": row.min_qty, "step_qty": row.step_qty, "currency": principal.site.currency}
        result.append((row, item))
    return result


def with_price(db, principal, row, item):
    if principal.access.can_view_price:
        try:
            price = pricing.resolve(db, principal.access, row, principal.site.currency)
            item.update(unit_price=format(price.amount, ".4f"), price_status="available")
        except PortalError as error:
            if error.code != "PRICE_UNAVAILABLE":
                raise
            item.update(unit_price=None, price_status="unavailable")
    return item


def list_catalog(db, principal, *, keyword="", category=None, in_stock_only=False,
                 page=1, page_size=24, sort="curated"):
    matches = []
    needle = normalize_text(keyword).casefold()
    for row, item in projected_items(db, principal):
        haystack = " ".join(str(item[key] or "") for key in ("model_name", "color_name", "customer_sku"))
        if needle and needle not in normalize_text(haystack).casefold():
            continue
        if category and item["category"] != category or in_stock_only and item["availability"] != "available":
            continue
        matches.append((row, item))
    if sort == "name":
        matches.sort(key=lambda pair: (normalize_text(pair[1]["model_name"]).casefold(),
            normalize_text(pair[1]["color_name"]).casefold(), pair[1]["item_id"]))
    facets = {"categories": sorted({item["category"] for _, item in matches}),
              "colors": sorted({item["color_name"] for _, item in matches})}
    selected = matches[(page - 1) * page_size:page * page_size]
    return {"items": [with_price(db, principal, row, item) for row, item in selected],
        "total": len(matches), "page": page, "page_size": page_size, "facets": facets,
        "catalog_version": principal.access.catalog_version, "mapping_version": principal.access.mapping_version}


def detail(db, principal, public_id):
    # Exact scope is checked before reading price/stock or validating unrelated mappings.
    if not any(row.public_id == str(public_id) for row in authorized_items(db, principal)):
        reject("RESOURCE_NOT_FOUND", "This item is not available.", 404)
    for row, item in projected_items(db, principal):
        if row.public_id == str(public_id):
            return with_price(db, principal, row, item)
    reject("RESOURCE_NOT_FOUND", "This item is not available.", 404)
