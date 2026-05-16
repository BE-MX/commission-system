"""备货管理 — SKU 销量 / 库存状态查询

跨库 JOIN: 提成库 ark_safety_stock + 业务库 okki_products/okki_order_items/okki_orders/okki_inventory
"""

from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.stock.constants import (
    VALID_ORDER_FILTER, calc_status, calc_suggested_qty, source_label,
)

settings = get_settings()


def get_sku_sales(db: Session, product_id: int, days: int) -> int:
    """指定 SKU 最近 N 天的销量 (只统计已结束订单+7 个指定部门)"""
    business_db = settings.BUSINESS_DB_NAME
    since = date.today() - timedelta(days=days)
    sql = f"""
        SELECT COALESCE(SUM(oi.quantity), 0) AS total_sales
        FROM `{business_db}`.okki_order_items oi
        JOIN `{business_db}`.okki_orders o ON o.order_id = oi.order_id
        WHERE oi.product_id = :product_id
          AND o.account_date >= :since
          AND EXISTS (
              SELECT 1 FROM `{business_db}`.okki_products p
              WHERE p.product_id = oi.product_id AND p.disable_flag = 0
          )
          AND {VALID_ORDER_FILTER}
    """
    row = db.execute(text(sql), {"product_id": product_id, "since": since}).mappings().first()
    return int(row["total_sales"]) if row else 0


def query_all_sku_status(
    db: Session,
    keyword: Optional[str] = None,
) -> list[dict]:
    """
    一次性查所有产品的 30/90 天销量 + 跨仓库库存汇总 + 安全库存配置。

    返回每行包含: product_id, product_name, model, sales_30d, sales_90d,
    enable_count, real_count, safety_stock, lead_time_days, safety_factor,
    source(int), safety_stock_updated_at, avg_daily_sales_30d, status,
    suggested_qty, data_anomaly, safety_stock_source(label)

    被销量备货一览 + 日报生成 复用。
    """
    business_db = settings.BUSINESS_DB_NAME
    today = date.today()
    d30 = today - timedelta(days=30)
    d90 = today - timedelta(days=90)

    kw_clause = ""
    params: dict[str, Any] = {"d30": d30, "d90": d90}
    if keyword:
        kw_clause = "AND (p.name LIKE :kw OR p.model LIKE :kw OR p.cn_name LIKE :kw)"
        params["kw"] = f"%{keyword}%"

    sql = f"""
        SELECT
            p.product_id                        AS product_id,
            p.name                              AS product_name,
            p.cn_name                           AS cn_name,
            p.model                             AS model,
            COALESCE(SUM(CASE WHEN o.account_date >= :d30 THEN oi.quantity END), 0) AS sales_30d,
            COALESCE(SUM(CASE WHEN o.account_date >= :d90 THEN oi.quantity END), 0) AS sales_90d,
            COALESCE(inv.enable_count, 0)       AS enable_count,
            COALESCE(inv.real_count, 0)         AS real_count,
            COALESCE(ss.safety_stock, 0)        AS safety_stock,
            COALESCE(ss.lead_time_days, 30)     AS lead_time_days,
            COALESCE(ss.safety_factor, 1.50)    AS safety_factor,
            ss.source                           AS source,
            ss.updated_at                       AS safety_stock_updated_at
        FROM `{business_db}`.okki_products p
        LEFT JOIN `{business_db}`.okki_order_items oi
               ON oi.product_id = p.product_id
        LEFT JOIN `{business_db}`.okki_orders o
               ON o.order_id = oi.order_id
              AND {VALID_ORDER_FILTER}
              AND o.account_date >= :d90
        LEFT JOIN (
            SELECT product_id,
                   SUM(enable_count) AS enable_count,
                   SUM(real_count)   AS real_count
            FROM `{business_db}`.okki_inventory
            WHERE disable_flag = 0
            GROUP BY product_id
        ) inv ON inv.product_id = p.product_id
        LEFT JOIN ark_safety_stock ss
               ON ss.product_id = p.product_id
        WHERE p.disable_flag = 0
          {kw_clause}
        GROUP BY p.product_id, p.name, p.cn_name, p.model,
                 inv.enable_count, inv.real_count,
                 ss.safety_stock, ss.lead_time_days, ss.safety_factor,
                 ss.source, ss.updated_at
    """

    rows = db.execute(text(sql), params).mappings().all()

    results: list[dict] = []
    for r in rows:
        sales_30d = int(r["sales_30d"] or 0)
        sales_90d = int(r["sales_90d"] or 0)
        enable_count = float(r["enable_count"] or 0)
        real_count = float(r["real_count"] or 0)
        safety_stock = int(r["safety_stock"] or 0)
        source_int = r["source"] if r["source"] is not None else 0
        status = calc_status(enable_count, safety_stock)
        suggested_qty = calc_suggested_qty(enable_count, safety_stock)
        data_anomaly = enable_count > real_count and real_count > 0
        avg_daily = round(sales_30d / 30, 2) if sales_30d else 0.0

        results.append({
            "product_id": int(r["product_id"]),
            "product_name": r["product_name"] or r["cn_name"] or "",
            "cn_name": r["cn_name"],
            "model": r["model"] or "",
            "sales_30d": sales_30d,
            "sales_90d": sales_90d,
            "avg_daily_sales_30d": avg_daily,
            "enable_count": enable_count,
            "real_count": real_count,
            "safety_stock": safety_stock,
            "lead_time_days": int(r["lead_time_days"] or 30),
            "safety_factor": float(r["safety_factor"] or 1.50),
            "status": status,
            "suggested_qty": suggested_qty,
            "data_anomaly": data_anomaly,
            "safety_stock_source": source_label(source_int) if r["source"] is not None else "",
            "safety_stock_updated_at": (
                r["safety_stock_updated_at"].isoformat()
                if r["safety_stock_updated_at"] else None
            ),
        })

    return results
