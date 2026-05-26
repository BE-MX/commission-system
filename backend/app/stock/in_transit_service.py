"""备货管理 — 生产在途数量统计

被 safety_service / overview_service 调用,统计「已提交」状态生产订单明细的在途数量。
"""

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("stock.in_transit")


def get_in_transit_by_product_ids(db: Session, product_ids: list[int]) -> dict[int, int]:
    """批量查询产品的生产在途数量

    返回: {product_id: in_transit_qty}
    仅统计明细状态为「已提交」(0) 的数据。
    """
    if not product_ids:
        return {}

    placeholders = ",".join([f":p{i}" for i in range(len(product_ids))])
    params = {f"p{i}": pid for i, pid in enumerate(product_ids)}

    rows = db.execute(
        text(f"""
            SELECT
                i.product_id,
                COALESCE(SUM(i.order_qty - i.received_qty), 0) AS in_transit_qty
            FROM ark_production_order_items i
            JOIN ark_production_orders o ON o.id = i.order_id
            WHERE i.product_id IN ({placeholders})
              AND i.status = 0
              AND o.status = 0
              AND o.deleted_flag = 0
            GROUP BY i.product_id
        """),
        params,
    ).mappings().all()

    return {int(r["product_id"]): int(r["in_transit_qty"]) for r in rows}


def get_in_transit_for_query(
    db: Session,
    product_ids: list[int],
) -> dict[int, int]:
    """查询安全库存列表/销量备货一览时的在途数量聚合"""
    return get_in_transit_by_product_ids(db, product_ids)
