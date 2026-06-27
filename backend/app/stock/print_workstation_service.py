"""备货管理 — 打印工作台服务

提供打印工作台专用的订单列表、分类聚合、打印记录能力。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.report.category_service import classify, split_by_category
from app.stock.models import ProductionOrder, ProductionPrintLog

logger = logging.getLogger("stock")

STATUS_LABELS = {0: "已提交", 1: "已终止", 2: "已完成"}


def get_print_order_list(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    status: Optional[int] = None,
    print_state: Optional[str] = None,
    sort_field: str = "created_at",
    sort_order: str = "desc",
) -> dict:
    """打印工作台-订单列表(含最后整单打印时间)"""
    clauses = ["o.deleted_flag = 0"]
    params: dict[str, Any] = {}

    if status is not None:
        clauses.append("o.status = :status")
        params["status"] = status
    if keyword:
        clauses.append("(o.order_no LIKE :kw OR o.batch_no LIKE :kw)")
        params["kw"] = f"%{keyword}%"

    # print_state: unprinted / today / week
    if print_state == "unprinted":
        clauses.append("lp.last_printed_at IS NULL")
    elif print_state == "today":
        clauses.append("DATE(lp.last_printed_at) = CURDATE()")
    elif print_state == "week":
        clauses.append("lp.last_printed_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)")

    where_sql = " AND ".join(clauses)

    # 子查询：订单级最后打印时间
    print_subquery = """
        LEFT JOIN (
            SELECT order_id, MAX(printed_at) AS last_printed_at
            FROM ark_production_print_logs
            WHERE scope = 'order'
            GROUP BY order_id
        ) lp ON lp.order_id = o.id
    """

    count_sql = f"""
        SELECT COUNT(DISTINCT o.id)
        FROM ark_production_orders o
        {print_subquery}
        WHERE {where_sql}
    """
    total = db.execute(text(count_sql), params).scalar() or 0

    SORT_COL_MAP = {
        "order_no": "o.order_no", "batch_no": "o.batch_no",
        "created_at": "o.created_at", "status": "o.status",
        "last_printed_at": "lp.last_printed_at",
    }
    sort_col = SORT_COL_MAP.get(sort_field, "o.created_at")
    sort_dir = "DESC" if sort_order == "desc" else "ASC"

    params.update({"limit": page_size, "offset": (page - 1) * page_size})
    sql = f"""
        SELECT
            o.id, o.order_no, o.batch_no, o.remark, o.status,
            o.created_by, o.created_at,
            u.real_name AS created_by_name,
            COUNT(i.id) AS item_count,
            COALESCE(SUM(i.order_qty), 0) AS total_order_qty,
            lp.last_printed_at AS last_order_printed_at
        FROM ark_production_orders o
        LEFT JOIN ark_users u ON u.id = o.created_by
        LEFT JOIN ark_production_order_items i ON i.order_id = o.id
        {print_subquery}
        WHERE {where_sql}
        GROUP BY o.id, o.order_no, o.batch_no, o.remark, o.status,
                 o.created_by, o.created_at, u.real_name, lp.last_printed_at
        ORDER BY {sort_col} {sort_dir}
        LIMIT :limit OFFSET :offset
    """
    rows = db.execute(text(sql), params).mappings().all()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "order_no": r["order_no"],
            "batch_no": r["batch_no"],
            "remark": r["remark"],
            "status": r["status"],
            "status_label": STATUS_LABELS.get(r["status"], "未知"),
            "created_by_name": r["created_by_name"] or "",
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "item_count": int(r["item_count"] or 0),
            "total_order_qty": int(r["total_order_qty"] or 0),
            "last_order_printed_at": r["last_order_printed_at"].isoformat() if r["last_order_printed_at"] else None,
        })

    return {"total": int(total), "items": items}


def get_order_print_categories(db: Session, order_id: int) -> list:
    """获取订单的分类卡片(打印工作台展开)"""
    settings = get_settings()
    business_db = settings.BUSINESS_DB_NAME

    sql = text(f"""
        SELECT
            oi.id AS item_id,
            oi.product_id,
            oi.product_name,
            oi.model,
            oi.order_qty,
            p.color,
            p.size,
            p.unit,
            p.product_remark
        FROM ark_production_order_items oi
        LEFT JOIN ark_production_orders o ON oi.order_id = o.id
        LEFT JOIN `{business_db}`.okki_products p ON p.product_id = oi.product_id
        WHERE oi.order_id = :order_id AND o.deleted_flag = 0
    """)
    rows = db.execute(sql, {"order_id": order_id}).mappings().all()

    long_items = []
    for r in rows:
        long_items.append({
            "item_id": r["item_id"],
            "product_id": r["product_id"],
            "product_name": r["product_name"] or "",
            "model": r["model"] or "",
            "order_qty": int(r["order_qty"]) if r["order_qty"] else 0,
            "color": r["color"] or "",
            "size": r["size"] or "",
            "unit": r["unit"] or "",
            "product_remark": r["product_remark"] or "",
        })

    categories_raw = split_by_category(long_items)

    # 查各分类最近打印记录
    log_sql = text("""
        SELECT category_index, MAX(printed_at) AS last_printed_at,
               SUBSTRING_INDEX(GROUP_CONCAT(printed_by_name ORDER BY printed_at DESC), ',', 1) AS last_printed_by_name
        FROM ark_production_print_logs
        WHERE order_id = :order_id AND scope = 'category'
        GROUP BY category_index
    """)
    log_rows = db.execute(log_sql, {"order_id": order_id}).mappings().all()
    log_map = {r["category_index"]: r for r in log_rows}

    # 整单最近打印
    order_log_sql = text("""
        SELECT MAX(printed_at) AS last_printed_at,
               SUBSTRING_INDEX(GROUP_CONCAT(printed_by_name ORDER BY printed_at DESC), ',', 1) AS last_printed_by_name
        FROM ark_production_print_logs
        WHERE order_id = :order_id AND scope = 'order'
    """)
    order_log = db.execute(order_log_sql, {"order_id": order_id}).mappings().first()

    categories = []
    for cat_idx, cat_label, items in categories_raw:
        colors = list(set(it["color"] for it in items if it["color"]))
        product_types = list(set(it["product_remark"] for it in items if it["product_remark"]))
        item_ids = [it["item_id"] for it in items]
        total_qty = sum(it["order_qty"] for it in items)

        log_entry = log_map.get(cat_idx)
        categories.append({
            "category_index": cat_idx,
            "category_label": cat_label,
            "colors": sorted(colors),
            "product_types": sorted(product_types),
            "item_count": len(items),
            "total_qty": total_qty,
            "item_ids": item_ids,
            "last_printed_at": log_entry["last_printed_at"].isoformat() if log_entry and log_entry["last_printed_at"] else None,
            "last_printed_by_name": log_entry["last_printed_by_name"] if log_entry else None,
        })

    return {
        "categories": categories,
        "last_order_printed_at": order_log["last_printed_at"].isoformat() if order_log and order_log["last_printed_at"] else None,
        "last_order_printed_by_name": order_log["last_printed_by_name"] if order_log else None,
    }


def create_print_job(
    db: Session,
    order_id: int,
    scope: str,
    category_index: Optional[int],
    item_ids: Optional[list],
    user_id: int,
    user_name: str,
) -> dict:
    """创建打印记录并返回打印URL"""
    order = db.query(ProductionOrder).filter(
        ProductionOrder.id == order_id,
        ProductionOrder.deleted_flag == 0,
    ).first()
    if not order:
        raise ValueError("订单不存在或已删除")

    # 如果是整单打印但没有传 item_ids，计算全部明细
    category_label = None
    if scope == "category" and category_index is not None:
        # 获取分类标签
        from app.report.category_service import CATEGORY_RULES, OTHER_LABEL
        if category_index == -1:
            category_label = OTHER_LABEL
        elif 0 <= category_index < len(CATEGORY_RULES):
            category_label = CATEGORY_RULES[category_index]["label"]

    log = ProductionPrintLog(
        order_id=order_id,
        order_no=order.order_no,
        scope=scope,
        category_index=category_index if scope == "category" else None,
        category_label=category_label,
        item_ids_json=item_ids,
        printed_by=user_id,
        printed_by_name=user_name,
        printed_at=datetime.utcnow(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # 构建打印 URL
    print_url = f"/api/report/print/production-order?order_no={order.order_no}"
    if scope == "category" and category_index is not None:
        print_url += f"&category_index={category_index}"

    return {
        "print_url": print_url,
        "log_id": log.id,
        "printed_at": log.printed_at.isoformat(),
    }
