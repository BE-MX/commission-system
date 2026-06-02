"""备货管理 — 销量备货一览(SQL 分页 + 状态过滤 + 摘要统计)

性能策略:
- 状态、在途、可用库存、安全库存全部下沉到一条 SQL,服务端分页。
- 销量 (30/90d) 通过 derived subquery 聚合一次,避免主查询 GROUP BY。
- 备货状态明细 (stock_items) 仅查询当前页的 product_ids,前端不再串行二次请求。
- 摘要 (summary) 单独跑一条轻量 GROUP BY status 查询,反映 keyword 范围内的总体分布。
"""

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.stock._filters import name_filter_clauses
from app.stock.constants import VALID_ORDER_FILTER, calc_suggested_qty
from app.stock.production_order_service import get_stock_status_by_product_ids


def _parse_name(name: str) -> dict:
    """产品名称拆分: 类型/尺寸/颜色/克重 (与前端 parseProductName 等价)。"""
    if not name:
        return {"type": "", "size": "", "color": "", "weight": ""}
    parts = name.split("/")
    n = len(parts)
    t = parts[0] if n > 0 else ""
    s = parts[1] if n > 1 else ""
    if n >= 5 and parts[-3].startswith("#"):
        c = f"{parts[-3]}/{parts[-2]}"
    else:
        c = parts[-2] if n >= 2 else ""
    w = parts[-1] if n >= 1 else ""
    return {"type": t, "size": s, "color": c, "weight": w}


# ── 排序列映射 ─────────────────────────────────────────────
# 主查询 derived table 内字段,可在外层 ORDER BY 直接引用
_SORT_MAP = {
    "sales_30d": "sales_30d",
    "sales_90d": "sales_90d",
    "avg_daily_sales_30d": "sales_30d",  # 等价于按 30d 销量
    "enable_count": "enable_count",
    "real_count": "real_count",
    "effective_enable_count": "effective_enable_count",
    "production_in_transit": "production_in_transit",
    "safety_stock": "safety_stock",
    "model": "model",
    "product_id": "product_id",
    "color": "product_name",
}


def query_stock_overview(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[list[str]] = None,
    sort_by: str = "sales_30d",
    order: str = "desc",
    keyword: Optional[str] = None,
    model: Optional[str] = None,
    product_type: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    weight: Optional[str] = None,
) -> dict:
    """销量备货一览,返回 {total, summary, items}。

    items 已经包含 stock_status / stock_items, 前端无需二次请求。
    """
    settings = get_settings()
    business_db = settings.BUSINESS_DB_NAME
    today = date.today()
    d30 = today - timedelta(days=30)
    d90 = today - timedelta(days=90)

    # ── 筛选片段 ──────────────────────────────────────────
    kw_clause = ""
    kw_params: dict = {}
    if keyword:
        kw_clause = "AND (p.name LIKE :kw OR p.model LIKE :kw OR p.cn_name LIKE :kw)"
        kw_params["kw"] = f"%{keyword}%"

    name_clause, name_params = name_filter_clauses(model, product_type, size, color, weight)

    status_in_clause = ""
    status_params: dict = {}
    if status_filter:
        placeholders = ",".join(f":st{i}" for i in range(len(status_filter)))
        status_in_clause = f"WHERE status IN ({placeholders})"
        for i, s in enumerate(status_filter):
            status_params[f"st{i}"] = s

    # ── 共用 JOIN (不带销量,用于 count / summary) ────────
    base_no_sales = f"""
        FROM `{business_db}`.okki_products p
        LEFT JOIN (
            SELECT product_id,
                   SUM(enable_count) AS enable_count,
                   SUM(real_count)   AS real_count
            FROM `{business_db}`.okki_inventory
            WHERE disable_flag = 0
            GROUP BY product_id
        ) inv ON inv.product_id = p.product_id
        LEFT JOIN ark_safety_stock ss ON ss.product_id = p.product_id
        LEFT JOIN (
            SELECT i.product_id,
                   SUM(i.order_qty - i.received_qty) AS in_transit_qty,
                   MAX(i.is_urgent)                  AS has_urgent
            FROM ark_production_order_items i
            JOIN ark_production_orders o ON o.id = i.order_id
            WHERE i.status = 0 AND o.status = 0 AND o.deleted_flag = 0
            GROUP BY i.product_id
        ) it ON it.product_id = p.product_id
    """

    status_case = """
        CASE
            WHEN COALESCE(ss.safety_stock, 0) = 0 THEN 'unset'
            WHEN (COALESCE(inv.enable_count, 0) + COALESCE(it.in_transit_qty, 0)) < ss.safety_stock THEN 'shortage'
            WHEN (COALESCE(inv.enable_count, 0) + COALESCE(it.in_transit_qty, 0)) < ss.safety_stock * 1.5 THEN 'warning'
            ELSE 'sufficient'
        END
    """

    # ── 1. 摘要 (仅 keyword 过滤,反映总体) ────────────────
    summary_sql = f"""
        SELECT status, COUNT(*) AS cnt FROM (
            SELECT p.product_id, {status_case} AS status
            {base_no_sales}
            WHERE p.disable_flag = 0
              {kw_clause}
        ) t GROUP BY status
    """
    summary = {"shortage_count": 0, "warning_count": 0, "sufficient_count": 0, "unset_count": 0}
    for r in db.execute(text(summary_sql), kw_params).mappings().all():
        st = r["status"]
        summary[f"{st}_count"] = int(r["cnt"])

    # ── 2. 总数 (含 keyword + 名称 + 状态过滤) ────────────
    count_sql = f"""
        SELECT COUNT(*) FROM (
            SELECT p.product_id, {status_case} AS status
            {base_no_sales}
            WHERE p.disable_flag = 0
              {kw_clause}
              {name_clause}
        ) t {status_in_clause}
    """
    count_params = {**kw_params, **name_params, **status_params}
    total = int(db.execute(text(count_sql), count_params).scalar() or 0)

    if total == 0:
        return {"total": 0, "summary": summary, "items": []}

    # ── 3. 分页数据 (含销量 + 状态过滤 + 排序) ────────────
    sort_col = _SORT_MAP.get(sort_by, "sales_30d")
    sort_dir = "DESC" if (order or "").lower() == "desc" else "ASC"

    data_sql = f"""
        SELECT * FROM (
            SELECT
                p.product_id                                AS product_id,
                p.name                                      AS product_name,
                p.cn_name                                   AS cn_name,
                p.model                                     AS model,
                COALESCE(inv.enable_count, 0)               AS enable_count,
                COALESCE(inv.real_count, 0)                 AS real_count,
                COALESCE(ss.safety_stock, 0)                AS safety_stock,
                COALESCE(ss.lead_time_days, 30)             AS lead_time_days,
                COALESCE(ss.safety_factor, 1.50)            AS safety_factor,
                ss.source                                   AS source,
                ss.updated_at                               AS safety_stock_updated_at,
                COALESCE(it.in_transit_qty, 0)              AS production_in_transit,
                COALESCE(it.has_urgent, 0)                  AS has_urgent,
                COALESCE(inv.enable_count, 0) + COALESCE(it.in_transit_qty, 0) AS effective_enable_count,
                COALESCE(sales.sales_30d, 0)                AS sales_30d,
                COALESCE(sales.sales_90d, 0)                AS sales_90d,
                {status_case} AS status
            {base_no_sales}
            LEFT JOIN (
                SELECT
                    oi.product_id,
                    SUM(CASE WHEN o.account_date >= :d30 THEN oi.quantity END) AS sales_30d,
                    SUM(oi.quantity)                                           AS sales_90d
                FROM `{business_db}`.okki_order_items oi
                JOIN `{business_db}`.okki_orders o ON o.order_id = oi.order_id
                WHERE o.account_date >= :d90
                  AND {VALID_ORDER_FILTER}
                GROUP BY oi.product_id
            ) sales ON sales.product_id = p.product_id
            WHERE p.disable_flag = 0
              {kw_clause}
              {name_clause}
        ) t
        {status_in_clause}
        ORDER BY {sort_col} {sort_dir}, product_id ASC
        LIMIT :limit OFFSET :offset
    """
    data_params = {
        **count_params,
        "d30": d30,
        "d90": d90,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    rows = db.execute(text(data_sql), data_params).mappings().all()

    # ── 4. 当前页备货明细 (生产中订单列表) ───────────────
    page_pids = [int(r["product_id"]) for r in rows]
    stock_status_map = get_stock_status_by_product_ids(db, page_pids) if page_pids else {}

    items: list[dict] = []
    for r in rows:
        pid = int(r["product_id"])
        sales_30d = int(r["sales_30d"] or 0)
        sales_90d = int(r["sales_90d"] or 0)
        enable_count = float(r["enable_count"] or 0)
        real_count = float(r["real_count"] or 0)
        safety_stock = int(r["safety_stock"] or 0)
        production_in_transit = int(r["production_in_transit"] or 0)
        effective_enable_count = enable_count + production_in_transit
        suggested_qty = calc_suggested_qty(effective_enable_count, safety_stock)
        avg_daily = round(sales_30d / 30, 2) if sales_30d else 0.0
        data_anomaly = enable_count > real_count and real_count > 0

        ss_entry = stock_status_map.get(pid) or {"stock_status": "", "items": []}

        items.append({
            "product_id": pid,
            "product_name": r["product_name"] or r["cn_name"] or "",
            "cn_name": r["cn_name"],
            "model": r["model"] or "",
            "sales_30d": sales_30d,
            "sales_90d": sales_90d,
            "avg_daily_sales_30d": avg_daily,
            "enable_count": enable_count,
            "production_in_transit": production_in_transit,
            "effective_enable_count": effective_enable_count,
            "real_count": real_count,
            "safety_stock": safety_stock,
            "lead_time_days": int(r["lead_time_days"] or 30),
            "safety_factor": float(r["safety_factor"] or 1.50),
            "status": r["status"],
            "suggested_qty": suggested_qty,
            "data_anomaly": data_anomaly,
            "safety_stock_source": _source_label_or_empty(r["source"]),
            "safety_stock_updated_at": (
                r["safety_stock_updated_at"].isoformat()
                if r["safety_stock_updated_at"] else None
            ),
            "stock_status": ss_entry["stock_status"],
            "stock_items": ss_entry.get("items", []),
        })

    return {"total": total, "summary": summary, "items": items}


def _source_label_or_empty(source_int) -> str:
    """ss.source 整数码 → 字符串标签,NULL → ''"""
    if source_int is None:
        return ""
    from app.stock.constants import source_label
    return source_label(source_int)


# ── 筛选维度可选值 ────────────────────────────────────────

def get_filter_options(db: Session) -> dict:
    """返回所有启用产品的筛选维度可选值(model/type/size/color/weight)。"""
    settings = get_settings()
    business_db = settings.BUSINESS_DB_NAME

    model_rows = db.execute(
        text(f"""
            SELECT DISTINCT model
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND model IS NOT NULL AND model != ''
            ORDER BY model
        """)
    ).all()
    models = [r[0] for r in model_rows]

    type_rows = db.execute(
        text(f"""
            SELECT DISTINCT SUBSTRING_INDEX(name, '/', 1) AS val
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND name LIKE '%/%'
            ORDER BY val
        """)
    ).all()
    types = [r[0] for r in type_rows if r[0]]

    size_rows = db.execute(
        text(f"""
            SELECT DISTINCT SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', 2), '/', -1) AS val
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND name LIKE '%/%/%'
            ORDER BY val
        """)
    ).all()
    sizes = [r[0] for r in size_rows if r[0]]

    color_rows = db.execute(
        text(f"""
            SELECT DISTINCT
                CASE
                    WHEN (LENGTH(name) - LENGTH(REPLACE(name, '/', '')) + 1) >= 5
                         AND SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', -3), '/', 1) LIKE '#%'
                    THEN CONCAT(
                        SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', -3), '/', 1),
                        '/',
                        SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', -2), '/', 1)
                    )
                    ELSE SUBSTRING_INDEX(SUBSTRING_INDEX(name, '/', -2), '/', 1)
                END AS val
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND name LIKE '%/%/%/%'
            ORDER BY val
        """)
    ).all()
    colors = [r[0] for r in color_rows if r[0]]

    weight_rows = db.execute(
        text(f"""
            SELECT DISTINCT SUBSTRING_INDEX(name, '/', -1) AS val
            FROM `{business_db}`.okki_products
            WHERE disable_flag = 0 AND name LIKE '%/%'
            ORDER BY val
        """)
    ).all()
    weights = [r[0] for r in weight_rows if r[0]]

    return {
        "models": models,
        "types": types,
        "sizes": sizes,
        "colors": colors,
        "weights": weights,
    }
