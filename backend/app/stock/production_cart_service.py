"""备货管理 — 生产单购物车 CRUD"""

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.semifinished.inventory_service import qty
from app.semifinished.models import CartPlan, SemifinishedMaterial

logger = logging.getLogger("stock.production_cart")


def get_cart_list(db: Session, user_id: int) -> list[dict]:
    """获取用户购物车列表"""
    rows = db.execute(
        text("""
            SELECT id, product_id, product_name, model, spec_info,
                   order_qty, remark, created_at
            FROM ark_production_cart
            WHERE user_id = :user_id
            ORDER BY created_at DESC
        """),
        {"user_id": user_id},
    ).mappings().all()

    plans = db.query(CartPlan).filter(CartPlan.production_cart_id.in_([r["id"] for r in rows])).all() if rows else []
    plans_by_cart: dict[int, list[dict]] = {}
    for plan in plans:
        plans_by_cart.setdefault(plan.production_cart_id, []).append({
            "material_id": plan.material_id,
            "quantity_grams": plan.quantity_grams,
        })
    return [
        {
            "id": r["id"],
            "product_id": int(r["product_id"]),
            "product_name": r["product_name"],
            "model": r["model"],
            "spec_info": r["spec_info"],
            "order_qty": r["order_qty"],
            "remark": r["remark"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "semifinished_items": plans_by_cart.get(r["id"], []),
        }
        for r in rows
    ]


def get_cart_count(db: Session, user_id: int) -> int:
    """获取购物车商品数量(用于角标)"""
    return db.execute(
        text("SELECT COUNT(*) FROM ark_production_cart WHERE user_id = :user_id"),
        {"user_id": user_id},
    ).scalar() or 0


def add_or_update_cart(
    db: Session,
    user_id: int,
    product_id: int,
    product_name: str,
    model: Optional[str],
    spec_info: Optional[str],
    order_qty: int,
    remark: Optional[str],
    semifinished_items: list[dict] | None = None,
) -> dict:
    """加入购物车: 已存在则更新数量和备注,不存在则新增"""
    existing = db.execute(
        text("SELECT id FROM ark_production_cart WHERE user_id = :user_id AND product_id = :product_id"),
        {"user_id": user_id, "product_id": product_id},
    ).mappings().first()

    if existing:
        db.execute(
            text("""
                UPDATE ark_production_cart
                SET order_qty = :order_qty,
                    remark = :remark,
                    updated_at = NOW()
                WHERE id = :id
            """),
            {"id": existing["id"], "order_qty": order_qty, "remark": remark},
        )
        cart_id = existing["id"]
        action = "updated"
    else:
        result = db.execute(
            text("""
                INSERT INTO ark_production_cart
                  (user_id, product_id, product_name, model, spec_info, order_qty, remark, created_at, updated_at)
                VALUES
                  (:user_id, :product_id, :product_name, :model, :spec_info, :order_qty, :remark, NOW(), NOW())
            """),
            {
                "user_id": user_id,
                "product_id": product_id,
                "product_name": product_name,
                "model": model,
                "spec_info": spec_info,
                "order_qty": order_qty,
                "remark": remark,
            },
        )
        cart_id = result.lastrowid
        action = "created"
    _replace_cart_plans(db, cart_id, semifinished_items or [])
    db.commit()
    return {"id": cart_id, "action": action}


def _replace_cart_plans(db: Session, cart_id: int, items: list[dict]) -> None:
    db.query(CartPlan).filter(CartPlan.production_cart_id == cart_id).delete(synchronize_session=False)
    if not items:
        return
    material_ids = [int(item["material_id"]) for item in items]
    if len(set(material_ids)) != len(material_ids):
        raise ValueError("半成品计划不能包含重复物料")
    valid_ids = {
        row.id for row in db.query(SemifinishedMaterial).filter(
            SemifinishedMaterial.id.in_(material_ids),
            SemifinishedMaterial.status == "active",
        ).all()
    }
    if valid_ids != set(material_ids):
        raise ValueError("半成品计划包含不存在或已停用的物料")
    for item in items:
        amount = qty(item["quantity_grams"])
        if amount <= 0:
            raise ValueError("半成品计划克数必须大于0")
        db.add(CartPlan(production_cart_id=cart_id, material_id=item["material_id"], quantity_grams=amount))


def update_cart_item(
    db: Session,
    user_id: int,
    cart_id: int,
    order_qty: int,
    remark: Optional[str],
) -> bool:
    """更新购物车项,仅允许修改自己的"""
    old_qty = db.execute(
        text("SELECT order_qty FROM ark_production_cart WHERE id = :id AND user_id = :user_id"),
        {"id": cart_id, "user_id": user_id},
    ).scalar()
    if old_qty is None:
        return False
    result = db.execute(
        text("""
            UPDATE ark_production_cart
            SET order_qty = :order_qty,
                remark = :remark,
                updated_at = NOW()
            WHERE id = :id AND user_id = :user_id
        """),
        {"id": cart_id, "user_id": user_id, "order_qty": order_qty, "remark": remark},
    )
    if int(old_qty) != order_qty and int(old_qty) > 0:
        ratio = Decimal(order_qty) / Decimal(int(old_qty))
        for plan in db.query(CartPlan).filter(CartPlan.production_cart_id == cart_id).all():
            plan.quantity_grams = qty(plan.quantity_grams * ratio)
    db.commit()
    return result.rowcount > 0


def delete_cart_item(db: Session, user_id: int, cart_id: int) -> bool:
    """删除购物车单项"""
    result = db.execute(
        text("DELETE FROM ark_production_cart WHERE id = :id AND user_id = :user_id"),
        {"id": cart_id, "user_id": user_id},
    )
    db.commit()
    return result.rowcount > 0


def delete_cart_items(db: Session, user_id: int, cart_ids: list[int], *, commit: bool = True) -> int:
    """批量删除购物车项,返回删除数量"""
    if not cart_ids:
        return 0
    placeholders = ",".join([f":c{i}" for i in range(len(cart_ids))])
    params = {f"c{i}": cid for i, cid in enumerate(cart_ids)}
    params["user_id"] = user_id

    result = db.execute(
        text(f"""
            DELETE FROM ark_production_cart
            WHERE user_id = :user_id AND id IN ({placeholders})
        """),
        params,
    )
    if commit:
        db.commit()
    return result.rowcount


def get_cart_items_by_ids(db: Session, user_id: int, cart_ids: list[int]) -> list[dict]:
    """按ID批量查询购物车项(用于生成订单时取数据)"""
    if not cart_ids:
        return []
    placeholders = ",".join([f":c{i}" for i in range(len(cart_ids))])
    params = {f"c{i}": cid for i, cid in enumerate(cart_ids)}
    params["user_id"] = user_id

    rows = db.execute(
        text(f"""
            SELECT id, product_id, product_name, model, spec_info, order_qty, remark
            FROM ark_production_cart
            WHERE user_id = :user_id AND id IN ({placeholders})
            ORDER BY id
        """),
        params,
    ).mappings().all()

    plans = db.query(CartPlan).filter(CartPlan.production_cart_id.in_([r["id"] for r in rows])).all() if rows else []
    plans_by_cart: dict[int, list[dict]] = {}
    for plan in plans:
        plans_by_cart.setdefault(plan.production_cart_id, []).append({
            "material_id": plan.material_id,
            "quantity_grams": plan.quantity_grams,
        })
    return [
        {
            "id": r["id"],
            "product_id": int(r["product_id"]),
            "product_name": r["product_name"],
            "model": r["model"],
            "spec_info": r["spec_info"],
            "order_qty": r["order_qty"],
            "remark": r["remark"],
            "semifinished_items": plans_by_cart.get(r["id"], []),
        }
        for r in rows
    ]
