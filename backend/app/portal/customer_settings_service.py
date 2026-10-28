"""Customer-owned delivery and grant prices; never write the business mirror."""
from copy import deepcopy
from decimal import Decimal
from sqlalchemy import select
from app.invoice.models import CustomerProfile, Invoice
from app.portal import admin_service as admin
from app.portal.domain import require_version
from app.portal.errors import reject
from app.portal.models import CatalogGrant, Quote
from app.portal.catalog_access_service import granted_items


def delivery_view(db, access, account=None):
    profile = db.get(CustomerProfile, access.okki_company_id, populate_existing=True)
    delivery = profile.delivery_json if profile else None
    if delivery is None and account is not None:
        delivery = account.delivery_json
    if delivery is None:
        row = db.execute(select(Invoice.contact_name, Invoice.contact_phone, Invoice.delivery_address).where(Invoice.customer_id == access.okki_company_id,
            Invoice.delivery_address.is_not(None), Invoice.delivery_address != "")
            .order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(1)).first()
        if row is not None:
            # Free-text history cannot reliably be split into city/country fields.
            delivery = dict(contact_name=row.contact_name or "", phone=row.contact_phone or "",
                address_line1=row.delivery_address, address_line2="", city="", region="", postal_code="", country_code="")
    return {"delivery": deepcopy(delivery), "row_version": profile.delivery_version if profile else 1}


def save_delivery(db, access, expected, delivery, *, actor_id=None):
    current = delivery_view(db, access)
    require_version(current["row_version"], expected)
    profile = db.get(CustomerProfile, access.okki_company_id, populate_existing=True)
    if profile is None:
        profile = CustomerProfile(customer_id=access.okki_company_id, delivery_version=1)
        db.add(profile)
    profile.delivery_json = delivery.model_dump()
    profile.delivery_version = current["row_version"] + 1
    profile.updated_by = actor_id
    db.flush()
    return delivery_view(db, access)


def get_delivery(db, actor_id, public_id):
    actor = admin.begin(db, actor_id, "portal_access:read")
    access = admin.scoped_access(db, public_id, actor)
    return delivery_view(db, access)


def update_delivery(db, actor_id, public_id, expected, body):
    actor = admin.begin(db, actor_id)
    access = admin.scoped_access(db, public_id, actor)
    result = save_delivery(db, access, expected, body.delivery, actor_id=actor_id)
    admin.audit(db, actor, access, access, "customer_delivery.updated", changes={"delivery_version": result["row_version"]})
    return result


def price_view(db, access):
    from app.portal.browse_pricing import BrowsePrices
    rows = granted_items(db, access)
    browse = BrowsePrices(db, access, rows)
    grants = {g.catalog_item_id: g for g in db.scalars(select(CatalogGrant).where(CatalogGrant.access_id == access.id))}
    items = []
    for row in rows:
        if row.product_kind == "hair":
            standard = browse.resolve(row.standard_json).get("standard_price")
        else:
            from app.invoice.accessory_price_service import resolve_configured_price
            standard = resolve_configured_price(db, customer_id=access.okki_company_id,
                product_id=int(row.product_id), sku_id=int(row.sku_id), currency="USD").get("standard_price")
        price = grants[row.id].unit_price
        items.append({"id": row.public_id, "model_name": row.display_name, "color_name": row.color_name,
            "length": row.standard_json.get("length"), "sale_unit": row.sale_unit,
            "standard_price": format(standard, ".4f") if standard is not None else None,
            "unit_price": format(price, ".4f") if price is not None else None})
    return {"row_version": access.row_version, "items": items, "currency": "USD"}


def get_prices(db, actor_id, public_id):
    actor = admin.begin(db, actor_id, "portal_access:read")
    return price_view(db, admin.scoped_access(db, public_id, actor))


def update_prices(db, actor_id, public_id, expected, body):
    actor = admin.begin(db, actor_id)
    access = admin.scoped_access(db, public_id, actor)
    require_version(access.row_version, expected)
    if access.status == "review_required":
        reject("IDENTITY_REVIEW_REQUIRED", "请先复核客户身份与归属。")
    rows = {row.public_id: row for row in granted_items(db, access)}
    identifiers = [str(line.item_id) for line in body.items]
    if len(identifiers) != len(set(identifiers)) or any(key not in rows for key in identifiers):
        reject("INVALID_INPUT", "只可维护当前客户已授权商品且不能重复。", 422)
    before = access.row_version
    for line in body.items:
        grant = db.scalar(select(CatalogGrant).where(CatalogGrant.access_id == access.id,
            CatalogGrant.catalog_item_id == rows[str(line.item_id)].id))
        grant.unit_price = Decimal(line.unit_price) if line.unit_price is not None else None
    access.row_version += 1
    for quote in db.scalars(select(Quote).where(Quote.access_id == access.id, Quote.status == "valid")):
        quote.status = "expired"
    admin.audit(db, actor, access, access, "customer_prices.updated", before=before,
        changes={"item_count": len(identifiers)})
    db.flush()
    return price_view(db, access)
