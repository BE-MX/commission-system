"""Native accessory pricing uses local SKU identity, never external numeric IDs."""
from decimal import Decimal
import re
from sqlalchemy import or_, select
from app.catalog.models import CatalogProduct, CatalogSku
from app.catalog.query_service import catalog
from app.invoice.models import StdPrice


def snapshot(product, sku):
    return {"product_id": f"ark:product:{product.id}", "sku_id": f"ark:sku:{sku.id}",
            "accessory_name": product.display_name or product.name,
            "accessory_model": product.model or "", "accessory_color": sku.color}


def identity(db, product_id, sku_id):
    if not re.fullmatch(r"ark:product:[1-9]\d*", str(product_id)) or not re.fullmatch(r"ark:sku:[1-9]\d*", str(sku_id)):
        raise ValueError("配件需要明确的本地商品和SKU标识")
    pair = db.execute(catalog().where(CatalogProduct.kind == "accessory",
        CatalogProduct.id == int(product_id.rsplit(":", 1)[1]),
        CatalogSku.id == int(sku_id.rsplit(":", 1)[1]))).first()
    if pair is None:
        raise ValueError("本地配件不存在、已停用或SKU不属于该商品")
    return pair


def search_candidates(db, keyword, limit=50):
    query = catalog().where(CatalogProduct.kind == "accessory")
    if keyword and keyword.strip():
        term = f"%{keyword.strip()}%"
        query = query.where(or_(CatalogProduct.name.ilike(term), CatalogProduct.model.ilike(term),
                               CatalogSku.color.ilike(term), CatalogSku.code.ilike(term)))
    return [snapshot(*pair) for pair in db.execute(query.order_by(CatalogProduct.id, CatalogSku.id)
                                                  .limit(min(max(int(limit), 1), 50))).all()]


def list_prices(db, keyword=None, customer_id=None, active_only=False, currency=None):
    from app.invoice import price_service
    from app.invoice.accessory_price_service import _serialize_price
    query = select(StdPrice, CatalogProduct, CatalogSku).select_from(StdPrice).join(
        CatalogSku, CatalogSku.id == StdPrice.local_sku_id).join(CatalogProduct, CatalogProduct.id == CatalogSku.product_id)
    query = query.where(StdPrice.product_kind == "accessory")
    if active_only:
        query = query.where(CatalogSku.active.is_(True), CatalogProduct.active.is_(True), CatalogProduct.kind == "accessory")
    if currency:
        query = query.where(StdPrice.currency == currency.strip().upper())
    if keyword and keyword.strip():
        term = f"%{keyword.strip()}%"
        query = query.where(or_(CatalogProduct.name.ilike(term), CatalogProduct.model.ilike(term), CatalogSku.color.ilike(term)))
    rule = price_service.get_customer_rule_row(db, customer_id) if customer_id else None
    return [{**_serialize_price(row, rule), **snapshot(product, sku), "source": "local"}
            for row, product, sku in db.execute(query.order_by(StdPrice.id)).all()]


def upsert_price(db, payload, user_id):
    product, sku = identity(db, payload.product_id, payload.sku_id)
    from app.inventory.service import _validate_skus
    _validate_skus(db, [sku.id])
    product, sku = identity(db, payload.product_id, payload.sku_id)
    row = db.get(StdPrice, payload.id) if payload.id is not None else None
    if payload.id is not None and (row is None or row.product_kind != "accessory" or row.local_sku_id is None):
        raise ValueError("本地配件价格记录不存在")
    existing = db.scalar(select(StdPrice).where(StdPrice.local_sku_id == sku.id))
    if existing is not None and existing is not row:
        raise ValueError("该本地配件已配置标准价，请编辑现有记录")
    if row is None:
        row = StdPrice(product_kind="accessory", local_sku_id=sku.id)
        db.add(row)
    row.local_sku_id = sku.id
    row.accessory_name, row.accessory_model, row.accessory_color = product.display_name, product.model, sku.color
    row.price, row.currency, row.updated_by = Decimal(payload.price), payload.currency.upper(), user_id
    return row


def resolve_configured_price(db, *, customer_id, product_id, sku_id, currency):
    from app.invoice import price_service
    product, sku = identity(db, product_id, sku_id)
    row = db.scalar(select(StdPrice).where(StdPrice.local_sku_id == sku.id, StdPrice.product_kind == "accessory"))
    if row is None or row.currency.upper() != currency.upper():
        raise ValueError("本地配件尚未配置当前币种标准价")
    standard = Decimal(row.price).quantize(Decimal("0.0001"))
    rule = price_service.get_customer_rule_row(db, customer_id)
    return {"standard_price": standard, "customer_price": price_service.apply_rule(standard, rule),
            "currency": row.currency, **snapshot(product, sku)}
