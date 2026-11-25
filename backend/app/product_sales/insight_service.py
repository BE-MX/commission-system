"""产品风向标「大类 AI 分析」：B1 / B3 / 50%幅度 各维度排行与涨跌证据 → AI 汇总（失败降级为规则文本），
结果存表 24 小时复用。

- 手动触发；公司口径（不含个人份额），所以同一大类、窗口、日期的结果所有人共用。
- 宪法 7：统一走 ``app.ai.service.chat``；大类、维度与取值在运行时注入 user message，不写死在 prompt。
- 数字只来自证据；不可比窗口或估算月禁止下涨跌趋势结论（system prompt + 证据里的标记双重约束）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.product_sales.insight_models import ProductSalesAiInsight
from app.product_sales.radar_service import COMPANY_SCOPE, get_grade_evidence

logger = logging.getLogger("product_sales")

PRESET_NAME = "product_sales_grade_insight"
INSIGHT_DIMENSION = "grade"
AI_TIMEOUT_SECONDS = 45
REUSE_HOURS = 24
EXPIRED_KEEP_DAYS = 7  # 过期行保留一周供审计，之后在下次写入时顺手清理
REFRESH_COOLDOWN_MINUTES = 5  # 「重新分析」冷却期：期内直接返回刚生成的结果，避免反复打模型
_key_locks: dict[str, threading.Lock] = {}
_key_locks_guard = threading.Lock()


def _lock_for(cache_key: str) -> threading.Lock:
    """同一大类+窗口+日期在本进程内 single-flight：两人同时点只调用一次模型。"""
    with _key_locks_guard:
        if len(_key_locks) > 256:  # 只回收没人持有的锁，避免正在生成的请求失去互斥
            for key in [key for key, lock in _key_locks.items() if not lock.locked()]:
                _key_locks.pop(key, None)
        return _key_locks.setdefault(cache_key, threading.Lock())


def _cache_key(grade: str, window_days: int, as_of: str, version: tuple) -> str:
    raw = json.dumps([COMPANY_SCOPE.key, INSIGHT_DIMENSION, grade, window_days, as_of, list(version)],
                     ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _kg(value) -> str:
    return f"{float(value or 0):,.1f} kg"


def _rules_text(evidence: dict) -> str:
    summary = evidence["summary"]
    lines = [f"{evidence['grade_label']} 近 {evidence['window']['days']} 天 {_kg(summary['kg'])}，"
             f"上期 {_kg(summary['prev_kg'])}。"]
    if not evidence["comparable"]:
        lines.append("对比期内有估算数据，涨跌只作参考，不下趋势结论。")
    for block in evidence["dimensions"][:3]:
        top = "、".join(f"{row['key']} {_kg(row['kg'])}" for row in block["top"][:3])
        if top:
            lines.append(f"{block['dimension']}前三：{top}。")
    return "\n".join(lines)


def explain_grade(db: Session, grade: str, window_days: int, radar_version: tuple, persistent_version: tuple,
                  caller_user_id: int | None, refresh: bool = False) -> dict:
    """``persistent_version`` 只含库里可见的映射版本，跨进程一致，用于存表复用键。

    规则降级结果不落表（模型恢复后应能马上拿到 AI 分析）；``refresh`` 绕过复用重新生成。
    """
    evidence = get_grade_evidence(db, grade, window_days, radar_version)
    as_of = evidence["window"]["current"][1]
    cache_key = _cache_key(grade, window_days, as_of, persistent_version)
    with _lock_for(cache_key):
        return _explain_locked(db, evidence, grade, window_days, as_of, cache_key, caller_user_id, refresh)


def _explain_locked(db: Session, evidence: dict, grade: str, window_days: int, as_of: str, cache_key: str,
                    caller_user_id: int | None, refresh: bool) -> dict:
    now = beijing_now()
    # 先结束进锁前的读事务：MySQL 可重复读下旧快照看不到先拿到锁的人刚提交的结果
    db.commit()
    cached = db.query(ProductSalesAiInsight).filter(ProductSalesAiInsight.cache_key == cache_key).one_or_none()
    valid = cached if cached and cached.expires_at > now else None
    if valid:
        cooldown_until = valid.created_at + timedelta(minutes=REFRESH_COOLDOWN_MINUTES)
        if not refresh:
            return _serialize(valid, reused=True, now=now)
        if cooldown_until > now:
            return _serialize(valid, reused=True, now=now)

    db.commit()  # 结束本次读取的事务；chat() 自己会写调用日志并在等待模型期间重新持有连接（facade 现状）
    content, source = _call_ai(db, evidence, caller_user_id)
    if source != "ai" and valid:
        # 重新分析失败时保留上一份仍有效的 AI 分析，不用信息更少的规则摘要替换
        return {**_serialize(valid, reused=True, now=now), "refresh_failed": True}
    if source != "ai":
        return {"content": content, "source": source, "reused": False, "comparable": evidence["comparable"],
                "created_at": now.isoformat(sep=" ", timespec="seconds"), "expires_at": None}
    try:
        db.query(ProductSalesAiInsight).filter(
            ProductSalesAiInsight.expires_at < now - timedelta(days=EXPIRED_KEEP_DAYS),
        ).delete(synchronize_session=False)
        row = db.query(ProductSalesAiInsight).filter(ProductSalesAiInsight.cache_key == cache_key).one_or_none()
        if row is None:
            row = ProductSalesAiInsight(cache_key=cache_key)
            db.add(row)
        row.scope_key, row.dimension, row.item_key, row.window_days = COMPANY_SCOPE.key, INSIGHT_DIMENSION, grade, window_days
        row.as_of_date, row.content, row.source, row.evidence = date.fromisoformat(as_of), content, source, evidence
        row.created_by_user_id, row.created_at = caller_user_id, now
        row.expires_at = now + timedelta(hours=REUSE_HOURS)
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.query(ProductSalesAiInsight).filter(ProductSalesAiInsight.cache_key == cache_key).one_or_none()
        if winner:
            return _serialize(winner, reused=True, now=now)
        raise
    except Exception as exc:
        db.rollback()
        logger.warning("product_sales grade insight save failed: %s", exc)
        print(f"[product_sales] grade insight save failed: {exc}", flush=True)
        raise
    return _serialize(row, reused=False, now=now)


def _call_ai(db: Session, evidence: dict, caller_user_id: int | None) -> tuple[str, str]:
    try:
        from app.ai.service import chat

        result = chat(
            db=db,
            preset_name=PRESET_NAME,
            messages=[{
                "role": "user",
                "content": (
                    f"本次分析的大类是「{evidence['grade_label']}」，维度有："
                    + "、".join(block["dimension"] for block in evidence["dimensions"])
                    + "。以下 JSON 是系统实时计算的该大类销量证据（重量 kg，件数为 quantity），"
                    "本期与上期是紧邻的两个同长窗口（本期含截止日当天）。monthly 里 credible=false 的月份是估算月，"
                    "partial=true 的月份只有 days_covered 天数据，不得和完整月比较，也不参与趋势判断。"
                    "comparable=false 时不得下涨跌趋势结论。\n"
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
        logger.warning("product_sales grade AI insight failed: %s", exc)
        print(f"[product_sales] grade AI insight failed: {exc}", flush=True)
    return _rules_text(evidence), "rules"


def latest_grade_insight(db: Session, grade: str, window_days: int, as_of: str, persistent_version: tuple) -> dict | None:
    """页面打开时直接展示 24 小时内已生成的分析，不触发模型。"""
    now = beijing_now()
    row = db.query(ProductSalesAiInsight).filter(
        ProductSalesAiInsight.cache_key == _cache_key(grade, window_days, as_of, persistent_version),
    ).one_or_none()
    if row is None or row.expires_at <= now:
        return None
    return _serialize(row, reused=True, now=now)


def _serialize(row: ProductSalesAiInsight, reused: bool, now=None) -> dict:
    cooldown_until = None
    if row.created_at is not None and now is not None:
        until = row.created_at + timedelta(minutes=REFRESH_COOLDOWN_MINUTES)
        if until > now:
            cooldown_until = until.isoformat(sep=" ", timespec="seconds")
    return {
        "summary_kg": ((row.evidence or {}).get("summary") or {}).get("kg"),
        "content": row.content,
        "source": row.source,
        "reused": reused,
        "comparable": bool((row.evidence or {}).get("comparable")),
        "created_at": row.created_at.isoformat(sep=" ", timespec="seconds"),
        "expires_at": row.expires_at.isoformat(sep=" ", timespec="seconds") if row.expires_at else None,
        "cooldown_until": cooldown_until,
    }
