"""备货管理 — 安全库存 CRUD + AI 备货建议(TFT 微服务 / 公式兜底)"""

import logging
from datetime import date, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.stock.constants import (
    VALID_ORDER_FILTER, TFT_SERVICE_ENABLED, TFT_SERVICE_URL,
    SOURCE_FORMULA, SOURCE_TFT, SOURCE_INSUFFICIENT,
    source_code, source_label,
)
from app.stock.in_transit_service import get_in_transit_by_product_ids
from app.stock.sku_query import get_sku_sales

logger = logging.getLogger("stock.safety")
settings = get_settings()


def _add_in_clause(
    field_expr: str,
    param_prefix: str,
    raw_value: Optional[str],
    clauses: list[str],
    params: dict[str, Any],
) -> None:
    """辅助: 将逗号分隔值转为 SQL IN 子句。"""
    if not raw_value:
        return
    vals = [v for v in raw_value.split(",") if v]
    if not vals:
        return
    placeholders = ",".join(f":{param_prefix}{i}" for i in range(len(vals)))
    clauses.append(f"{field_expr} IN ({placeholders})")
    for i, v in enumerate(vals):
        params[f"{param_prefix}{i}"] = v


def _name_filter_clauses(
    model: Optional[str] = None,
    product_type: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    weight: Optional[str] = None,
) -> tuple[str, dict[str, Any]]:
    """生成产品型号 + 名称拆分筛选的 SQL 片段与参数。支持逗号分隔多选。"""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    _add_in_clause("p.model", "m", model, clauses, params)
    _add_in_clause("SUBSTRING_INDEX(p.name, '/', 1)", "t", product_type, clauses, params)
    _add_in_clause(
        "SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', 2), '/', -1)", "s", size, clauses, params
    )
    _add_in_clause(
        """CASE
            WHEN (LENGTH(p.name) - LENGTH(REPLACE(p.name, '/', '')) + 1) >= 5
                 AND SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', -3), '/', 1) LIKE '#%'
            THEN CONCAT(
                SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', -3), '/', 1),
                '/',
                SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', -2), '/', 1)
            )
            ELSE SUBSTRING_INDEX(SUBSTRING_INDEX(p.name, '/', -2), '/', 1)
        END""",
        "c", color, clauses, params
    )
    _add_in_clause("SUBSTRING_INDEX(p.name, '/', -1)", "w", weight, clauses, params)
    sql = " AND ".join(clauses)
    return (f"AND {sql}" if sql else ""), params


def query_safety_stock_list(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    keyword: Optional[str] = None,
    model: Optional[str] = None,
    product_type: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    weight: Optional[str] = None,
    sort_by: str = "product_id",
    order: str = "asc",
    has_in_transit: Optional[bool] = None,
    has_safety_stock: Optional[bool] = None,
    stock_status: Optional[str] = None,
) -> dict:
    """安全库存设置页用,展示 SKU 基本信息 + 当前配置 + 30 天销量(轻量)"""
    business_db = settings.BUSINESS_DB_NAME

    kw_clause = ""
    params: dict[str, Any] = {}
    if keyword:
        kw_clause = "AND (p.name LIKE :kw OR p.model LIKE :kw OR p.cn_name LIKE :kw)"
        params["kw"] = f"%{keyword}%"

    name_clause, name_params = _name_filter_clauses(
        model=model,
        product_type=product_type,
        size=size,
        color=color,
        weight=weight,
    )
    params.update(name_params)

    # 排序映射
    sort_map = {
        "product_id": "p.product_id",
        "sales_30d": "COALESCE(SUM(CASE WHEN o.account_date >= :d30 THEN oi.quantity END), 0)",
        "enable_count": "COALESCE(inv.enable_count, 0)",
        "safety_stock": "COALESCE(ss.safety_stock, 0)",
    }
    order_col = sort_map.get(sort_by, "p.product_id")
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    order_by = f"ORDER BY {order_col} {order_dir}, p.product_id ASC"

    # 额外筛选条件
    extra_clauses = ""

    if has_in_transit is True:
        extra_clauses += """
            AND EXISTS (
                SELECT 1 FROM ark_production_order_items i
                JOIN ark_production_orders o ON o.id = i.order_id
                WHERE i.product_id = p.product_id
                  AND i.status = 0 AND o.status = 0 AND o.deleted_flag = 0
                HAVING SUM(i.order_qty - i.received_qty) > 0
            )"""

    if has_safety_stock is True:
        extra_clauses += """
            AND EXISTS (
                SELECT 1 FROM ark_safety_stock ss2
                WHERE ss2.product_id = p.product_id AND ss2.safety_stock > 0
            )"""

    if stock_status == "urgent":
        extra_clauses += """
            AND EXISTS (
                SELECT 1 FROM ark_production_order_items i
                JOIN ark_production_orders o ON o.id = i.order_id
                WHERE i.product_id = p.product_id
                  AND i.status = 0 AND i.is_urgent = 1
                  AND o.status = 0 AND o.deleted_flag = 0
            )"""
    elif stock_status == "stocking":
        extra_clauses += """
            AND EXISTS (
                SELECT 1 FROM ark_production_order_items i
                JOIN ark_production_orders o ON o.id = i.order_id
                WHERE i.product_id = p.product_id
                  AND i.status = 0
                  AND o.status = 0 AND o.deleted_flag = 0
            )
            AND NOT EXISTS (
                SELECT 1 FROM ark_production_order_items i
                JOIN ark_production_orders o ON o.id = i.order_id
                WHERE i.product_id = p.product_id
                  AND i.status = 0 AND i.is_urgent = 1
                  AND o.status = 0 AND o.deleted_flag = 0
            )"""

    today = date.today()
    d30 = today - timedelta(days=30)
    params.update({
        "d30": d30,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    })

    # 先取总数(排除分页参数)
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset", "d30")}
    count_sql = f"""
        SELECT COUNT(*) AS cnt
        FROM `{business_db}`.okki_products p
        WHERE p.disable_flag = 0
          {kw_clause}
          {name_clause}
          {extra_clauses}
    """
    total = db.execute(text(count_sql), count_params).scalar() or 0

    sql = f"""
        SELECT
            p.product_id                        AS product_id,
            p.name                              AS product_name,
            p.cn_name                           AS cn_name,
            p.model                             AS model,
            COALESCE(SUM(CASE WHEN o.account_date >= :d30 THEN oi.quantity END), 0) AS sales_30d,
            COALESCE(inv.enable_count, 0)       AS enable_count,
            COALESCE(ss.safety_stock, 0)        AS safety_stock,
            COALESCE(ss.lead_time_days, 30)     AS lead_time_days,
            COALESCE(ss.safety_factor, 1.50)    AS safety_factor,
            ss.source                           AS source,
            ss.updated_by                       AS updated_by,
            ss.updated_at                       AS updated_at
        FROM `{business_db}`.okki_products p
        LEFT JOIN `{business_db}`.okki_order_items oi
               ON oi.product_id = p.product_id
        LEFT JOIN `{business_db}`.okki_orders o
               ON o.order_id = oi.order_id
              AND {VALID_ORDER_FILTER}
              AND o.account_date >= :d30
        LEFT JOIN (
            SELECT product_id,
                   SUM(enable_count) AS enable_count
            FROM `{business_db}`.okki_inventory
            WHERE disable_flag = 0
            GROUP BY product_id
        ) inv ON inv.product_id = p.product_id
        LEFT JOIN ark_safety_stock ss
               ON ss.product_id = p.product_id
        WHERE p.disable_flag = 0
          {kw_clause}
          {name_clause}
          {extra_clauses}
        GROUP BY p.product_id, p.name, p.cn_name, p.model,
                 inv.enable_count,
                 ss.safety_stock, ss.lead_time_days, ss.safety_factor,
                 ss.source, ss.updated_by, ss.updated_at
        {order_by}
        LIMIT :limit OFFSET :offset
    """

    rows = db.execute(text(sql), params).mappings().all()

    # 批量查询生产在途数量
    product_ids = [int(r["product_id"]) for r in rows]
    in_transit_map = get_in_transit_by_product_ids(db, product_ids)

    items = []
    for r in rows:
        sales_30d = int(r["sales_30d"] or 0)
        avg_daily = round(sales_30d / 30, 2) if sales_30d else 0.0
        source_int = r["source"]
        enable_count = float(r["enable_count"] or 0)
        production_in_transit = in_transit_map.get(int(r["product_id"]), 0)
        items.append({
            "product_id": int(r["product_id"]),
            "product_name": r["product_name"] or r["cn_name"] or "",
            "cn_name": r["cn_name"],
            "model": r["model"] or "",
            "sales_30d": sales_30d,
            "avg_daily_sales_30d": avg_daily,
            "enable_count": enable_count,
            "production_in_transit": production_in_transit,
            "safety_stock": int(r["safety_stock"] or 0),
            "lead_time_days": int(r["lead_time_days"] or 30),
            "safety_factor": float(r["safety_factor"] or 1.50),
            "source": source_label(source_int) if source_int is not None else "",
            "updated_by": r["updated_by"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        })

    return {"total": int(total), "items": items}


def save_safety_stock(
    db: Session,
    items: list[dict],
    lead_time_days: int,
    safety_factor: float,
    source: str,
    updated_by: int,
) -> dict:
    """
    批量保存,返回 {saved: [pids], failed: [{product_id, reason}]}
    - items 元素: {product_id, safety_stock, updated_at?(乐观锁)}
    - 乐观锁: 若 items 携带 updated_at,服务端校验未变化
    - 校验 product_id 在 okki_products 存在
    - 使用 INSERT ... ON DUPLICATE KEY UPDATE
    """
    business_db = settings.BUSINESS_DB_NAME
    saved: list[int] = []
    failed: list[dict] = []
    source_int = source_code(source)

    for item in items:
        pid = item.get("product_id")
        stock = item.get("safety_stock", 0)
        client_updated_at = item.get("updated_at")

        if pid is None or not isinstance(pid, int):
            failed.append({"product_id": pid, "reason": "product_id 缺失或非法"})
            continue
        if stock < 0:
            failed.append({"product_id": pid, "reason": "safety_stock 不能为负"})
            continue

        # 乐观锁校验
        if client_updated_at:
            existing = db.execute(
                text("SELECT updated_at FROM ark_safety_stock WHERE product_id = :pid"),
                {"pid": pid},
            ).mappings().first()
            if existing and existing["updated_at"]:
                server_ts = existing["updated_at"].isoformat()
                # 客户端传的可能是 ISO 字符串,与 isoformat 比较
                if server_ts != client_updated_at:
                    failed.append({"product_id": pid, "reason": "数据已被他人修改,请刷新后重试"})
                    continue

        # 校验产品存在
        exists = db.execute(
            text(f"SELECT 1 FROM `{business_db}`.okki_products WHERE product_id = :pid AND disable_flag = 0"),
            {"pid": pid},
        ).first()
        if not exists:
            failed.append({"product_id": pid, "reason": "product_id 不存在或已停用"})
            continue

        # UPSERT
        upsert_sql = """
            INSERT INTO ark_safety_stock
              (product_id, safety_stock, lead_time_days, safety_factor, source, updated_by, updated_at, created_at)
            VALUES (:product_id, :safety_stock, :lead_time_days, :safety_factor, :source, :updated_by, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
              safety_stock   = VALUES(safety_stock),
              lead_time_days = VALUES(lead_time_days),
              safety_factor  = VALUES(safety_factor),
              source         = VALUES(source),
              updated_by     = VALUES(updated_by),
              updated_at     = NOW()
        """
        db.execute(text(upsert_sql), {
            "product_id": pid,
            "safety_stock": stock,
            "lead_time_days": lead_time_days,
            "safety_factor": safety_factor,
            "source": source_int,
            "updated_by": updated_by,
        })
        saved.append(pid)

    db.commit()
    return {"saved": saved, "failed": failed}


async def get_safety_stock_suggestion(
    db: Session,
    product_id: int,
    lead_time_days: int,
    safety_factor: float,
    history_days: int = 90,
) -> dict:
    """
    单 SKU 安全库存建议。
    - TFT_SERVICE_ENABLED=True 时尝试调微服务,失败回退公式
    - 公式: avg_daily_sales × lead_time_days × safety_factor
    - 销量为 0 时返回 insufficient_data
    """
    # 尝试 TFT
    if TFT_SERVICE_ENABLED and TFT_SERVICE_URL:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    TFT_SERVICE_URL,
                    json={"product_id": product_id, "history_days": history_days},
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "product_id": product_id,
                    "suggested_safety_stock": data.get("suggested_safety_stock"),
                    "predicted_30d_sales": data.get("predicted_30d_sales"),
                    "confidence_interval": data.get("confidence_interval"),
                    "source": SOURCE_TFT,
                    "model_version": data.get("model_version"),
                }
        except Exception as e:
            logger.warning("TFT 服务不可用,降级公式: %s", e)

    # 公式兜底
    sales = get_sku_sales(db, product_id, days=history_days)
    if sales == 0:
        return {
            "product_id": product_id,
            "suggested_safety_stock": None,
            "predicted_30d_sales": 0,
            "confidence_interval": None,
            "source": SOURCE_INSUFFICIENT,
            "model_version": None,
            "note": "销量数据不足,请手动设置",
        }

    avg_daily = sales / history_days if history_days > 0 else 0
    suggested = round(avg_daily * lead_time_days * safety_factor)
    return {
        "product_id": product_id,
        "suggested_safety_stock": suggested,
        "predicted_30d_sales": round(avg_daily * 30),
        "avg_daily_sales": round(avg_daily, 2),
        "confidence_interval": None,
        "source": SOURCE_FORMULA,
        "model_version": None,
    }


async def batch_generate_suggestions(
    db: Session,
    product_ids: Optional[list[int]],
    lead_time_days: int,
    safety_factor: float,
    history_days: int = 90,
) -> dict:
    """
    批量生成。product_ids=None 时查全部启用产品。
    返回 {source: 'formula'|'tft', tft_available: bool, items: [...]}
    """
    business_db = settings.BUSINESS_DB_NAME

    if not product_ids:
        rows = db.execute(
            text(f"SELECT product_id FROM `{business_db}`.okki_products WHERE disable_flag = 0")
        ).all()
        product_ids = [int(r[0]) for r in rows]

    # 一次取 product 基础信息+当前安全库存,避免每条单独查
    if not product_ids:
        return {"source": SOURCE_FORMULA, "tft_available": TFT_SERVICE_ENABLED, "items": []}

    placeholders = ",".join([f":p{i}" for i in range(len(product_ids))])
    params = {f"p{i}": pid for i, pid in enumerate(product_ids)}
    info_sql = f"""
        SELECT p.product_id, p.name AS product_name, p.cn_name, p.model,
               COALESCE(ss.safety_stock, 0) AS current_safety_stock
        FROM `{business_db}`.okki_products p
        LEFT JOIN ark_safety_stock ss ON ss.product_id = p.product_id
        WHERE p.product_id IN ({placeholders})
    """
    info_rows = db.execute(text(info_sql), params).mappings().all()
    info_map = {int(r["product_id"]): dict(r) for r in info_rows}

    items: list[dict] = []
    used_sources: set[str] = set()

    for pid in product_ids:
        info = info_map.get(int(pid)) or {}
        suggestion = await get_safety_stock_suggestion(
            db, pid, lead_time_days, safety_factor, history_days,
        )
        used_sources.add(suggestion["source"])
        items.append({
            "product_id": int(pid),
            "product_name": info.get("product_name") or info.get("cn_name") or "",
            "model": info.get("model") or "",
            "current_safety_stock": int(info.get("current_safety_stock") or 0),
            **suggestion,
        })

    overall = SOURCE_TFT if SOURCE_TFT in used_sources else SOURCE_FORMULA
    return {
        "source": overall,
        "source_label": "TFT 预测" if overall == SOURCE_TFT else "公式估算",
        "tft_available": TFT_SERVICE_ENABLED,
        "items": items,
    }
