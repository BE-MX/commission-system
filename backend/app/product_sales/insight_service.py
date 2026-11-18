"""产品风向标「解读这款」：结构化证据 → AI 解读（失败降级为规则文本），结果存表 24 小时复用。

宪法 7：统一走 ``app.ai.service.chat``；维度与款的取值在运行时注入 user message，不写死在 prompt。
数字只来自证据；不可比窗口禁止下趋势结论（system prompt + 证据里的 comparable 标记双重约束）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.product_sales.insight_models import ProductSalesAiInsight
from app.product_sales.metrics import CREDIBLE_MONTH_SHARE
from app.product_sales.radar_service import ShareScope, get_item_detail

logger = logging.getLogger("product_sales")

PRESET_NAME = "product_sales_insight"
AI_TIMEOUT_SECONDS = 30
REUSE_HOURS = 24
EXPIRED_KEEP_DAYS = 7  # 过期行保留一周供审计，之后在下次写入时顺手清理


def _cache_key(share: ShareScope, dimension: str, key: str, window_days: int, as_of: str, version: tuple) -> str:
    raw = json.dumps([share.key, dimension, key, window_days, as_of, list(version)], ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _kg(value) -> str:
    return f"{float(value or 0):,.1f} kg"


def _rules_text(evidence: dict) -> str:
    summary = evidence["detail"].get("summary") or {}
    parts = [f"{evidence['detail']['dimension_label']}「{evidence['detail']['key']}」近 {evidence['detail']['window']['days']} 天"
             f" {_kg(summary.get('kg'))}，上期 {_kg(summary.get('prev_kg'))}。"]
    if not evidence["comparable"]:
        parts.append("对比期内有估算月份，变化只作参考，不下趋势结论。")
    models = evidence["detail"].get("top_models") or []
    if models:
        parts.append("主要型号：" + "、".join(f"{m['name']} {_kg(m['kg'])}" for m in models[:3]) + "。")
    return "".join(parts)


def explain(db: Session, share: ShareScope, dimension: str, key: str, window_days: int,
            radar_version: tuple, persistent_version: tuple, caller_user_id: int | None,
            refresh: bool = False) -> dict:
    """``persistent_version`` 只含库里可见的映射版本，跨进程一致，用于存表复用键。

    规则降级结果不落表（模型恢复后应能马上拿到 AI 解读）；``refresh`` 绕过复用重新生成。
    """
    detail = get_item_detail(db, share, dimension, key, window_days, radar_version)
    as_of = detail["window"]["current"][1]
    cache_key = _cache_key(share, dimension, key, window_days, as_of, persistent_version)
    now = beijing_now()
    cached = db.query(ProductSalesAiInsight).filter(ProductSalesAiInsight.cache_key == cache_key).one_or_none()
    if cached and cached.expires_at > now and not refresh:
        return _serialize(cached, reused=True)

    comparable = bool(detail["credibility"]["current"]["credible"] and detail["credibility"]["previous"]["credible"])
    evidence = {
        "comparable": comparable,
        "credible_share_threshold": float(CREDIBLE_MONTH_SHARE),
        "dimension_values": {"dimension": detail["dimension_label"], "key": key},
        "detail": detail,
    }
    db.commit()  # 结束本次读取的事务；chat() 自己会写调用日志并在等待模型期间重新持有连接（facade 现状）
    content, source = _call_ai(db, evidence, caller_user_id)
    if source != "ai":
        return {"content": content, "source": source, "reused": False, "comparable": comparable,
                "created_at": now.isoformat(sep=" ", timespec="seconds"), "expires_at": None}
    try:
        db.query(ProductSalesAiInsight).filter(
            ProductSalesAiInsight.expires_at < now - timedelta(days=EXPIRED_KEEP_DAYS),
        ).delete(synchronize_session=False)
        row = db.query(ProductSalesAiInsight).filter(ProductSalesAiInsight.cache_key == cache_key).one_or_none()
        if row is None:
            row = ProductSalesAiInsight(cache_key=cache_key)
            db.add(row)
        row.scope_key, row.dimension, row.item_key, row.window_days = share.key, dimension, key[:512], window_days
        row.as_of_date, row.content, row.source, row.evidence = date.fromisoformat(as_of), content, source, evidence
        row.created_by_user_id, row.created_at = caller_user_id, now
        row.expires_at = now + timedelta(hours=REUSE_HOURS)
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.query(ProductSalesAiInsight).filter(ProductSalesAiInsight.cache_key == cache_key).one_or_none()
        if winner:
            return _serialize(winner, reused=True)
        raise
    except Exception as exc:
        db.rollback()
        logger.warning("product_sales insight save failed: %s", exc)
        print(f"[product_sales] insight save failed: {exc}", flush=True)
        raise
    return _serialize(row, reused=False)


def _call_ai(db: Session, evidence: dict, caller_user_id: int | None) -> tuple[str, str]:
    try:
        from app.ai.service import chat

        result = chat(
            db=db,
            preset_name=PRESET_NAME,
            messages=[{
                "role": "user",
                "content": (
                    "以下 JSON 是系统实时计算的单款销量证据（重量 kg）。本次分析的维度与取值见 dimension_values，"
                    "月度数据里 credible=false 的月份是估算月。comparable=false 时只能描述现状，不得下涨跌趋势结论。\n"
                    + json.dumps(evidence, ensure_ascii=False, default=str)
                ),
            }],
            caller_module="product_sales",
            caller_user_id=caller_user_id,
            timeout_sec=AI_TIMEOUT_SECONDS,
            enforce_total_timeout=True,
        )
        content = (result.get("content") or "").strip()
        if content:
            return content, "ai"
    except Exception as exc:
        logger.warning("product_sales AI insight failed: %s", exc)
        print(f"[product_sales] AI insight failed: {exc}", flush=True)
    return _rules_text(evidence), "rules"


def _serialize(row: ProductSalesAiInsight, reused: bool) -> dict:
    return {
        "content": row.content,
        "source": row.source,
        "reused": reused,
        "comparable": bool((row.evidence or {}).get("comparable")),
        "created_at": row.created_at.isoformat(sep=" ", timespec="seconds"),
        "expires_at": row.expires_at.isoformat(sep=" ", timespec="seconds") if row.expires_at else None,
    }
