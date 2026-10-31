"""Native replenishment reads stable SKU, sellable inventory and valid sales."""
from datetime import timedelta
from decimal import Decimal
import re
from fastapi import HTTPException
from sqlalchemy import and_, case, cast, false, func, or_, select, String, true
from sqlalchemy.exc import IntegrityError
from app.catalog.models import CatalogProduct, CatalogSku
from app.catalog.query_service import weight_text
from app.core.time import beijing_today
from app.customer.models import CustomerOrder, CustomerOrderItem
from app.inventory.models import StockBalance, Warehouse
from app.invoice.models import InvoiceItem
from app.stock.models import ProductionOrder, ProductionOrderItem, SafetyStock
from app.stock.constants import calc_suggested_qty, source_label, source_code


def local_resource_predicate(db, sku, warehouse=None):
    """Only the verified physical bucket supplies local availability."""
    from app.commerce_transition.models import ResourceScope
    from app.trade.service import consumer_phase
    phase = consumer_phase(db)
    if phase == "legacy_only":
        return false()
    identity = and_(ResourceScope.resource_kind == "sku", ResourceScope.resource_key == cast(sku, String))
    if warehouse is not None:
        identity = and_(identity, or_(ResourceScope.warehouse_key == "*", ResourceScope.warehouse_key == cast(warehouse, String)))
    allowed = select(ResourceScope.id).where(identity, ResourceScope.route == "local", ResourceScope.state == "active").exists()
    blocked = select(ResourceScope.id).where(identity, or_(ResourceScope.route != "local", ResourceScope.state != "active")).exists()
    if phase == "transition" and warehouse is None:
        return allowed  # Concrete balances below still enforce their own bucket.
    return and_(~blocked, allowed if phase == "transition" else true())


def legacy_excluded_products(db):
    """A warehouse-less mirror cannot prove exclusion for any local SKU bucket."""
    from app.catalog.models import CatalogExternalIdentity
    from app.commerce_transition.models import ResourceScope
    return set(db.scalars(select(CatalogExternalIdentity.external_product_id).join(ResourceScope,
        ResourceScope.resource_key == cast(CatalogExternalIdentity.sku_id, String)).where(
        CatalogExternalIdentity.source == "okki", ResourceScope.resource_kind == "sku",
        or_(ResourceScope.route == "local", ResourceScope.state == "frozen"))))


def public_local_rows(db, keyword=None):
    stock = (select(StockBalance.sku_id, func.sum(StockBalance.on_hand - StockBalance.reserved).label("available"))
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id).where(Warehouse.active.is_(True),
            StockBalance.quality == "sellable", local_resource_predicate(db, StockBalance.sku_id, StockBalance.warehouse_id))
        .group_by(StockBalance.sku_id).subquery())
    query = (select(CatalogProduct, CatalogSku, func.coalesce(stock.c.available, 0))
        .join(CatalogSku, CatalogSku.product_id == CatalogProduct.id).outerjoin(stock, stock.c.sku_id == CatalogSku.id)
        .where(CatalogProduct.active.is_(True), CatalogSku.active.is_(True), local_resource_predicate(db, CatalogSku.id)))
    if keyword and keyword.strip():
        query = query.where(or_(CatalogProduct.name.contains(keyword.strip(), autoescape=True),
                               CatalogProduct.model.contains(keyword.strip(), autoescape=True)))
    return [{"product_id": f"ark:sku:{sku.id}", "type": product.display_name, "size": sku.size,
        "color": sku.color, "weight": weight_text(sku) if sku.weight_grams is not None else "",
        "in_stock": count > 0, "source": "local"} for product, sku, count in db.execute(query)]


def sku_id(identity):
    if not re.fullmatch(r"ark:sku:[1-9]\d*", str(identity)):
        raise ValueError("本地备货需要 ark:sku:ID，不接受未映射的外部产品编号")
    return int(identity.rsplit(":", 1)[1])


def require_sales_current(db):
    from app.trade.refresh_service import projection_status
    state = projection_status(db)
    if state["status"] != "current":
        raise HTTPException(409, "本地订单事实正在更新，请稍后刷新备货销量")
    return state


def _production():
    return (select(ProductionOrderItem).join(ProductionOrder, ProductionOrder.id == ProductionOrderItem.order_id)
        .where(ProductionOrder.transaction_mode == "local", ProductionOrder.deleted_flag == 0,
            ProductionOrder.status != 1, ProductionOrderItem.status != 1,
            ProductionOrderItem.received_qty < ProductionOrderItem.order_qty,
            ProductionOrderItem.local_sku_id.is_not(None)))


def _sales(days, db):
    from app.trade.query_service import formal_order_predicate
    from app.trade.service import consumer_phase
    from app.catalog.models import CatalogExternalIdentity
    today = beijing_today()
    if consumer_phase(db) == "transition":
        # A migrated line has a native binding; its old alias must never create
        # another contribution. Unmigrated sales need one exact tenant/SKU map.
        sku = func.coalesce(InvoiceItem.local_sku_id, CatalogExternalIdentity.sku_id)
        return (select(sku.label("sku_id"), func.sum(CustomerOrderItem.quantity).label("quantity"))
            .select_from(CustomerOrderItem).join(CustomerOrder, CustomerOrder.id == CustomerOrderItem.order_id)
            .outerjoin(InvoiceItem, and_(InvoiceItem.id == CustomerOrderItem.local_invoice_item_id,
                                        InvoiceItem.invoice_id == CustomerOrder.local_invoice_id))
            .outerjoin(CatalogExternalIdentity, and_(CustomerOrder.source_system == "okki",
                CatalogExternalIdentity.source == "okki", CatalogExternalIdentity.tenant == CustomerOrder.source_account_key,
                CatalogExternalIdentity.external_product_id == CustomerOrderItem.external_product_id,
                CatalogExternalIdentity.external_sku_id == func.coalesce(CustomerOrderItem.external_sku_id, "")))
            .where(CustomerOrderItem.projection_role == "active", CustomerOrder.is_valid_business_order.is_(True),
                formal_order_predicate(), sku.is_not(None), CustomerOrderItem.quantity_unit.in_(["piece", "pcs", "pieces"]),
                CustomerOrder.account_date.between(today - timedelta(days=days), today)).group_by(sku).subquery())
    return (select(InvoiceItem.local_sku_id.label("sku_id"),
            func.coalesce(func.sum(CustomerOrderItem.quantity), 0).label("quantity"))
        .join(CustomerOrder, CustomerOrder.id == CustomerOrderItem.order_id)
        .join(InvoiceItem, InvoiceItem.id == CustomerOrderItem.local_invoice_item_id)
        .where(CustomerOrder.local_invoice_id.is_not(None), CustomerOrderItem.projection_role == 'active',
            InvoiceItem.invoice_id == CustomerOrder.local_invoice_id, InvoiceItem.local_sku_id.is_not(None),
            CustomerOrder.is_valid_business_order.is_(True),
            formal_order_predicate(),
            CustomerOrder.account_date.between(today - timedelta(days=days), today))
        .group_by(InvoiceItem.local_sku_id).subquery())


def _projection(db, keyword=None, model=None, product_type=None, size=None, color=None, weight=None):
    stocks = (select(StockBalance.sku_id, func.sum(StockBalance.on_hand).label("on_hand"),
                     func.sum(StockBalance.on_hand - StockBalance.reserved).label("available"))
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
        .where(Warehouse.active.is_(True), StockBalance.quality == "sellable",
            local_resource_predicate(db, StockBalance.sku_id, StockBalance.warehouse_id))
        .group_by(StockBalance.sku_id).subquery())
    production = _production().subquery()
    incoming = select(production.c.local_sku_id, func.sum(production.c.order_qty - production.c.received_qty).label("quantity"),
                      func.sum(production.c.order_qty - production.c.received_qty -
                               production.c.supplied_qty + production.c.supplied_received_qty).label("available"),
                      func.max(production.c.is_urgent).label("urgent")).group_by(production.c.local_sku_id).subquery()
    sales30, sales90 = _sales(30, db), _sales(90, db)
    available = func.coalesce(stocks.c.available, 0)
    in_transit = func.coalesce(incoming.c.quantity, 0)
    threshold = func.coalesce(SafetyStock.safety_stock, 0)
    incoming_available = func.coalesce(incoming.c.available, 0)
    effective = available + incoming_available
    status = case((threshold == 0, "unset"), (effective < threshold, "shortage"),
                  (effective < threshold * Decimal("1.5"), "warning"), else_="sufficient")
    query = (select(CatalogSku.id.label("local_sku_id"), CatalogSku.code.label("sku_code"),
        CatalogProduct.name.label("product_name"), CatalogProduct.display_name.label("product_type"),
        CatalogProduct.model, CatalogSku.color, CatalogSku.size, CatalogSku.weight_grams,
        func.coalesce(sales30.c.quantity, 0).label("sales_30d"), func.coalesce(sales90.c.quantity, 0).label("sales_90d"),
        available.label("enable_count"), func.coalesce(stocks.c.on_hand, 0).label("real_count"),
        in_transit.label("production_in_transit"), effective.label("effective_enable_count"),
        incoming_available.label("available_production_in_transit"),
        threshold.label("safety_stock"), func.coalesce(SafetyStock.lead_time_days, 30).label("lead_time_days"),
        func.coalesce(SafetyStock.safety_factor, Decimal("1.5")).label("safety_factor"),
        SafetyStock.source.label("source_code"), SafetyStock.updated_at, SafetyStock.updated_by,
        func.coalesce(SafetyStock.version, 0).label("version"), incoming.c.urgent.label("has_urgent"),
        status.label("status")).select_from(CatalogSku)
        .join(CatalogProduct, CatalogProduct.id == CatalogSku.product_id)
        .outerjoin(stocks, stocks.c.sku_id == CatalogSku.id)
        .outerjoin(incoming, incoming.c.local_sku_id == CatalogSku.id)
        .outerjoin(SafetyStock, SafetyStock.local_sku_id == CatalogSku.id)
        .outerjoin(sales30, sales30.c.sku_id == CatalogSku.id)
        .outerjoin(sales90, sales90.c.sku_id == CatalogSku.id)
        .where(CatalogSku.active.is_(True), CatalogProduct.active.is_(True), local_resource_predicate(db, CatalogSku.id)))
    if keyword:
        term = f"%{keyword.strip()}%"
        query = query.where(or_(CatalogProduct.name.ilike(term), CatalogProduct.model.ilike(term), CatalogSku.code.ilike(term)))
    for value, column in ((model, CatalogProduct.model), (product_type, CatalogProduct.display_name),
                           (size, CatalogSku.size), (color, CatalogSku.color)):
        if value:
            query = query.where(column.in_([part.strip() for part in value.split(",") if part.strip()]))
    if weight:
        grams = []
        includes_unweighted = False
        for part in weight.split(","):
            matched = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*g", part.strip(), flags=re.I)
            if matched:
                grams.append(Decimal(matched[1]))
            elif part.strip() == "piece":
                includes_unweighted = True
        predicates = [CatalogSku.weight_grams.in_(grams)]
        if includes_unweighted:
            predicates.append(CatalogSku.weight_grams.is_(None))
        query = query.where(or_(*predicates))
    return query.subquery()


def production_status(db, identities):
    ids = {sku_id(value): value for value in identities}
    rows = db.execute(_production().add_columns(ProductionOrder.order_no, ProductionOrder.batch_no)
                      .where(ProductionOrderItem.local_sku_id.in_(ids)).order_by(ProductionOrderItem.id)).all() if ids else []
    result = {value: {"stock_status": "", "has_urgent": False, "items": []} for value in identities}
    for item, order_no, batch_no in rows:
        entry = result[ids[item.local_sku_id]]
        entry["has_urgent"] = entry["has_urgent"] or bool(item.is_urgent)
        entry["items"].append({"item_id": item.id, "order_no": order_no, "batch_no": batch_no,
            "product_name": item.product_name, "order_qty": item.order_qty, "received_qty": item.received_qty,
            "in_transit_qty": item.order_qty - item.received_qty, "is_urgent": bool(item.is_urgent),
            "expected_delivery_date": item.expected_delivery_date.isoformat() if item.expected_delivery_date else None})
    for entry in result.values():
        entry["stock_status"] = "加急中" if entry["has_urgent"] else "备货中" if entry["items"] else ""
    return result


def query(db, *, page=1, page_size=50, status_filter=None, sort_by="sales_30d", order="desc",
          has_in_transit=None, has_safety_stock=None, stock_status=None, all_rows=False, **filters):
    state = require_sales_current(db)
    data = _projection(db, **filters)
    statement = select(data)
    if has_in_transit is not None:
        statement = statement.where((data.c.production_in_transit > 0) == has_in_transit)
    if has_safety_stock is not None:
        statement = statement.where((data.c.safety_stock > 0) == has_safety_stock)
    if stock_status:
        statement = statement.where(data.c.production_in_transit > 0)
        if stock_status == "urgent":
            statement = statement.where(data.c.has_urgent == 1)
        elif stock_status == "stocking":
            statement = statement.where(func.coalesce(data.c.has_urgent, 0) == 0)
    scope = statement.subquery()
    summary = {f"{name}_count": 0 for name in ("shortage", "warning", "sufficient", "unset")}
    summary.update({f"{status}_count": count for status, count in db.execute(
        select(scope.c.status, func.count()).group_by(scope.c.status))})
    if status_filter:
        statement = statement.where(data.c.status.in_(status_filter))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    sort_column = {"product_id": data.c.local_sku_id, "avg_daily_sales_30d": data.c.sales_30d}.get(sort_by)
    if sort_column is None:
        sort_column = data.c[sort_by] if sort_by in {"sales_30d", "sales_90d", "model", "color", "enable_count",
            "real_count", "effective_enable_count", "production_in_transit", "safety_stock"} else data.c.sales_30d
    statement = statement.order_by(sort_column.desc() if order == "desc" else sort_column.asc(), data.c.local_sku_id)
    if not all_rows:
        statement = statement.offset((page - 1) * page_size).limit(page_size)
    rows = db.execute(statement).mappings().all()
    statuses = production_status(db, [f"ark:sku:{row['local_sku_id']}" for row in rows])
    items = []
    for row in rows:
        item = dict(row)
        identity = f"ark:sku:{row['local_sku_id']}"
        item.update(product_id=identity, source=source_label(row["source_code"]) if row["source_code"] is not None else "",
            safety_stock_source=source_label(row["source_code"]) if row["source_code"] is not None else "",
            safety_stock_updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
            updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
            avg_daily_sales_30d=round(float(row["sales_30d"]) / 30, 2),
            suggested_qty=calc_suggested_qty(row["effective_enable_count"], row["safety_stock"]),
            data_anomaly=False, cn_name=row["product_name"], transaction_mode="local",
            stock_status=statuses[identity]["stock_status"], stock_items=statuses[identity]["items"])
        for key in ("sales_30d", "sales_90d", "enable_count", "real_count", "production_in_transit",
                    "available_production_in_transit", "effective_enable_count", "safety_stock", "lead_time_days", "version"):
            item[key] = int(item[key])
        item["safety_factor"] = float(item["safety_factor"])
        item["weight_grams"] = str(item["weight_grams"]) if item["weight_grams"] is not None else None
        items.append(item)
    return {"total": total, "summary": summary, "items": items, "projection": state, "transaction_mode": "local"}


def get_sales(db, identity, days):
    require_sales_current(db)
    identity = sku_id(identity)
    sales = _sales(days, db)
    return int(db.scalar(select(sales.c.quantity).where(sales.c.sku_id == identity)) or 0)


def filter_options(db):
    from app.catalog.query_service import catalog
    rows = db.execute(catalog()).all()
    return {key: sorted({value for value in values if value}) for key, values in {
        "models": [product.model for product, sku in rows], "types": [product.display_name for product, sku in rows],
        "sizes": [sku.size for product, sku in rows], "colors": [sku.color for product, sku in rows],
        "weights": [weight_text(sku) for product, sku in rows]}.items()}


def save(db, items, lead_time_days, safety_factor, source, updated_by):
    from app.inventory.service import _validate_skus
    saved, failed = [], []
    parsed = []
    for item in items:
        try:
            parsed.append((sku_id(item.get("product_id")), item))
        except ValueError as exc:
            failed.append({"product_id": item.get("product_id"), "reason": str(exc)})
    active_ids = set(db.scalars(select(CatalogSku.id).join(CatalogProduct, CatalogProduct.id == CatalogSku.product_id)
        .where(CatalogSku.id.in_([identity for identity, item in parsed]), CatalogSku.active.is_(True),
               CatalogProduct.active.is_(True), CatalogSku.unit == "piece"))) if parsed else set()
    valid = []
    for identity, item in parsed:
        if identity not in active_ids:
            failed.append({"product_id": item["product_id"], "reason": "SKU不存在或已停用，请刷新"})
        else:
            valid.append((identity, item))
    # One ordered catalog lock set for the whole batch, including empty policies.
    # Policies are insert-first; never lock a missing unique-key range under RR.
    try:
        _validate_skus(db, [identity for identity, item in valid])
    except ValueError as exc:
        failed.extend({"product_id": item["product_id"], "reason": str(exc)} for identity, item in valid)
        db.commit()
        return {"saved": saved, "failed": failed}
    for identity_id, item in valid:
        identity = item.get("product_id")
        try:
            with db.begin_nested():
                expected = item.get("expected_version", 0)
                if expected == 0:
                    row = SafetyStock(local_sku_id=identity_id, version=0, safety_stock=item["safety_stock"],
                        lead_time_days=lead_time_days, safety_factor=Decimal(str(safety_factor)),
                        source=source_code(source), updated_by=updated_by)
                    try:
                        with db.begin_nested():
                            db.add(row)
                            db.flush()
                    except IntegrityError:
                        if db.scalar(select(SafetyStock.id).where(SafetyStock.local_sku_id == identity_id).with_for_update()) is None:
                            raise
                        raise ValueError("安全库存配置已变化，请刷新后重试") from None
                else:
                    known_id = db.scalar(select(SafetyStock.id).where(SafetyStock.local_sku_id == identity_id))
                    row = db.scalar(select(SafetyStock).where(SafetyStock.id == known_id).with_for_update()
                                    .execution_options(populate_existing=True)) if known_id is not None else None
                    if row is None or row.version != expected:
                        raise ValueError("安全库存配置已变化，请刷新后重试")
                row.safety_stock, row.lead_time_days = item["safety_stock"], lead_time_days
                row.safety_factor, row.source = Decimal(str(safety_factor)), source_code(source)
                row.updated_by, row.version = updated_by, row.version + 1
                db.flush()
            saved.append(identity)
        except ValueError as exc:
            failed.append({"product_id": identity, "reason": str(exc)})
    db.commit()
    return {"saved": saved, "failed": failed}
