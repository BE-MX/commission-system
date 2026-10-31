"""Native catalog projections for entry, public availability and bounded agents."""
from decimal import Decimal
import re
from sqlalchemy import func, or_, select
from app.catalog.models import CatalogProduct, CatalogSku
from app.inventory.models import StockBalance, Warehouse


def availability():
    return (select(StockBalance.sku_id, func.sum(StockBalance.on_hand - StockBalance.reserved).label("available"))
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .where(Warehouse.active.is_(True), StockBalance.quality == "sellable")
        .group_by(StockBalance.sku_id).subquery())


def catalog():
    return (select(CatalogProduct, CatalogSku).select_from(CatalogProduct).join(CatalogSku, CatalogSku.product_id == CatalogProduct.id)
        .where(CatalogProduct.active.is_(True), CatalogSku.active.is_(True)))


def weight_text(sku):
    return f"{format(sku.weight_grams.normalize(), 'f')}g" if sku.weight_grams is not None else sku.unit


def record(product, sku):
    return {"source": "local", "product_id": f"ark:product:{product.id}", "sku_id": f"ark:sku:{sku.id}",
        "local_product_id": product.id, "local_sku_id": sku.id, "sku_count": 1,
        "product_name": product.name, "product_display": product.display_name, "model": product.model or "",
        "color": sku.color, "size": sku.size, "unit": weight_text(sku), "product_kind": product.kind,
        "price_per_piece": None, "price_source": "missing"}


def length_expression():
    value = func.lower(CatalogSku.size)
    for suffix in ('inches', 'inch', '英寸', '寸', '"', '“', '”', '″'):
        value = func.replace(value, suffix, '')
    return func.trim(value)


def filtered(query, values, *, exclude=None):
    from app.invoice.catalog_specs import normalized_length
    for key, column in (("model", CatalogProduct.model), ("color", CatalogSku.color), ("size", CatalogSku.size)):
        value = values.get(key)
        if value and key != exclude:
            if key == "size":
                query = query.where(length_expression() == normalized_length(value))
            else:
                query = query.where(func.lower(func.trim(column)) == value.strip().casefold())
    unit = values.get("unit")
    if unit and exclude != "unit":
        weight = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*g", unit.strip().casefold())
        if weight:
            query = query.where(CatalogSku.weight_grams == Decimal(weight[1]))
        else:
            query = query.where(CatalogSku.weight_grams.is_(None), CatalogSku.unit == unit.strip())
    return query


def match_product(db, **values):
    query = filtered(catalog(), values).order_by(CatalogProduct.id, CatalogSku.id).limit(21)
    rows = db.execute(query).all()
    matches = [record(product, sku) for product, sku in rows[:20]]
    if matches:
        balance = availability()
        counts = dict(db.execute(select(balance.c.sku_id, balance.c.available).where(
            balance.c.sku_id.in_([item["local_sku_id"] for item in matches]))).all())
        for item in matches:
            item["available_stock"] = int(counts.get(item["local_sku_id"], 0))
            item["stock_warning"] = "当前无可售库存，请确认生产交期" if item["available_stock"] <= 0 else ""
    return {"is_unique": len(rows) == 1, "item": matches[0] if len(rows) == 1 else None,
            "matches": matches, "truncated": len(rows) > 20}


def filter_options(db, **values):
    result = {}
    for dim, key in (("model", "models"), ("color", "colors"), ("size", "sizes"), ("unit", "units")):
        def distinct(filters):
            query = filtered(catalog(), filters, exclude=dim)
            columns = {"model": [CatalogProduct.model], "color": [CatalogSku.color], "size": [CatalogSku.size],
                       "unit": [CatalogSku.weight_grams, CatalogSku.unit]}[dim]
            rows = db.execute(query.with_only_columns(*columns, maintain_column_froms=True).distinct().order_by(*columns).limit(501)).all()
            if dim == "unit":
                return sorted({f"{format(weight.normalize(), 'f')}g" if weight is not None else unit for weight, unit in rows})[:500]
            return [row[0] for row in rows[:500] if row[0]]
        result[key] = distinct(values)
        result[f"all_{key}"] = distinct({}) if any(value for name, value in values.items() if name != dim) else result[key]
    return result


def entry_options(db):
    result = filter_options(db)
    displays = db.scalars(catalog().with_only_columns(CatalogProduct.display_name, maintain_column_froms=True)
        .distinct().order_by(CatalogProduct.display_name).limit(500)).all()
    return {"displays": list(displays), **{key: result[key] for key in ("models", "colors", "sizes", "units")}}


def public_inventory(db, page=1, page_size=20, keyword=None, in_stock_only=False):
    stock = availability()
    query = catalog().add_columns(func.coalesce(stock.c.available, 0)).outerjoin(stock, stock.c.sku_id == CatalogSku.id)
    if keyword and keyword.strip():
        query = query.where(or_(CatalogProduct.name.contains(keyword.strip(), autoescape=True),
            CatalogProduct.model.contains(keyword.strip(), autoescape=True)))
    if in_stock_only:
        query = query.where(stock.c.available > 0)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(CatalogProduct.name, CatalogSku.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": [{"product_id": f"ark:sku:{sku.id}", "type": product.display_name,
        "size": sku.size, "color": sku.color, "weight": weight_text(sku) if sku.weight_grams is not None else "",
        "in_stock": count > 0} for product, sku, count in rows]}


def lookup_specs(db, terms, length=None):
    from app.invoice.catalog_specs import normalized_length
    query = catalog().where(or_(*[func.lower(CatalogProduct.model).contains(term.casefold(), autoescape=True) for term in terms]))
    sizes = db.scalars(query.with_only_columns(CatalogSku.size, maintain_column_froms=True).distinct()
        .order_by(CatalogSku.size).limit(31)).all()
    requested = normalized_length(length) if length else None
    if requested:
        query = query.where(length_expression() == requested)
    columns = (CatalogProduct.model, CatalogSku.size, CatalogSku.weight_grams, CatalogSku.unit)
    rows = db.execute(query.with_only_columns(*columns, maintain_column_froms=True).distinct().order_by(*columns).limit(21)).all()
    matches = [{"model": model, "size": size, "unit": f"{format(weight.normalize(), 'f')}g" if weight is not None else unit}
        for model, size, weight, unit in rows[:20]]
    return {"status": "matched" if rows else "not_found", "matched_by": "family", "requested_length": requested,
        "available_lengths": sorted({normalized_length(size) for size in sizes[:30] if size}), "matches": matches,
        "truncated": len(rows) > 20 or len(sizes) > 30, "scope": "active_catalog_specifications_only",
        "limitations": "Catalog entries are not stock availability or a sales commitment. Family matches are not one unique model."}
