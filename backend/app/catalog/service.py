"""Product identity maintenance. Historical order snapshots are never rewritten."""

from sqlalchemy import func, or_, select
from sqlalchemy.exc import OperationalError

from app.catalog.models import CatalogProduct, CatalogSku


def product_dict(product):
    return {key: getattr(product, key) for key in
            ("id", "code", "name", "display_name", "kind", "model", "active", "created_at", "updated_at")}


def sku_dict(sku):
    return {key: getattr(sku, key) for key in
            ("id", "product_id", "code", "color", "size", "curl", "unit", "weight_grams", "active")}


def list_products(db, keyword=None, active=None, page=1, page_size=50):
    query = select(CatalogProduct)
    if keyword:
        query = query.where(or_(CatalogProduct.name.contains(keyword), CatalogProduct.code.contains(keyword)))
    if active is not None:
        query = query.where(CatalogProduct.active == active)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    products = db.scalars(query.order_by(CatalogProduct.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    ids = [p.id for p in products]
    skus = db.scalars(select(CatalogSku).where(CatalogSku.product_id.in_(ids)).order_by(CatalogSku.id)).all() if ids else []
    grouped = {}
    for sku in skus:
        grouped.setdefault(sku.product_id, []).append(sku_dict(sku))
    return {"items": [{**product_dict(p), "skus": grouped.get(p.id, [])} for p in products],
            "total": total, "page": page, "page_size": page_size}


def create_product(db, body):
    if db.scalar(select(CatalogProduct.id).where(CatalogProduct.code == body.code)):
        raise ValueError("产品编码已存在")
    product = CatalogProduct(**body.model_dump())
    db.add(product)
    db.flush()
    return product_dict(product)


def update_product(db, product_id, body):
    product = db.scalar(select(CatalogProduct).where(CatalogProduct.id == product_id).with_for_update())
    if product is None:
        raise ValueError("产品不存在")
    for key, value in body.model_dump().items():
        setattr(product, key, value)
    db.flush()
    return product_dict(product)


def create_sku(db, product_id, body):
    product = db.scalar(select(CatalogProduct).where(CatalogProduct.id == product_id).with_for_update())
    if product is None or not product.active:
        raise ValueError("产品不存在或已停用")
    if db.scalar(select(CatalogSku.id).where(CatalogSku.code == body.code)):
        raise ValueError("SKU 编码已存在")
    sku = CatalogSku(product_id=product_id, unit="piece", **body.model_dump())
    db.add(sku)
    db.flush()
    return sku_dict(sku)


def set_sku_status(db, sku_id, active):
    sku = db.scalar(select(CatalogSku).where(CatalogSku.id == sku_id).with_for_update())
    if sku is None:
        raise ValueError("SKU 不存在")
    sku.active = active
    db.flush()
    return sku_dict(sku)


def update_sku(db, sku_id, body):
    from app.catalog.models import CatalogExternalIdentity
    from app.inventory.models import StockLedger
    from app.invoice.models import InvoiceItem, StdPrice
    from app.stock.models import ProductionOrderItem, ProductionCart, SafetyStock
    sku = db.scalar(select(CatalogSku).where(CatalogSku.id == sku_id).with_for_update()
                    .execution_options(populate_existing=True))
    if sku is None:
        raise ValueError("SKU不存在")
    values = body.model_dump()
    if values["code"] != sku.code:
        raise ValueError("SKU编码不可更改，请新建正确SKU")
    if all(getattr(sku, key) == value for key, value in values.items()):
        return sku_dict(sku)
    # All native transaction writers take this same SKU lock before first use.
    # Current locking reads also see references committed after an RR snapshot.
    for model, column in ((StockLedger, StockLedger.sku_id), (InvoiceItem, InvoiceItem.local_sku_id),
                          (ProductionOrderItem, ProductionOrderItem.local_sku_id),
                          (CatalogExternalIdentity, CatalogExternalIdentity.sku_id), (StdPrice, StdPrice.local_sku_id),
                          (ProductionCart, ProductionCart.local_sku_id), (SafetyStock, SafetyStock.local_sku_id)):
        try:
            reference = db.scalar(select(model.id).where(column == sku_id).limit(1).with_for_update(nowait=True))
        except OperationalError as exc:
            if getattr(exc.orig, "args", (None,))[0] == 3572:
                raise ValueError("SKU正被业务使用，请刷新后重试；已引用规格不能变更") from exc
            raise
        if reference is not None:
            raise ValueError("SKU已被业务引用，不能变更物料规格；请新建正确SKU并按需停用旧SKU")
    for key, value in values.items():
        setattr(sku, key, value)
    db.flush()
    return sku_dict(sku)
