"""产品风向标业务服务：历史品名映射的预填、查询、确认与月度可信度。"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import beijing_now, beijing_today
from app.product_sales import metrics
from app.report.category_service import OTHER_CATEGORY_INDEX, classify
from app.product_sales.models import (
    MAPPING_CONFIRMED,
    MAPPING_IGNORED,
    MAPPING_STATUSES,
    MAPPING_SUGGESTED,
    ProductSalesNameMapping,
)

logger = logging.getLogger("product_sales")

RULE_VERSION = "v1"
HISTORY_START = date(2025, 1, 1)
MAX_GRAMS = Decimal("5000")
_NAME_GRAMS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:克|g\b)", re.IGNORECASE)


def _model_key(name: object) -> str:
    """型号比对键：在规范化基础上去掉旧产品库常见的「新」前缀词（B3新天才发帘 ≈ B3天才发帘）。"""
    return metrics.normalize_name(name).replace("新", "").replace(" ", "")


def _model_grams_index(lines: list[dict]) -> dict[str, tuple[str, Decimal]]:
    """当前产品表型号 → (型号原值, 该型号最常见克重)。只用 exact 行，避免循环自证。"""
    counts: dict[str, Counter] = defaultdict(Counter)
    labels: dict[str, str] = {}
    for line in lines:
        if line["confidence"] != metrics.EXACT or line["model"] == metrics.UNKNOWN_LABEL:
            continue
        key = _model_key(line["model"])
        labels.setdefault(key, line["model"])
        counts[key][line["unit_grams"]] += 1
    return {key: (labels[key], counter.most_common(1)[0][0]) for key, counter in counts.items()}


def _category_grams(product_name: str) -> Decimal | None:
    """报表中心《发帘与贴发产品清单》分类规则的标准克重（label 第 2 行，如「20g」）。"""
    index, label = classify(product_name, "")
    if index == OTHER_CATEGORY_INDEX:
        return None
    lines = label.split("\n")
    return metrics.parse_grams(lines[1]) if len(lines) > 1 else None


def suggest(product_name: str, index: dict[str, tuple[str, Decimal]]) -> tuple[str | None, Decimal | None, str | None]:
    """历史品名 → (型号, 克重, 来源)。

    优先级：当前产品表同名型号 > 产品清单分类规则克重 > 品名里的「50克 / 50g」。
    后两者只给克重，型号留给人工填写，避免规则替业务命名。
    """
    hit = index.get(_model_key(product_name))
    if hit:
        return hit[0], hit[1], "okki_model"
    grams = _category_grams(product_name or "")
    if grams is not None:
        return None, grams, "category_rule"
    match = _NAME_GRAMS.search(product_name or "")
    if match:
        return None, Decimal(match.group(1)), "name_grams"
    return None, None, None


def refresh_mappings(db: Session, today: date | None = None) -> dict:
    """扫描 2025-01 起未命中产品表的品名：新品名写入预填，已有行只刷新统计快照。

    人工确认（confirmed / ignored）的型号与克重永不被覆盖。
    """
    end = today or beijing_today()
    lines = metrics.load_lines(db, HISTORY_START, end)
    index = _model_grams_index(lines)
    stats: dict[str, dict] = {}
    for line in lines:
        if line["confidence"] in (metrics.EXACT, metrics.DERIVED) or not line["product_name"]:
            continue
        key = metrics.name_hash(line["product_name"])
        item = stats.setdefault(key, {"name": line["product_name"], "lines": 0, "quantity": Decimal(0), "last": None})
        item["lines"] += 1
        item["quantity"] += line["quantity"]
        if line["account_date"] and (item["last"] is None or line["account_date"] > item["last"]):
            item["last"] = line["account_date"]
    existing = {row.name_hash: row for row in db.query(ProductSalesNameMapping).all()}
    created = updated = 0
    try:
        for key, item in stats.items():
            row = existing.get(key)
            if row is None:
                model, grams, source = suggest(item["name"], index)
                row = ProductSalesNameMapping(
                    name_hash=key, product_name=item["name"][:512], model=model, unit_grams=grams,
                    status=MAPPING_SUGGESTED, suggestion_source=source, rule_version=RULE_VERSION,
                )
                db.add(row)
                created += 1
            else:
                updated += 1
            row.line_count = item["lines"]
            row.quantity_total = item["quantity"]
            row.last_seen_date = item["last"]
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("product_sales mapping refresh conflict: %s", exc)
        print(f"[product_sales] mapping refresh conflict: {exc}", flush=True)
        raise HTTPException(status.HTTP_409_CONFLICT, "另一个扫描正在写入，请稍后重试") from None
    except Exception as exc:
        db.rollback()
        logger.warning("product_sales mapping refresh failed: %s", exc)
        print(f"[product_sales] mapping refresh failed: {exc}", flush=True)
        raise
    _bump_mapping_epoch()
    pending = db.query(ProductSalesNameMapping).filter(ProductSalesNameMapping.status == MAPPING_SUGGESTED).count()
    return {"created": created, "updated": updated, "pending": pending, "rule_version": RULE_VERSION}


def _serialize(row: ProductSalesNameMapping) -> dict:
    return {
        "id": row.id,
        "product_name": row.product_name,
        "model": row.model,
        "unit_grams": float(row.unit_grams) if row.unit_grams is not None else None,
        "status": row.status,
        "suggestion_source": row.suggestion_source,
        "line_count": row.line_count,
        "quantity_total": float(row.quantity_total or 0),
        "last_seen_date": row.last_seen_date.isoformat() if row.last_seen_date else None,
        "confirmed_by_user_id": row.confirmed_by_user_id,
        "confirmed_at": row.confirmed_at.isoformat(sep=" ", timespec="seconds") if row.confirmed_at else None,
    }


def list_mappings(
    db: Session, status_filter: str | None, keyword: str | None, page: int, page_size: int,
) -> dict:
    query = db.query(ProductSalesNameMapping)
    if status_filter:
        query = query.filter(ProductSalesNameMapping.status == status_filter)
    if keyword:
        escaped = keyword.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        like = f"%{escaped}%"
        query = query.filter(or_(
            ProductSalesNameMapping.product_name.like(like, escape="!"),
            ProductSalesNameMapping.model.like(like, escape="!"),
        ))
    total = query.count()
    rows = (
        query.order_by(
            ProductSalesNameMapping.quantity_total.desc(),
            ProductSalesNameMapping.line_count.desc(),
            ProductSalesNameMapping.id,
        )
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return {"items": [_serialize(row) for row in rows], "total": total, "status_counts": _status_counts(db)}


def _status_counts(db: Session) -> dict[str, int]:
    counts = {key: 0 for key in MAPPING_STATUSES}
    for key, value in db.query(ProductSalesNameMapping.status, func.count()).group_by(ProductSalesNameMapping.status):
        counts[key] = value
    return counts


def _grams(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        grams = Decimal(str(value))
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "克重必须是数字") from None
    if not grams.is_finite():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "克重必须是数字")
    grams = grams.quantize(Decimal("0.001"))
    if grams <= 0 or grams > MAX_GRAMS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"克重需在 0.001~{MAX_GRAMS} 之间")
    return grams


def save_mappings(db: Session, user_id: int, items: list[dict]) -> dict:
    """批量确认或忽略。confirmed 必须同时有型号和克重；ignored 表示非发制品不计重量。"""
    ids = [item["id"] for item in items]
    rows = {row.id: row for row in db.query(ProductSalesNameMapping).filter(ProductSalesNameMapping.id.in_(ids))}
    missing = [item_id for item_id in ids if item_id not in rows]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"映射不存在：{missing[:5]}")
    now = beijing_now()
    for item in items:
        row = rows[item["id"]]
        target = item["status"]
        model = (item.get("model") or "").strip() or None
        grams = _grams(item.get("unit_grams"))
        if target == MAPPING_CONFIRMED and (not model or grams is None):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"「{row.product_name}」确认前需填写型号和克重")
        row.status = target
        if model or target != MAPPING_IGNORED:
            row.model = model  # 标「非发制品」不清掉原型号，恢复时还能找回
        row.unit_grams = grams if target != MAPPING_IGNORED else row.unit_grams
        row.confirmed_by_user_id = user_id if target != MAPPING_SUGGESTED else None
        row.confirmed_at = now if target != MAPPING_SUGGESTED else None
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("product_sales mapping save failed: %s", exc)
        print(f"[product_sales] mapping save failed: {exc}", flush=True)
        raise
    _bump_mapping_epoch()
    return {"saved": len(items)}


def current_models(db: Session) -> list[dict]:
    """当前产品表型号及其最常见克重，供确认页下拉选择（选型号即带出克重）。"""
    schema = get_settings().BUSINESS_DB_NAME
    counts: dict[str, Counter] = defaultdict(Counter)
    for model, unit, count in db.execute(text(
        f"SELECT TRIM(model), unit, COUNT(*) FROM `{schema}`.okki_products "
        "WHERE model IS NOT NULL AND TRIM(model) <> '' GROUP BY TRIM(model), unit"
    )):
        grams = metrics.parse_grams(unit)
        if grams is not None:
            counts[model][grams] += count
    return [
        {"model": model, "unit_grams": float(counter.most_common(1)[0][0])}
        for model, counter in sorted(counts.items())
    ]


_COVERAGE_TTL_SECONDS = 300
_coverage_cache: dict[tuple, tuple[float, dict]] = {}
_mapping_epoch = 0


def _bump_mapping_epoch() -> None:
    """本进程内映射写入后让可信度缓存失效（updated_at 只到秒，不能单独当版本号）。"""
    global _mapping_epoch
    _mapping_epoch += 1


def _mapping_version(db: Session) -> tuple:
    count, latest = db.query(func.count(ProductSalesNameMapping.id), func.max(ProductSalesNameMapping.updated_at)).one()
    return count, latest.isoformat() if latest else None


def coverage(db: Session, date_from: date, date_to: date) -> dict:
    """月度可信度。全量扫描约 5 万行，按「窗口 + 映射版本」缓存 5 分钟（OKKI 无变更通知，允许分钟级滞后）。"""
    key = (date_from, date_to, _mapping_epoch, _mapping_version(db))
    cached = _coverage_cache.get(key)
    if cached and time.monotonic() - cached[0] < _COVERAGE_TTL_SECONDS:
        return cached[1]
    lines = metrics.load_lines(db, date_from, date_to)
    result = {
        "months": metrics.monthly_coverage(lines),
        "credible_share_threshold": float(metrics.CREDIBLE_MONTH_SHARE),
        "computed_at": beijing_now().isoformat(sep=" ", timespec="seconds"),
    }
    _coverage_cache.clear()
    _coverage_cache[key] = (time.monotonic(), result)
    return result
