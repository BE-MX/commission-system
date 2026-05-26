"""备货管理 — 生产订单 CRUD + 状态管理 + 入库数量 + 审计日志

决策确认:
- 订单号格式: PO{YYYYMMDD}-{NNN}
- 批次号全局唯一
- 订单和明细状态双向同步
- 入库完成(received_qty == order_qty)自动改明细状态为「已完成」(2)
- 软删(delete_flag=1)
"""

import logging
from datetime import date
from typing import Any, Optional

from app.core.config import get_settings

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.stock.models import ProductionOrder, ProductionOrderItem, ProductionAuditLog

logger = logging.getLogger("stock.production_order")

# 状态映射
STATUS_LABELS = {0: "已提交", 1: "已终止", 2: "已完成"}


def _generate_order_no(db: Session) -> str:
    """生成订单号: PO{YYYYMMDD}-{NNN}, 按天自增"""
    today_str = date.today().strftime("%Y%m%d")
    prefix = f"PO{today_str}-"

    result = db.execute(
        text("""
            SELECT order_no FROM ark_production_orders
            WHERE order_no LIKE :prefix
            ORDER BY order_no DESC LIMIT 1
        """),
        {"prefix": f"{prefix}%"},
    ).mappings().first()

    if result:
        last_no = result["order_no"]
        try:
            seq = int(last_no.split("-")[-1])
            next_seq = seq + 1
        except (ValueError, IndexError):
            next_seq = 1
    else:
        next_seq = 1

    return f"{prefix}{next_seq:03d}"


def _write_audit(
    db: Session,
    *,
    order_id: int,
    item_id: Optional[int] = None,
    operator_id: int,
    operator_name: str,
    action: str,
    from_status: Optional[int] = None,
    to_status: Optional[int] = None,
    comment: Optional[str] = None,
    snapshot: Optional[dict] = None,
):
    """写入审计日志(不提交,由调用方commit)"""
    log = ProductionAuditLog(
        order_id=order_id,
        item_id=item_id,
        operator_id=operator_id,
        operator_name=operator_name,
        action=action,
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        snapshot=snapshot,
    )
    db.add(log)


def create_order(
    db: Session,
    cart_items: list[dict],
    batch_no: str,
    remark: Optional[str],
    is_urgent: bool = False,
    expected_delivery_date: Optional[date] = None,
    operator_id: int = 0,
    operator_name: str = "",
) -> dict:
    """从购物车项生成生产订单

    返回: {"order_id": int, "order_no": str}
    """
    # 校验批次号唯一
    existing_batch = db.execute(
        text("SELECT 1 FROM ark_production_orders WHERE batch_no = :batch_no AND deleted_flag = 0"),
        {"batch_no": batch_no},
    ).first()
    if existing_batch:
        raise ValueError(f"批次号 '{batch_no}' 已存在")

    order_no = _generate_order_no(db)

    # 创建主表
    order = ProductionOrder(
        order_no=order_no,
        batch_no=batch_no,
        remark=remark,
        status=0,
        created_by=operator_id,
    )
    db.add(order)
    db.flush()

    # 创建明细
    for item in cart_items:
        order_item = ProductionOrderItem(
            order_id=order.id,
            product_id=item["product_id"],
            product_name=item["product_name"],
            model=item.get("model"),
            spec_info=item.get("spec_info"),
            order_qty=item["order_qty"],
            received_qty=0,
            status=0,
            is_urgent=1 if is_urgent else 0,
            expected_delivery_date=expected_delivery_date,
            remark=item.get("remark"),
        )
        db.add(order_item)

    # 审计日志
    _write_audit(
        db,
        order_id=order.id,
        operator_id=operator_id,
        operator_name=operator_name,
        action="create",
        snapshot={"batch_no": batch_no, "item_count": len(cart_items), "is_urgent": is_urgent, "expected_delivery_date": str(expected_delivery_date) if expected_delivery_date else None},
    )

    db.commit()
    return {"order_id": order.id, "order_no": order_no}


def get_order_list(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: Optional[int] = None,
    keyword: Optional[str] = None,
) -> dict:
    """按生产单维度列表"""
    clauses = ["o.deleted_flag = 0"]
    params: dict[str, Any] = {}

    if status is not None:
        clauses.append("o.status = :status")
        params["status"] = status
    if keyword:
        clauses.append("(o.order_no LIKE :kw OR o.batch_no LIKE :kw)")
        params["kw"] = f"%{keyword}%"

    where_sql = " AND ".join(clauses)

    # 总数
    count_sql = f"SELECT COUNT(*) FROM ark_production_orders o WHERE {where_sql}"
    total = db.execute(text(count_sql), params).scalar() or 0

    # 查询
    params.update({"limit": page_size, "offset": (page - 1) * page_size})
    sql = f"""
        SELECT
            o.id, o.order_no, o.batch_no, o.remark, o.status,
            o.created_by, o.created_at,
            u.real_name AS created_by_name,
            COUNT(i.id) AS item_count,
            COALESCE(SUM(i.order_qty), 0) AS total_order_qty,
            COALESCE(SUM(i.received_qty), 0) AS total_received_qty
        FROM ark_production_orders o
        LEFT JOIN ark_users u ON u.id = o.created_by
        LEFT JOIN ark_production_order_items i ON i.order_id = o.id
        WHERE {where_sql}
        GROUP BY o.id, o.order_no, o.batch_no, o.remark, o.status,
                 o.created_by, o.created_at, u.real_name
        ORDER BY o.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = db.execute(text(sql), params).mappings().all()

    items = []
    for r in rows:
        total_order = int(r["total_order_qty"] or 0)
        total_received = int(r["total_received_qty"] or 0)
        items.append({
            "id": r["id"],
            "order_no": r["order_no"],
            "batch_no": r["batch_no"],
            "remark": r["remark"],
            "status": r["status"],
            "status_label": STATUS_LABELS.get(r["status"], "未知"),
            "created_by": r["created_by"],
            "created_by_name": r["created_by_name"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "item_count": r["item_count"],
            "total_order_qty": total_order,
            "total_received_qty": total_received,
            "total_in_transit_qty": total_order - total_received,
        })

    return {"total": int(total), "items": items}


def get_order_detail(db: Session, order_id: int) -> Optional[dict]:
    """生产订单详情(含明细)"""
    order = db.execute(
        text("""
            SELECT o.*, u.real_name AS created_by_name
            FROM ark_production_orders o
            LEFT JOIN ark_users u ON u.id = o.created_by
            WHERE o.id = :id AND o.deleted_flag = 0
        """),
        {"id": order_id},
    ).mappings().first()

    if not order:
        return None

    # 查询明细
    items = db.execute(
        text("""
            SELECT * FROM ark_production_order_items
            WHERE order_id = :order_id
            ORDER BY id
        """),
        {"order_id": order_id},
    ).mappings().all()

    item_list = []
    for i in items:
        order_qty = i["order_qty"]
        received = i["received_qty"]
        item_list.append({
            "id": i["id"],
            "order_id": i["order_id"],
            "product_id": int(i["product_id"]),
            "product_name": i["product_name"],
            "model": i["model"],
            "spec_info": i["spec_info"],
            "order_qty": order_qty,
            "received_qty": received,
            "in_transit_qty": order_qty - received,
            "status": i["status"],
            "is_urgent": i["is_urgent"] or 0,
            "expected_delivery_date": i["expected_delivery_date"].isoformat() if i["expected_delivery_date"] else None,
            "remark": i["remark"],
            "created_at": i["created_at"].isoformat() if i["created_at"] else None,
        })

    return {
        "id": order["id"],
        "order_no": order["order_no"],
        "batch_no": order["batch_no"],
        "remark": order["remark"],
        "status": order["status"],
        "status_label": STATUS_LABELS.get(order["status"], "未知"),
        "created_by": order["created_by"],
        "created_by_name": order["created_by_name"],
        "created_at": order["created_at"].isoformat() if order["created_at"] else None,
        "updated_by": order["updated_by"],
        "updated_at": order["updated_at"].isoformat() if order["updated_at"] else None,
        "items": item_list,
    }


def update_order(
    db: Session,
    order_id: int,
    batch_no: Optional[str] = None,
    remark: Optional[str] = None,
    status: Optional[int] = None,
    operator_id: int = 0,
    operator_name: str = "",
) -> bool:
    """编辑生产订单,支持状态变更(级联同步明细状态)"""
    order = db.execute(
        text("SELECT * FROM ark_production_orders WHERE id = :id AND deleted_flag = 0"),
        {"id": order_id},
    ).mappings().first()

    if not order:
        return False

    old_status = order["status"]
    updates = []
    params: dict[str, Any] = {"id": order_id}

    if batch_no is not None:
        # 校验新批次号唯一(排除自己)
        dup = db.execute(
            text("SELECT 1 FROM ark_production_orders WHERE batch_no = :batch_no AND id != :id AND deleted_flag = 0"),
            {"batch_no": batch_no, "id": order_id},
        ).first()
        if dup:
            raise ValueError(f"批次号 '{batch_no}' 已存在")
        updates.append("batch_no = :batch_no")
        params["batch_no"] = batch_no

    if remark is not None:
        updates.append("remark = :remark")
        params["remark"] = remark

    if status is not None and status != old_status:
        updates.append("status = :status")
        params["status"] = status

    if not updates:
        return True

    updates.append("updated_at = NOW()")
    if operator_id:
        updates.append("updated_by = :updated_by")
        params["updated_by"] = operator_id

    db.execute(
        text(f"UPDATE ark_production_orders SET {', '.join(updates)} WHERE id = :id"),
        params,
    )

    # 状态变更时级联同步明细状态
    if status is not None and status != old_status:
        db.execute(
            text("UPDATE ark_production_order_items SET status = :status WHERE order_id = :order_id"),
            {"status": status, "order_id": order_id},
        )

    # 审计日志
    _write_audit(
        db,
        order_id=order_id,
        operator_id=operator_id,
        operator_name=operator_name,
        action="update_status" if status is not None else "update",
        from_status=old_status,
        to_status=status if status is not None else old_status,
        snapshot={"batch_no": batch_no, "remark": remark},
    )

    db.commit()
    return True


def delete_order(
    db: Session,
    order_id: int,
    operator_id: int = 0,
    operator_name: str = "",
) -> bool:
    """软删生产订单(已入库的不允许删除)"""
    order = db.execute(
        text("""
            SELECT o.*, COALESCE(SUM(i.received_qty), 0) AS total_received
            FROM ark_production_orders o
            LEFT JOIN ark_production_order_items i ON i.order_id = o.id
            WHERE o.id = :id AND o.deleted_flag = 0
            GROUP BY o.id
        """),
        {"id": order_id},
    ).mappings().first()

    if not order:
        return False

    # 已入库的不允许删除
    total_received = int(order["total_received"] or 0)
    if total_received > 0:
        raise ValueError("该生产订单已有入库记录,不允许删除")

    db.execute(
        text("UPDATE ark_production_orders SET deleted_flag = 1, updated_at = NOW() WHERE id = :id"),
        {"id": order_id},
    )

    _write_audit(
        db,
        order_id=order_id,
        operator_id=operator_id,
        operator_name=operator_name,
        action="delete",
        snapshot={"order_no": order["order_no"], "batch_no": order["batch_no"]},
    )

    db.commit()
    return True


# ── 明细操作 ────────────────────────────────────────────────

def get_order_item_list(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: Optional[int] = None,
    keyword: Optional[str] = None,
) -> dict:
    """按生产订单明细维度列表(标签页二用)"""
    clauses = ["o.deleted_flag = 0"]
    params: dict[str, Any] = {}

    if status is not None:
        clauses.append("i.status = :status")
        params["status"] = status
    if keyword:
        clauses.append("(i.product_name LIKE :kw OR o.order_no LIKE :kw OR o.batch_no LIKE :kw)")
        params["kw"] = f"%{keyword}%"

    where_sql = " AND ".join(clauses)

    count_sql = f"""
        SELECT COUNT(*) FROM ark_production_order_items i
        JOIN ark_production_orders o ON o.id = i.order_id
        WHERE {where_sql}
    """
    total = db.execute(text(count_sql), params).scalar() or 0

    params.update({"limit": page_size, "offset": (page - 1) * page_size})
    sql = f"""
        SELECT
            i.id, i.order_id, i.product_id, i.product_name, i.model, i.spec_info,
            i.order_qty, i.received_qty, i.status AS item_status, i.is_urgent, i.expected_delivery_date, i.remark, i.created_at,
            o.order_no, o.batch_no, o.status AS order_status
        FROM ark_production_order_items i
        JOIN ark_production_orders o ON o.id = i.order_id
        WHERE {where_sql}
        ORDER BY i.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    rows = db.execute(text(sql), params).mappings().all()

    items = []
    for r in rows:
        order_qty = r["order_qty"]
        received = r["received_qty"]
        items.append({
            "id": r["id"],
            "order_id": r["order_id"],
            "order_no": r["order_no"],
            "batch_no": r["batch_no"],
            "product_id": int(r["product_id"]),
            "product_name": r["product_name"],
            "model": r["model"],
            "spec_info": r["spec_info"],
            "order_qty": order_qty,
            "received_qty": received,
            "in_transit_qty": order_qty - received,
            "status": r["item_status"],
            "status_label": STATUS_LABELS.get(r["item_status"], "未知"),
            "order_status": r["order_status"],
            "order_status_label": STATUS_LABELS.get(r["order_status"], "未知"),
            "is_urgent": r["is_urgent"] or 0,
            "expected_delivery_date": r["expected_delivery_date"].isoformat() if r["expected_delivery_date"] else None,
            "remark": r["remark"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    return {"total": int(total), "items": items}


def update_order_item(
    db: Session,
    item_id: int,
    order_qty: Optional[int] = None,
    remark: Optional[str] = None,
    is_urgent: Optional[int] = None,
    expected_delivery_date: Optional[date] = None,
    operator_id: int = 0,
    operator_name: str = "",
) -> bool:
    """编辑明细(数量/备注/加急/预计交期)"""
    item = db.execute(
        text("SELECT * FROM ark_production_order_items WHERE id = :id"),
        {"id": item_id},
    ).mappings().first()

    if not item:
        return False

    updates = []
    params: dict[str, Any] = {"id": item_id}

    if order_qty is not None:
        if order_qty < item["received_qty"]:
            raise ValueError("生产下单数量不能小于已入库数量")
        updates.append("order_qty = :order_qty")
        params["order_qty"] = order_qty

    if remark is not None:
        updates.append("remark = :remark")
        params["remark"] = remark

    if is_urgent is not None:
        updates.append("is_urgent = :is_urgent")
        params["is_urgent"] = is_urgent

    if expected_delivery_date is not None:
        updates.append("expected_delivery_date = :expected_delivery_date")
        params["expected_delivery_date"] = expected_delivery_date

    if not updates:
        return True

    updates.append("updated_at = NOW()")
    db.execute(
        text(f"UPDATE ark_production_order_items SET {', '.join(updates)} WHERE id = :id"),
        params,
    )

    _write_audit(
        db,
        order_id=item["order_id"],
        item_id=item_id,
        operator_id=operator_id,
        operator_name=operator_name,
        action="update",
        snapshot={"order_qty": order_qty, "remark": remark, "is_urgent": is_urgent, "expected_delivery_date": str(expected_delivery_date) if expected_delivery_date else None},
    )

    db.commit()
    return True


def update_item_status(
    db: Session,
    item_id: int,
    status: int,
    operator_id: int = 0,
    operator_name: str = "",
) -> bool:
    """修改明细状态,同步更新订单状态(双向同步)"""
    item = db.execute(
        text("SELECT * FROM ark_production_order_items WHERE id = :id"),
        {"id": item_id},
    ).mappings().first()

    if not item:
        return False

    old_status = item["status"]
    if old_status == status:
        return True

    db.execute(
        text("UPDATE ark_production_order_items SET status = :status, updated_at = NOW() WHERE id = :id"),
        {"status": status, "id": item_id},
    )

    order_id = item["order_id"]

    # 检查是否所有明细都变更为同一状态,若是则同步更新订单状态
    all_items = db.execute(
        text("SELECT status FROM ark_production_order_items WHERE order_id = :order_id"),
        {"order_id": order_id},
    ).mappings().all()

    all_same = all(i["status"] == status for i in all_items)
    if all_same:
        db.execute(
            text("UPDATE ark_production_orders SET status = :status, updated_at = NOW() WHERE id = :order_id"),
            {"status": status, "order_id": order_id},
        )

    _write_audit(
        db,
        order_id=order_id,
        item_id=item_id,
        operator_id=operator_id,
        operator_name=operator_name,
        action="update_status",
        from_status=old_status,
        to_status=status,
    )

    db.commit()
    return True


def update_item_received(
    db: Session,
    item_id: int,
    received_qty: int,
    operator_id: int = 0,
    operator_name: str = "",
) -> bool:
    """录入已入库数量,校验范围,完成时自动改状态"""
    if received_qty < 0:
        raise ValueError("已入库数量不能小于0")

    item = db.execute(
        text("SELECT * FROM ark_production_order_items WHERE id = :id"),
        {"id": item_id},
    ).mappings().first()

    if not item:
        return False

    if received_qty > item["order_qty"]:
        raise ValueError("已入库数量不能大于生产下单数量")

    old_received = item["received_qty"]
    new_status = item["status"]

    # 入库完成自动改状态为「已完成」
    if received_qty == item["order_qty"] and item["status"] != 2:
        new_status = 2

    db.execute(
        text("""
            UPDATE ark_production_order_items
            SET received_qty = :received_qty,
                status = :status,
                updated_at = NOW()
            WHERE id = :id
        """),
        {"received_qty": received_qty, "status": new_status, "id": item_id},
    )

    _write_audit(
        db,
        order_id=item["order_id"],
        item_id=item_id,
        operator_id=operator_id,
        operator_name=operator_name,
        action="update_received",
        snapshot={"old_received": old_received, "new_received": received_qty, "status": new_status},
    )

    db.commit()
    return True


def delete_order_item(
    db: Session,
    item_id: int,
    operator_id: int = 0,
    operator_name: str = "",
) -> bool:
    """删除明细(已入库的不允许删除)"""
    item = db.execute(
        text("SELECT * FROM ark_production_order_items WHERE id = :id"),
        {"id": item_id},
    ).mappings().first()

    if not item:
        return False

    if item["received_qty"] > 0:
        raise ValueError("该明细已有入库记录,不允许删除")

    db.execute(
        text("DELETE FROM ark_production_order_items WHERE id = :id"),
        {"id": item_id},
    )

    _write_audit(
        db,
        order_id=item["order_id"],
        item_id=item_id,
        operator_id=operator_id,
        operator_name=operator_name,
        action="delete",
    )

    db.commit()
    return True


def get_stock_status_by_product_ids(db: Session, product_ids: list[int]) -> dict[int, dict]:
    """查询产品备货状态

    返回: {product_id: {"stock_status": "", "has_urgent": bool, "items": [...]}}
    - 存在未完成(status=0)且加急明细 → "加急中"
    - 存在未完成(status=0)明细 → "备货中"
    - 否则 → ""
    """
    if not product_ids:
        return {}

    placeholders = ",".join([f":p{i}" for i in range(len(product_ids))])
    params = {f"p{i}": pid for i, pid in enumerate(product_ids)}

    sql = f"""
        SELECT
            i.product_id,
            i.id AS item_id,
            i.product_name,
            i.order_qty,
            i.received_qty,
            i.status,
            i.is_urgent,
            i.expected_delivery_date,
            o.order_no,
            o.batch_no
        FROM ark_production_order_items i
        JOIN ark_production_orders o ON o.id = i.order_id
        WHERE i.product_id IN ({placeholders})
          AND i.status = 0
          AND o.status = 0
          AND o.deleted_flag = 0
        ORDER BY i.product_id, i.is_urgent DESC, i.id
    """
    rows = db.execute(text(sql), params).mappings().all()

    result: dict[int, dict] = {}
    for pid in product_ids:
        result[pid] = {"stock_status": "", "has_urgent": False, "items": []}

    for r in rows:
        pid = int(r["product_id"])
        entry = result[pid]
        entry["items"].append({
            "item_id": r["item_id"],
            "product_name": r["product_name"],
            "order_qty": r["order_qty"],
            "received_qty": r["received_qty"],
            "in_transit_qty": r["order_qty"] - r["received_qty"],
            "is_urgent": bool(r["is_urgent"]),
            "expected_delivery_date": r["expected_delivery_date"].isoformat() if r["expected_delivery_date"] else None,
            "order_no": r["order_no"],
            "batch_no": r["batch_no"],
        })
        if r["is_urgent"]:
            entry["has_urgent"] = True

    for pid in product_ids:
        entry = result[pid]
        if entry["has_urgent"]:
            entry["stock_status"] = "加急中"
        elif entry["items"]:
            entry["stock_status"] = "备货中"
        else:
            entry["stock_status"] = ""

    return result
