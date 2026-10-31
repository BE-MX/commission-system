"""Colorwork availability from active catalog SKUs and sellable local stock."""
from decimal import Decimal
from sqlalchemy import func, or_, select
from app.catalog.models import CatalogProduct, CatalogSku
from app.inventory.models import StockBalance, Warehouse
from app.core.time import beijing_now, to_beijing_time


def template_statuses(db, template_id, rule):
    from app.stock.local_query_service import local_resource_predicate
    balances = (select(StockBalance.sku_id, func.sum(StockBalance.on_hand - StockBalance.reserved).label("available"),
        func.max(StockBalance.updated_at).label("updated_at"))
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .where(Warehouse.active.is_(True), StockBalance.quality == "sellable",
            local_resource_predicate(db, StockBalance.sku_id, StockBalance.warehouse_id))
        .group_by(StockBalance.sku_id).subquery())
    query = (select(CatalogSku, balances.c.available, balances.c.updated_at)
        .join(CatalogProduct, CatalogProduct.id == CatalogSku.product_id)
        .outerjoin(balances, balances.c.sku_id == CatalogSku.id)
        .where(CatalogProduct.active.is_(True), CatalogSku.active.is_(True), local_resource_predicate(db, CatalogSku.id),
            or_(*[or_(CatalogProduct.name == prefix, CatalogProduct.name.like(prefix + "/%")) for prefix in rule["prefixes"]])))
    if rule["weight"]:
        query = query.where(CatalogSku.weight_grams == Decimal(rule["weight"].removesuffix("g")))
    totals, count, updated = {}, 0, None
    for sku, available, changed in db.execute(query):
        color = sku.color.strip()
        size = sku.size.replace('"', "").replace("inch", "").strip()
        if size.endswith(".0"):
            size = size[:-2]
        if not color or not size:
            continue
        key = f"{color}|{size}"
        totals[key] = totals.get(key, 0) + int(available or 0)
        count += 1
        if changed is not None and (updated is None or changed > updated):
            updated = changed
    return {"template_id": template_id, "unmapped": False,
        "statuses": {key: "restocking" if value <= 0 else "low_stock" if value < 20 else "normal" for key, value in totals.items()},
        "matched_products": count, "source_synced_at": to_beijing_time(updated).isoformat() if updated else None,
        "synced_at": to_beijing_time(beijing_now()).isoformat(), "source": "local"}
