"""备货管理 — 业务逻辑层

数据库约定:
- 提成库 (commission_db): SafetyStock / StockDailyReport 等本模块表
- 业务库 (lsordertest, 只读): okki_products / okki_order_items / okki_orders / okki_inventory
- 跨库 JOIN 用 `{settings.BUSINESS_DB_NAME}.okki_xxx` 显式带库名

订单口径(与提成模块一致):
- status = 13972831656 (已结束)
- 或 status = 13972831654 AND status_name = '已结清'
- 且 departments JSON 列包含 7 个指定 department_id
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.stock.models import SafetyStock, StockDailyReport

logger = logging.getLogger("stock")
settings = get_settings()

# ── 订单口径常量 ────────────────────────────────────────
VALID_ORDER_FILTER = """
    (
        o.status = 13972831656
        OR (o.status = 13972831654 AND o.status_name = '已结清')
    )
    AND (
        o.departments LIKE '%"department_id": 24925%'
        OR o.departments LIKE '%"department_id": 24926%'
        OR o.departments LIKE '%"department_id": 25198%'
        OR o.departments LIKE '%"department_id": 258938%'
        OR o.departments LIKE '%"department_id": 258940%'
        OR o.departments LIKE '%"department_id": 258941%'
        OR o.departments LIKE '%"department_id": 258942%'
    )
"""

# ── TFT 配置(可选,默认关闭) ──────────────────────────────
TFT_SERVICE_ENABLED = os.environ.get("TFT_SERVICE_ENABLED", "").lower() in {"1", "true", "yes"}
TFT_SERVICE_URL = os.environ.get("TFT_SERVICE_URL", "")

# 来源枚举
SOURCE_MANUAL = "manual"
SOURCE_FORMULA = "formula"
SOURCE_TFT = "tft"
SOURCE_INSUFFICIENT = "insufficient_data"


# ── 状态计算 ────────────────────────────────────────────
def calc_status(enable_count: float, safety_stock: int) -> str:
    """库存状态: unset / shortage / warning / sufficient"""
    if not safety_stock or safety_stock == 0:
        return "unset"
    if enable_count < safety_stock:
        return "shortage"
    if enable_count < safety_stock * 1.5:
        return "warning"
    return "sufficient"


def calc_suggested_qty(enable_count: float, safety_stock: int) -> int:
    """建议备货量 = max(0, safety_stock × 2 - enable_count)"""
    return max(0, int(safety_stock) * 2 - int(enable_count))


def _source_label(code: int) -> str:
    """source 整数码 → 字符串标签"""
    return {0: SOURCE_MANUAL, 1: SOURCE_FORMULA, 2: SOURCE_TFT}.get(int(code or 0), SOURCE_MANUAL)


def _source_code(label: str) -> int:
    """source 字符串 → 整数码"""
    return {SOURCE_MANUAL: 0, SOURCE_FORMULA: 1, SOURCE_TFT: 2}.get(label, 0)


# ── 销量查询 ────────────────────────────────────────────
def get_sku_sales(db: Session, product_id: int, days: int) -> int:
    """指定 SKU 最近 N 天的销量(只统计已结束订单+7个指定部门)"""
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


# ── 全量库存状态查询(给概览页和日报复用) ───────────────────
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
            "safety_stock_source": _source_label(source_int) if r["source"] is not None else "",
            "safety_stock_updated_at": (
                r["safety_stock_updated_at"].isoformat()
                if r["safety_stock_updated_at"] else None
            ),
        })

    return results


# ── 销量备货一览(分页+筛选) ────────────────────────────────
def query_stock_overview(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[list[str]] = None,
    sort_by: str = "sales_30d",
    order: str = "desc",
    keyword: Optional[str] = None,
) -> dict:
    """销量备货一览,返回分页 + 统计摘要"""
    all_items = query_all_sku_status(db, keyword=keyword)

    # 统计(在筛选之前,反映总体)
    summary = {"shortage_count": 0, "warning_count": 0, "sufficient_count": 0, "unset_count": 0}
    for it in all_items:
        st = it["status"]
        if st == "shortage":
            summary["shortage_count"] += 1
        elif st == "warning":
            summary["warning_count"] += 1
        elif st == "sufficient":
            summary["sufficient_count"] += 1
        elif st == "unset":
            summary["unset_count"] += 1

    # 状态筛选
    if status_filter:
        all_items = [it for it in all_items if it["status"] in status_filter]

    # 排序
    valid_sorts = {"sales_30d", "sales_90d", "enable_count"}
    sort_key = sort_by if sort_by in valid_sorts else "sales_30d"
    reverse = (order == "desc")
    all_items.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)

    # 分页
    total = len(all_items)
    start = (page - 1) * page_size
    items = all_items[start:start + page_size]

    return {"total": total, "summary": summary, "items": items}


# ── 安全库存列表(轻量,只查 product + safety_stock,不算销量) ──
def query_safety_stock_list(
    db: Session,
    page: int = 1,
    page_size: int = 50,
    keyword: Optional[str] = None,
) -> dict:
    """安全库存设置页用,展示 SKU 基本信息 + 当前配置 + 30 天销量(轻量)"""
    business_db = settings.BUSINESS_DB_NAME

    kw_clause = ""
    params: dict[str, Any] = {}
    if keyword:
        kw_clause = "AND (p.name LIKE :kw OR p.model LIKE :kw OR p.cn_name LIKE :kw)"
        params["kw"] = f"%{keyword}%"

    # 先取总数
    count_sql = f"""
        SELECT COUNT(*) AS cnt
        FROM `{business_db}`.okki_products p
        WHERE p.disable_flag = 0
          {kw_clause}
    """
    total = db.execute(text(count_sql), params).scalar() or 0

    today = date.today()
    d30 = today - timedelta(days=30)
    params.update({
        "d30": d30,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    })

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
        GROUP BY p.product_id, p.name, p.cn_name, p.model,
                 inv.enable_count,
                 ss.safety_stock, ss.lead_time_days, ss.safety_factor,
                 ss.source, ss.updated_by, ss.updated_at
        ORDER BY p.product_id
        LIMIT :limit OFFSET :offset
    """

    rows = db.execute(text(sql), params).mappings().all()
    items = []
    for r in rows:
        sales_30d = int(r["sales_30d"] or 0)
        avg_daily = round(sales_30d / 30, 2) if sales_30d else 0.0
        source_int = r["source"]
        items.append({
            "product_id": int(r["product_id"]),
            "product_name": r["product_name"] or r["cn_name"] or "",
            "cn_name": r["cn_name"],
            "model": r["model"] or "",
            "sales_30d": sales_30d,
            "avg_daily_sales_30d": avg_daily,
            "enable_count": float(r["enable_count"] or 0),
            "safety_stock": int(r["safety_stock"] or 0),
            "lead_time_days": int(r["lead_time_days"] or 30),
            "safety_factor": float(r["safety_factor"] or 1.50),
            "source": _source_label(source_int) if source_int is not None else "",
            "updated_by": r["updated_by"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        })

    return {"total": int(total), "items": items}


# ── 批量保存安全库存(乐观锁 + UPSERT) ────────────────────
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
    source_int = _source_code(source)

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


# ── AI 备货建议(单条) ──────────────────────────────────
async def get_safety_stock_suggestion(
    db: Session,
    product_id: int,
    lead_time_days: int,
    safety_factor: float,
    history_days: int = 30,
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


# ── 批量 AI 建议 ────────────────────────────────────────
async def batch_generate_suggestions(
    db: Session,
    product_ids: Optional[list[int]],
    lead_time_days: int,
    safety_factor: float,
    history_days: int = 30,
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


# ── 日报相关 ────────────────────────────────────────────
def upsert_daily_report(
    db: Session,
    report_date_value: date,
    shortage_skus: list[dict],
    warning_skus: list[dict],
    summary: dict,
) -> StockDailyReport:
    """写入或更新当日日报。"""
    existing = (
        db.query(StockDailyReport)
        .filter(StockDailyReport.report_date == report_date_value)
        .first()
    )
    if existing:
        existing.shortage_count = summary.get("shortage_count", 0)
        existing.warning_count = summary.get("warning_count", 0)
        existing.sufficient_count = summary.get("sufficient_count", 0)
        existing.shortage_skus = _serialize_skus(shortage_skus)
        existing.warning_skus = _serialize_skus(warning_skus)
        db.commit()
        return existing

    rec = StockDailyReport(
        report_date=report_date_value,
        shortage_count=summary.get("shortage_count", 0),
        warning_count=summary.get("warning_count", 0),
        sufficient_count=summary.get("sufficient_count", 0),
        shortage_skus=_serialize_skus(shortage_skus),
        warning_skus=_serialize_skus(warning_skus),
        dingtalk_sent=0,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _serialize_skus(skus: list[dict]) -> list[dict]:
    """提取日报需要的字段精简存库"""
    keep = ["product_id", "product_name", "model", "enable_count",
            "safety_stock", "avg_daily_sales_30d", "suggested_qty"]
    return [{k: it.get(k) for k in keep if k in it} for it in skus]


def get_daily_report(db: Session, report_date_value: Optional[date] = None) -> Optional[dict]:
    """
    获取日报。report_date=None 时取最新一条。
    返回 dict 或 None。
    """
    q = db.query(StockDailyReport)
    if report_date_value:
        rec = q.filter(StockDailyReport.report_date == report_date_value).first()
    else:
        rec = q.order_by(StockDailyReport.report_date.desc()).first()

    if not rec:
        return None

    return {
        "id": rec.id,
        "report_date": rec.report_date.isoformat(),
        "shortage_count": rec.shortage_count,
        "warning_count": rec.warning_count,
        "sufficient_count": rec.sufficient_count,
        "shortage_skus": rec.shortage_skus or [],
        "warning_skus": rec.warning_skus or [],
        "dingtalk_sent": bool(rec.dingtalk_sent),
        "sent_at": rec.sent_at.isoformat() if rec.sent_at else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def mark_daily_report_pushed(db: Session, report_date_value: date) -> None:
    """标记钉钉已推送"""
    rec = (
        db.query(StockDailyReport)
        .filter(StockDailyReport.report_date == report_date_value)
        .first()
    )
    if rec:
        rec.dingtalk_sent = 1
        rec.sent_at = datetime.utcnow()
        db.commit()


def get_stock_recipients(db: Session) -> list[str]:
    """
    返回需要接收库存日报的钉钉 user_id 列表。
    口径: 拥有 stock:read 或 stock:admin 权限的活跃用户(含 super_admin)。
    """
    sql = """
        SELECT DISTINCT u.dingtalk_id
        FROM ark_users u
        LEFT JOIN ark_user_roles ur ON ur.user_id = u.id
        LEFT JOIN ark_roles r       ON r.id = ur.role_id
        LEFT JOIN ark_role_permissions rp ON rp.role_id = r.id
        LEFT JOIN ark_permissions p ON p.id = rp.permission_id
        WHERE u.is_active = 1
          AND u.dingtalk_id IS NOT NULL
          AND u.dingtalk_id <> ''
          AND (
              r.name = 'super_admin'
              OR p.code IN ('stock:read', 'stock:admin')
          )
    """
    rows = db.execute(text(sql)).all()
    return [str(r[0]) for r in rows if r[0]]
