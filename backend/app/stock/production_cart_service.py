"""备货管理 — 生产单购物车 CRUD"""

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

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
        db.commit()
        return {"id": existing["id"], "action": "updated"}
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
        db.commit()
        return {"id": result.lastrowid, "action": "created"}


def update_cart_item(
    db: Session,
    user_id: int,
    cart_id: int,
    order_qty: int,
    remark: Optional[str],
) -> bool:
    """更新购物车项,仅允许修改自己的"""
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


def delete_cart_items(db: Session, user_id: int, cart_ids: list[int]) -> int:
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

    return [
        {
            "id": r["id"],
            "product_id": int(r["product_id"]),
            "product_name": r["product_name"],
            "model": r["model"],
            "spec_info": r["spec_info"],
            "order_qty": r["order_qty"],
            "remark": r["remark"],
        }
        for r in rows
    ]
