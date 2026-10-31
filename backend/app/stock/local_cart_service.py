"""Native replenishment cart creates journaled production orders atomically."""
import hashlib
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from app.auth.models import ArkUser
from app.catalog.models import CatalogProduct, CatalogSku
from app.inventory.service import _validate_skus
from app.semifinished.inventory_service import qty
from app.semifinished.models import CartPlan, SemifinishedMaterial, SemifinishedOrder
from app.stock.models import ProductionCart, ProductionOrder, ProductionOrderItem
from app.stock.local_query_service import sku_id


def _lock_user(db, user_id):
    row = db.execute(select(ArkUser.id, ArkUser.is_active, ArkUser.deleted_at).where(ArkUser.id == user_id).with_for_update()).first()
    if row is None or not row.is_active or row.deleted_at is not None:
        raise ValueError("当前账号不可用")


def _rows(db, user_id, ids=None, *, lock=False):
    statement = select(ProductionCart).where(ProductionCart.user_id == user_id, ProductionCart.local_sku_id.is_not(None))
    if ids is not None:
        statement = statement.where(ProductionCart.id.in_(ids))
    statement = statement.order_by(ProductionCart.id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalars(statement).all()


def list_items(db, user_id, ids=None):
    rows = _rows(db, user_id, ids)
    plans = db.scalars(select(CartPlan).where(CartPlan.production_cart_id.in_([row.id for row in rows]))).all() if rows else []
    return [{"id": row.id, "local_sku_id": row.local_sku_id, "product_id": f"ark:sku:{row.local_sku_id}",
        "product_name": row.product_name, "model": row.model, "spec_info": row.spec_info,
        "order_qty": row.order_qty, "remark": row.remark, "created_at": row.created_at.isoformat(),
        "semifinished_items": [{"material_id": plan.material_id, "quantity_grams": plan.quantity_grams}
                              for plan in plans if plan.production_cart_id == row.id]} for row in rows]


def count(db, user_id):
    return db.scalar(select(func.count()).select_from(ProductionCart).where(
        ProductionCart.user_id == user_id, ProductionCart.local_sku_id.is_not(None)))


def add(db, user_id, identity, order_qty, remark, semifinished_items):
    identity_id = sku_id(identity)
    _lock_user(db, user_id)
    _validate_skus(db, [identity_id])
    sku = db.get(CatalogSku, identity_id)
    product = db.get(CatalogProduct, sku.product_id)
    known_id = db.scalar(select(ProductionCart.id).where(ProductionCart.user_id == user_id,
        ProductionCart.local_sku_id == identity_id))
    row = db.scalar(select(ProductionCart).where(ProductionCart.id == known_id).with_for_update()
        .execution_options(populate_existing=True)) if known_id is not None else None
    action = "updated"
    if row is None:
        # Insert first for absent keys; an old RR snapshot can miss a row,
        # so duplicate-key recovery still fetches the current committed row.
        try:
            with db.begin_nested():
                row = ProductionCart(user_id=user_id, local_sku_id=identity_id,
                    product_name=product.name, order_qty=order_qty)
                db.add(row)
                db.flush()
            action = "created"
        except IntegrityError:
            row = db.scalar(select(ProductionCart).where(ProductionCart.user_id == user_id,
                ProductionCart.local_sku_id == identity_id).with_for_update().execution_options(populate_existing=True))
            if row is None:
                raise
    row.product_name, row.model = product.name, product.model
    row.spec_info = " / ".join(value for value in (sku.color, sku.size, sku.curl) if value)[:255]
    row.order_qty, row.remark = order_qty, remark
    db.flush()
    _replace_plans(db, row.id, semifinished_items or [])
    result = {"id": row.id, "action": action}
    db.commit()
    return result


def _replace_plans(db, cart_id, items):
    amounts = {int(item["material_id"]): qty(item["quantity_grams"]) for item in items}
    if len(amounts) != len(items):
        raise ValueError("半成品计划不能包含重复物料")
    if any(value <= 0 for value in amounts.values()):
        raise ValueError("半成品计划克数必须大于0")
    valid = set(db.scalars(select(SemifinishedMaterial.id).where(
        SemifinishedMaterial.id.in_(amounts), SemifinishedMaterial.status == "active"))) if amounts else set()
    if valid != set(amounts):
        raise ValueError("半成品计划包含不存在或已停用的物料")
    # Insert before deleting excess plans. An empty-range DELETE first takes
    # a next-key lock that can deadlock another cart's independent insertion.
    for material_id, amount in sorted(amounts.items()):
        try:
            with db.begin_nested():
                db.add(CartPlan(production_cart_id=cart_id, material_id=material_id, quantity_grams=amount))
                db.flush()
        except IntegrityError:
            plan = db.scalar(select(CartPlan).where(CartPlan.production_cart_id == cart_id,
                CartPlan.material_id == material_id).with_for_update().execution_options(populate_existing=True))
            if plan is None:
                raise
            plan.quantity_grams = amount
            db.flush()
    obsolete = db.query(CartPlan).filter(CartPlan.production_cart_id == cart_id)
    if amounts:
        obsolete = obsolete.filter(CartPlan.material_id.notin_(amounts))
    obsolete.delete(synchronize_session=False)


def update(db, user_id, cart_id, order_qty, remark):
    _lock_user(db, user_id)
    rows = _rows(db, user_id, [cart_id], lock=True)
    if not rows:
        return False
    row = rows[0]
    if row.order_qty != order_qty:
        for plan in db.scalars(select(CartPlan).where(CartPlan.production_cart_id == row.id).with_for_update()):
            plan.quantity_grams = qty(plan.quantity_grams * Decimal(order_qty) / Decimal(row.order_qty))
    row.order_qty, row.remark = order_qty, remark
    db.commit()
    return True


def delete(db, user_id, ids, *, commit=True):
    _lock_user(db, user_id)
    rows = _rows(db, user_id, ids, lock=True)
    if rows:
        db.query(CartPlan).filter(CartPlan.production_cart_id.in_([row.id for row in rows])).delete(synchronize_session=False)
    for row in rows:
        db.delete(row)
    if commit:
        db.commit()
    return len(rows)


def _result(db, order):
    result = {"order_id": order.id, "order_no": order.order_no, "transaction_mode": "local"}
    material_order = db.scalar(select(SemifinishedOrder).where(SemifinishedOrder.production_order_id == order.id)
        .with_for_update().execution_options(populate_existing=True))
    if material_order:
        result.update(semifinished_order_id=material_order.id, semifinished_order_no=material_order.order_no)
    return result


def create_order(db, body, user):
    from app.production.local_service import claim, create
    from app.production.local_schemas import ProductionCreate, ProductionLine
    from app.semifinished import order_service
    from app.receipt.access import user_id as actor_id
    if not body.request_key:
        raise ValueError("本地生产下单必须提供幂等键")
    if len(set(body.cart_ids)) != len(body.cart_ids):
        raise ValueError("备货车明细不能重复")
    with db.begin_nested():
        _lock_user(db, actor_id(user))
        event, fresh = claim(db, "create_from_cart", None, body, user)
        if not fresh:
            original = db.scalar(select(ProductionOrder).where(ProductionOrder.id == event.order_id)
                .with_for_update().execution_options(populate_existing=True))
            return _result(db, original)
        rows = _rows(db, actor_id(user), body.cart_ids, lock=True)
        if len(rows) != len(body.cart_ids):
            raise ValueError("选中的本地备货车明细已变化，请刷新后重试")
        inner_key = hashlib.sha256(f"cart-production:{event.id}".encode()).hexdigest()
        order = create(db, ProductionCreate(request_key=inner_key, batch_no=body.batch_no, remark=body.remark or "",
            items=[ProductionLine(local_sku_id=row.local_sku_id, quantity=row.order_qty,
                expected_delivery_date=body.expected_delivery_date, remark=row.remark or "") for row in rows]), user)
        for line in db.scalars(select(ProductionOrderItem).where(ProductionOrderItem.order_id == order.id)):
            line.is_urgent = int(body.is_urgent)
        amounts = {}
        for plan in db.scalars(select(CartPlan).where(CartPlan.production_cart_id.in_(body.cart_ids)).with_for_update()):
            amounts[plan.material_id] = amounts.get(plan.material_id, Decimal(0)) + plan.quantity_grams
        if amounts:
            order_service.create_order(db, items=[{"material_id": key, "quantity_grams": amount} for key, amount in amounts.items()],
                user_id=actor_id(user), batch_no=body.batch_no, is_urgent=body.is_urgent,
                expected_delivery_date=body.expected_delivery_date, remark=f"随产成品订单 {order.order_no} 创建",
                source_type="production_sync", production_order_id=order.id, commit=False)
        delete(db, actor_id(user), body.cart_ids, commit=False)
        event.order_id = order.id
        db.flush()
        return _result(db, order)
