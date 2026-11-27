"""AI 订阅管理服务：卡片状态、余额估算与核对流水、续费确认、统一单价与全平台汇总。"""

from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.logo_storage import delete_logo_quietly, mime_for_key, read_logo_path, save_logo
from app.ai.models import (
    AiBalanceCheckpoint,
    AiCallLog,
    AiModelPrice,
    AiPreset,
    AiProvider,
    AiProviderBilling,
)
from app.ai.provider_config import public_extra_headers
from app.ai.provider_service import get_provider
from app.core.time import beijing_now, beijing_today

ALLOWED_CURRENCIES = {"CNY", "USD"}
ALLOWED_SERVICE_KINDS = {"official", "relay"}
ALLOWED_BILLING_MODES = {"monthly", "quarterly", "yearly", "pay_as_you_go"}
ALLOWED_CHECKPOINT_KINDS = {"reconcile", "topup"}
ALLOWED_PRICING_MODES = {"token", "per_call", "image_rate_card"}

QUANT_2 = Decimal("0.01")
QUANT_4 = Decimal("0.0001")
QUANT_6 = Decimal("0.000001")


def _mask_api_key(key: Optional[str]) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def _validate_https_url(url: Optional[str], label: str) -> Optional[str]:
    if url is None:
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(f"{label}仅支持 https:// 开头的有效地址")
    return cleaned


def add_billing_cycle(base_date: date, billing_mode: str) -> date:
    """按计费周期顺延一期（安全处理月末日期，如 1/31 -> 2/28）。"""
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(billing_mode, 1)
    total_months = (base_date.year * 12 + (base_date.month - 1)) + months
    year, month_idx = divmod(total_months, 12)
    month = month_idx + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _cycle_days_for(billing: AiProviderBilling) -> int:
    if billing.billing_mode == "yearly":
        return 365
    if billing.billing_mode == "quarterly":
        return 90
    return 30


def _month_start_beijing(today: Optional[date] = None) -> datetime:
    d = today or beijing_today()
    return datetime(d.year, d.month, 1, 0, 0, 0)


def _format_decimal(val: Optional[Decimal], quant: Decimal = QUANT_2) -> Optional[str]:
    if val is None:
        return None
    return str(Decimal(val).quantize(quant, rounding=ROUND_HALF_UP))


def _compute_balance_snapshot(
    db: Session,
    provider_id: int,
    billing: Optional[AiProviderBilling],
    checkpoint: Optional[AiBalanceCheckpoint],
    inflight_count: int,
    today: date,
    *,
    as_of: Optional[datetime] = None,
) -> dict:
    if checkpoint is None:
        return {
            "has_checkpoint": False,
            "status": "unset",
            "estimated_amount": None,
            "currency": billing.price_currency if billing and billing.price_currency else "CNY",
            "base_amount": None,
            "recorded_at": None,
            "checkpoint_kind": None,
            "threshold": _format_decimal(billing.low_balance_threshold, QUANT_4) if billing and billing.low_balance_threshold is not None else None,
            "remaining_pct": None,
            "threshold_pct": None,
            "stale_days": None,
            "is_stale": False,
            "inflight_count": inflight_count,
            "deduct_by_usage": bool(billing.is_balance_deducted_by_usage) if billing else True,
            "currency_mismatch": False,
        }

    deduct = bool(billing.is_balance_deducted_by_usage) if billing else True
    base_amount = Decimal(checkpoint.balance_amount)
    base_currency = checkpoint.balance_currency
    threshold = Decimal(billing.low_balance_threshold) if (billing and billing.low_balance_threshold is not None) else None
    stale_days = max(0, (today - checkpoint.recorded_at.date()).days)

    currency_mismatch = False
    spent_same = Decimal("0")

    if deduct:
        spent_query = (
            db.query(
                AiCallLog.cost_currency,
                func.coalesce(func.sum(AiCallLog.cost_amount), 0),
            )
            .filter(
                AiCallLog.provider_id == provider_id,
                AiCallLog.cost_status == "priced",
                AiCallLog.finished_at.isnot(None),
                AiCallLog.finished_at > checkpoint.recorded_at,
            )
        )
        if as_of is not None:
            spent_query = spent_query.filter(AiCallLog.finished_at <= as_of)
        rows = spent_query.group_by(AiCallLog.cost_currency).all()
        for cur, amt in rows:
            dec_amt = Decimal(str(amt or 0))
            if dec_amt <= 0:
                continue
            if cur == base_currency:
                spent_same += dec_amt
            else:
                currency_mismatch = True

    if currency_mismatch:
        return {
            "has_checkpoint": True,
            "status": "currency_mismatch",
            "estimated_amount": None,
            "currency": base_currency,
            "base_amount": _format_decimal(base_amount, QUANT_4),
            "recorded_at": checkpoint.recorded_at.isoformat(),
            "checkpoint_kind": checkpoint.checkpoint_kind,
            "threshold": _format_decimal(threshold, QUANT_4) if threshold is not None else None,
            "remaining_pct": None,
            "threshold_pct": None,
            "stale_days": stale_days,
            "is_stale": stale_days > 14,
            "inflight_count": inflight_count,
            "deduct_by_usage": deduct,
            "currency_mismatch": True,
        }

    estimated = base_amount - spent_same if deduct else base_amount
    if base_amount > 0:
        rem_pct = max(0, min(100, int((estimated / base_amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))))
        thresh_pct = (
            max(0, min(100, int((threshold / base_amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))))
            if threshold is not None
            else None
        )
    else:
        rem_pct = 0
        thresh_pct = None

    return {
        "has_checkpoint": True,
        "status": "ok",
        "estimated_amount": _format_decimal(estimated, QUANT_4),
        "estimated_decimal": estimated,
        "currency": base_currency,
        "base_amount": _format_decimal(base_amount, QUANT_4),
        "recorded_at": checkpoint.recorded_at.isoformat(),
        "checkpoint_kind": checkpoint.checkpoint_kind,
        "threshold": _format_decimal(threshold, QUANT_4) if threshold is not None else None,
        "remaining_pct": rem_pct,
        "threshold_pct": thresh_pct,
        "stale_days": stale_days,
        "is_stale": stale_days > 14,
        "inflight_count": inflight_count,
        "deduct_by_usage": deduct,
        "currency_mismatch": False,
    }


def _evaluate_flags(
    provider: AiProvider,
    billing: Optional[AiProviderBilling],
    balance_info: dict,
    today: date,
) -> tuple[str, Optional[str], Optional[str], list[str], Optional[dict]]:
    renew_info = None
    if billing and billing.renew_at is not None:
        days_left = (billing.renew_at - today).days
        cycle_days = _cycle_days_for(billing)
        elapsed_pct = 100 if days_left < 0 else max(0, min(100, round(((cycle_days - days_left) / cycle_days) * 100)))
        renew_info = {
            "renew_at": billing.renew_at.isoformat(),
            "days_left": days_left,
            "cycle_days": cycle_days,
            "elapsed_pct": elapsed_pct,
            "renew_confirmed_at": billing.renew_confirmed_at.isoformat() if billing.renew_confirmed_at else None,
        }

    if not provider.is_enabled:
        return "disabled", None, None, [], renew_info

    renew_flag = None
    if renew_info is not None:
        if renew_info["days_left"] < 0:
            renew_flag = "renew_pending"
        elif renew_info["days_left"] <= 7:
            renew_flag = "renew_soon"

    balance_flag = None
    if provider.provider_type != "accio_work" and balance_info.get("status") == "ok":
        est_dec: Decimal = balance_info["estimated_decimal"]
        threshold = Decimal(billing.low_balance_threshold) if (billing and billing.low_balance_threshold is not None) else None
        if est_dec <= 0:
            balance_flag = "balance_empty"
        elif threshold is not None and est_dec < threshold:
            balance_flag = "balance_low"

    # 主状态优先级
    if renew_flag == "renew_pending":
        status = "renew_pending"
    elif balance_flag == "balance_empty":
        status = "balance_empty"
    elif balance_flag == "balance_low":
        status = "balance_low"
    elif renew_flag == "renew_soon":
        status = "renew_soon"
    else:
        status = "healthy"

    secondary: list[str] = []
    if renew_flag and renew_flag != status:
        secondary.append(renew_flag)
    if balance_flag and balance_flag != status:
        secondary.append(balance_flag)

    return status, renew_flag, balance_flag, secondary, renew_info


def _spend_rows_to_list(cur_map: dict[str, Decimal]) -> list[dict]:
    order = {"CNY": 0, "USD": 1}
    return [
        {"currency": cur, "amount": _format_decimal(amt, QUANT_2)}
        for cur, amt in sorted(cur_map.items(), key=lambda kv: (order.get(kv[0], 99), kv[0]))
        if amt is not None
    ]


def list_subscriptions(
    db: Session,
    *,
    status_filter: Optional[str] = None,
    service_kind: Optional[str] = None,
    api_type: Optional[str] = None,
    hide_disabled: bool = False,
    q: Optional[str] = None,
    sort: str = "renew",
) -> dict:
    today = beijing_today()
    month_start = _month_start_beijing(today)

    providers = (
        db.query(AiProvider)
        .filter(AiProvider.deleted_at.is_(None))
        .order_by(AiProvider.id.asc())
        .all()
    )
    provider_ids = [p.id for p in providers]

    # 批量加载 billing、最新 checkpoint、下挂模型、在途调用数、提供商级消费
    billings = (
        db.query(AiProviderBilling)
        .filter(AiProviderBilling.provider_id.in_(provider_ids))
        .all()
        if provider_ids
        else []
    )
    billing_map = {b.provider_id: b for b in billings}

    cp_ids = [b.latest_checkpoint_id for b in billings if b.latest_checkpoint_id is not None]
    cp_rows = (
        db.query(AiBalanceCheckpoint).filter(AiBalanceCheckpoint.id.in_(cp_ids)).all()
        if cp_ids
        else []
    )
    cp_map = {c.id: c for c in cp_rows}

    preset_rows = (
        db.query(AiPreset.provider_id, AiPreset.model)
        .filter(
            AiPreset.deleted_at.is_(None),
            AiPreset.is_enabled.is_(True),
            AiPreset.provider_id.in_(provider_ids),
        )
        .all()
        if provider_ids
        else []
    )
    models_by_provider: dict[int, list[str]] = {}
    for pid, model in preset_rows:
        if model:
            bucket = models_by_provider.setdefault(pid, [])
            if model not in bucket:
                bucket.append(model)

    inflight_rows = (
        db.query(AiCallLog.provider_id, func.count(AiCallLog.id))
        .filter(
            AiCallLog.status == "pending",
            AiCallLog.provider_id.in_(provider_ids),
        )
        .group_by(AiCallLog.provider_id)
        .all()
        if provider_ids
        else []
    )
    inflight_map = {pid: int(cnt) for pid, cnt in inflight_rows}

    # 全平台总消费 SQL 聚合（总账守恒：不过滤已停用或已软删提供商）
    global_month_rows = (
        db.query(AiCallLog.cost_currency, func.coalesce(func.sum(AiCallLog.cost_amount), 0))
        .filter(
            AiCallLog.cost_status == "priced",
            AiCallLog.finished_at.isnot(None),
            AiCallLog.finished_at >= month_start,
        )
        .group_by(AiCallLog.cost_currency)
        .all()
    )
    global_total_rows = (
        db.query(AiCallLog.cost_currency, func.coalesce(func.sum(AiCallLog.cost_amount), 0))
        .filter(AiCallLog.cost_status == "priced")
        .group_by(AiCallLog.cost_currency)
        .all()
    )
    global_status_rows = (
        db.query(AiCallLog.cost_status, func.count(AiCallLog.id))
        .filter(AiCallLog.cost_status.in_(("unpriced", "no_usage", "test")))
        .group_by(AiCallLog.cost_status)
        .all()
    )
    global_status_counts = {st: int(cnt) for st, cnt in global_status_rows}

    # 按提供商的本月/累计/未定价聚合
    prov_month_rows = (
        db.query(
            AiCallLog.provider_id,
            AiCallLog.cost_currency,
            func.coalesce(func.sum(AiCallLog.cost_amount), 0),
        )
        .filter(
            AiCallLog.provider_id.in_(provider_ids),
            AiCallLog.cost_status == "priced",
            AiCallLog.finished_at.isnot(None),
            AiCallLog.finished_at >= month_start,
        )
        .group_by(AiCallLog.provider_id, AiCallLog.cost_currency)
        .all()
        if provider_ids
        else []
    )
    prov_total_rows = (
        db.query(
            AiCallLog.provider_id,
            AiCallLog.cost_currency,
            func.coalesce(func.sum(AiCallLog.cost_amount), 0),
        )
        .filter(
            AiCallLog.provider_id.in_(provider_ids),
            AiCallLog.cost_status == "priced",
        )
        .group_by(AiCallLog.provider_id, AiCallLog.cost_currency)
        .all()
        if provider_ids
        else []
    )
    prov_unpriced_rows = (
        db.query(AiCallLog.provider_id, func.count(AiCallLog.id))
        .filter(
            AiCallLog.provider_id.in_(provider_ids),
            AiCallLog.cost_status.in_(("unpriced", "no_usage")),
        )
        .group_by(AiCallLog.provider_id)
        .all()
        if provider_ids
        else []
    )
    prov_calls_rows = (
        db.query(AiCallLog.provider_id, func.count(AiCallLog.id))
        .filter(
            AiCallLog.provider_id.in_(provider_ids),
            AiCallLog.created_at >= month_start,
        )
        .group_by(AiCallLog.provider_id)
        .all()
        if provider_ids
        else []
    )

    prov_month_map: dict[int, dict[str, Decimal]] = {}
    for pid, cur, amt in prov_month_rows:
        if cur:
            prov_month_map.setdefault(pid, {})[cur] = Decimal(str(amt or 0))
    prov_total_map: dict[int, dict[str, Decimal]] = {}
    for pid, cur, amt in prov_total_rows:
        if cur:
            prov_total_map.setdefault(pid, {})[cur] = Decimal(str(amt or 0))
    prov_unpriced_map = {pid: int(cnt) for pid, cnt in prov_unpriced_rows}
    prov_calls_map = {pid: int(cnt) for pid, cnt in prov_calls_rows}

    all_items: list[dict] = []
    active_count = 0
    renew_alert_count = 0
    balance_alert_count = 0
    disabled_count = 0
    fixed_monthly_map: dict[str, Decimal] = {}

    for p in providers:
        b = billing_map.get(p.id)
        cp = cp_map.get(b.latest_checkpoint_id) if (b and b.latest_checkpoint_id) else None
        bal_info = _compute_balance_snapshot(db, p.id, b, cp, inflight_map.get(p.id, 0), today)
        status, renew_flag, balance_flag, secondary_flags, renew_info = _evaluate_flags(p, b, bal_info, today)
        bal_info.pop("estimated_decimal", None)

        if not p.is_enabled:
            disabled_count += 1
        else:
            if renew_flag != "renew_pending":
                active_count += 1
            if renew_flag in ("renew_pending", "renew_soon"):
                renew_alert_count += 1
            if balance_flag in ("balance_empty", "balance_low"):
                balance_alert_count += 1
            if b and b.price_amount is not None and b.billing_mode in ("monthly", "quarterly", "yearly"):
                cur = b.price_currency or "CNY"
                divisor = Decimal("1") if b.billing_mode == "monthly" else (Decimal("3") if b.billing_mode == "quarterly" else Decimal("12"))
                fixed_monthly_map[cur] = fixed_monthly_map.get(cur, Decimal("0")) + (Decimal(b.price_amount) / divisor)

        effective_kind = "accio_work" if p.provider_type == "accio_work" else (b.service_kind if b else "official")
        month_by_cur = prov_month_map.get(p.id, {})
        total_by_cur = prov_total_map.get(p.id, {})

        all_items.append({
            "id": p.id,
            "name": p.name,
            "provider_type": p.provider_type,
            "service_kind": effective_kind,
            "api_type": getattr(p, "api_type", "openai") or "openai",
            "api_base": p.api_base,
            "api_key": _mask_api_key(p.api_key),
            "extra_headers": public_extra_headers(p.extra_headers, (p.runtime_config or {}).get("auth_header")),
            "runtime_config": p.runtime_config,
            "timeout_sec": p.timeout_sec,
            "remark": p.remark,
            "is_enabled": p.is_enabled,
            "status": status,
            "renew_flag": renew_flag,
            "balance_flag": balance_flag,
            "secondary_flags": secondary_flags,
            "models": models_by_provider.get(p.id, []),
            "billing": {
                "plan_name": b.plan_name if b else None,
                "billing_mode": b.billing_mode if b else "pay_as_you_go",
                "is_balance_deducted_by_usage": bool(b.is_balance_deducted_by_usage) if b else True,
                "price_amount": _format_decimal(b.price_amount, QUANT_2) if b and b.price_amount is not None else None,
                "price_currency": (b.price_currency or "CNY") if b else "CNY",
                "subscribed_at": b.subscribed_at.isoformat() if (b and b.subscribed_at) else None,
                "renew_at": b.renew_at.isoformat() if (b and b.renew_at) else None,
                "console_url": b.console_url if b else None,
                "docs_url": b.docs_url if b else None,
                "has_logo": bool(b and b.logo_storage_key),
                "logo_url": f"/api/ai/providers/{p.id}/logo" if (b and b.logo_storage_key) else None,
                "low_balance_threshold": _format_decimal(b.low_balance_threshold, QUANT_4) if b and b.low_balance_threshold is not None else None,
            },
            "renew": renew_info,
            "balance": bal_info,
            "spend": {
                "month": _spend_rows_to_list(month_by_cur),
                "total": _spend_rows_to_list(total_by_cur),
                "unpriced_count": prov_unpriced_map.get(p.id, 0),
                "month_calls": prov_calls_map.get(p.id, 0),
                "_month_cny": float(month_by_cur.get("CNY", 0)),
                "_month_usd": float(month_by_cur.get("USD", 0)),
            },
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        })

    # 筛选
    filtered = all_items
    if status_filter == "renew_alert":
        filtered = [x for x in filtered if x["renew_flag"] in ("renew_pending", "renew_soon")]
    elif status_filter == "balance_alert":
        filtered = [x for x in filtered if x["balance_flag"] in ("balance_empty", "balance_low")]
    elif status_filter == "disabled":
        filtered = [x for x in filtered if not x["is_enabled"]]
    if hide_disabled:
        filtered = [x for x in filtered if x["is_enabled"]]
    if service_kind:
        filtered = [x for x in filtered if x["service_kind"] == service_kind]
    if api_type:
        filtered = [x for x in filtered if x["provider_type"] == "direct" and x["api_type"] == api_type]
    if q:
        needle = q.strip().lower()
        filtered = [
            x for x in filtered
            if needle in x["name"].lower()
            or needle in x["api_base"].lower()
            or any(needle in m.lower() for m in x["models"])
        ]

    # 排序
    if sort == "balance":
        filtered.sort(key=lambda x: (x["balance"]["remaining_pct"] is None, x["balance"]["remaining_pct"] if x["balance"]["remaining_pct"] is not None else 9999, x["id"]))
    elif sort == "month":
        # 同币种分组（有 CNY 的优先按 CNY 降序，再按 USD 降序），不把不同币种数值直接混排
        filtered.sort(key=lambda x: (
            0 if x["spend"]["_month_cny"] > 0 else (1 if x["spend"]["_month_usd"] > 0 else 2),
            -x["spend"]["_month_cny"],
            -x["spend"]["_month_usd"],
            x["id"],
        ))
    else:
        filtered.sort(key=lambda x: (
            x["renew"] is None,
            x["renew"]["days_left"] if x["renew"] is not None else 10**9,
            x["id"],
        ))

    for x in all_items:
        x["spend"].pop("_month_cny", None)
        x["spend"].pop("_month_usd", None)

    summary = {
        "month_spend": _spend_rows_to_list({cur: Decimal(str(amt or 0)) for cur, amt in global_month_rows if cur}),
        "total_spend": _spend_rows_to_list({cur: Decimal(str(amt or 0)) for cur, amt in global_total_rows if cur}),
        "fixed_subscriptions_monthly": _spend_rows_to_list(fixed_monthly_map),
        "unpriced_count": global_status_counts.get("unpriced", 0) + global_status_counts.get("no_usage", 0),
        "no_usage_count": global_status_counts.get("no_usage", 0),
        "test_count": global_status_counts.get("test", 0),
        "total_providers": len(all_items),
        "active_count": active_count,
        "renew_alert_count": renew_alert_count,
        "balance_alert_count": balance_alert_count,
        "disabled_count": disabled_count,
    }

    return {"summary": summary, "total": len(filtered), "items": filtered}


def _get_or_create_billing(db: Session, provider_id: int, actor_id: Optional[int] = None) -> AiProviderBilling:
    billing = db.query(AiProviderBilling).filter(AiProviderBilling.provider_id == provider_id).first()
    if billing is None:
        billing = AiProviderBilling(
            provider_id=provider_id,
            service_kind="official",
            billing_mode="pay_as_you_go",
            is_balance_deducted_by_usage=True,
            price_currency="CNY",
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(billing)
        db.flush()
    return billing


def upsert_provider_billing(
    db: Session,
    provider_id: int,
    data: dict,
    *,
    actor_id: Optional[int] = None,
) -> AiProviderBilling:
    get_provider(db, provider_id)
    service_kind = data.get("service_kind", "official")
    if service_kind not in ALLOWED_SERVICE_KINDS:
        raise ValueError("接入渠道只能为 official 或 relay")
    billing_mode = data.get("billing_mode", "pay_as_you_go")
    if billing_mode not in ALLOWED_BILLING_MODES:
        raise ValueError("计费方式无效")
    price_currency = (data.get("price_currency") or "CNY").upper()
    if price_currency not in ALLOWED_CURRENCIES:
        raise ValueError("币种仅支持 CNY 或 USD")

    price_amount = data.get("price_amount")
    if price_amount is not None and Decimal(str(price_amount)) < 0:
        raise ValueError("订阅金额不能为负数")
    low_threshold = data.get("low_balance_threshold")
    if low_threshold is not None and Decimal(str(low_threshold)) < 0:
        raise ValueError("低余额预警线不能为负数")

    subscribed_at = data.get("subscribed_at")
    renew_at = data.get("renew_at")
    if subscribed_at and renew_at and renew_at < subscribed_at:
        raise ValueError("下次续费日期不能早于订阅日期")

    console_url = _validate_https_url(data.get("console_url"), "控制台链接")
    docs_url = _validate_https_url(data.get("docs_url"), "API 文档链接")

    billing = _get_or_create_billing(db, provider_id, actor_id=actor_id)
    billing.service_kind = service_kind
    billing.plan_name = (data.get("plan_name") or "").strip() or None
    billing.billing_mode = billing_mode
    if "is_balance_deducted_by_usage" in data and data["is_balance_deducted_by_usage"] is not None:
        billing.is_balance_deducted_by_usage = bool(data["is_balance_deducted_by_usage"])
    billing.price_amount = Decimal(str(price_amount)) if price_amount is not None else None
    billing.price_currency = price_currency
    billing.subscribed_at = subscribed_at
    billing.renew_at = renew_at
    billing.console_url = console_url
    billing.docs_url = docs_url
    billing.low_balance_threshold = Decimal(str(low_threshold)) if low_threshold is not None else None
    billing.updated_at = beijing_now()
    billing.updated_by = actor_id
    db.commit()
    db.refresh(billing)
    return billing


def confirm_provider_renew(
    db: Session,
    provider_id: int,
    *,
    actor_id: Optional[int] = None,
) -> dict:
    get_provider(db, provider_id)
    billing = db.query(AiProviderBilling).filter(AiProviderBilling.provider_id == provider_id).first()
    if billing is None or billing.renew_at is None:
        raise ValueError("该订阅源未登记续费日期，无法确认续费")
    if billing.billing_mode == "pay_as_you_go":
        raise ValueError("按量充值模式不支持按周期顺延续费，请在编辑中手动调整到期日")
    old_renew = billing.renew_at
    next_renew = add_billing_cycle(old_renew, billing.billing_mode)
    now = beijing_now()
    billing.renew_at = next_renew
    billing.renew_confirmed_at = now
    billing.updated_at = now
    billing.updated_by = actor_id
    db.commit()
    return {
        "provider_id": provider_id,
        "previous_renew_at": old_renew.isoformat(),
        "renew_at": next_renew.isoformat(),
        "renew_confirmed_at": now.isoformat(),
    }


def list_balance_checkpoints(db: Session, provider_id: int, *, limit: int = 50) -> list[dict]:
    get_provider(db, provider_id)
    rows = (
        db.query(AiBalanceCheckpoint)
        .filter(AiBalanceCheckpoint.provider_id == provider_id)
        .order_by(AiBalanceCheckpoint.recorded_at.desc(), AiBalanceCheckpoint.id.desc())
        .limit(limit)
        .all()
    )
    items = []
    for row in rows:
        drift = (
            _format_decimal(Decimal(row.balance_amount) - Decimal(row.estimated_before_amount), QUANT_4)
            if row.estimated_before_amount is not None
            else None
        )
        items.append({
            "id": row.id,
            "provider_id": row.provider_id,
            "checkpoint_kind": row.checkpoint_kind,
            "balance_amount": _format_decimal(row.balance_amount, QUANT_4),
            "balance_currency": row.balance_currency,
            "recorded_at": row.recorded_at.isoformat(),
            "estimated_before_amount": _format_decimal(row.estimated_before_amount, QUANT_4),
            "drift_amount": drift,
            "remark": row.remark,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "created_by": row.created_by,
        })
    return items


def create_balance_checkpoint(
    db: Session,
    provider_id: int,
    data: dict,
    *,
    actor_id: Optional[int] = None,
) -> dict:
    get_provider(db, provider_id)
    kind = data.get("checkpoint_kind", "reconcile")
    if kind not in ALLOWED_CHECKPOINT_KINDS:
        raise ValueError("登记类型仅支持 reconcile 或 topup")
    currency = (data.get("balance_currency") or "CNY").upper()
    if currency not in ALLOWED_CURRENCIES:
        raise ValueError("币种仅支持 CNY 或 USD")
    amount = Decimal(str(data["balance_amount"]))
    if amount < 0:
        raise ValueError("余额不能为负数")
    recorded_at = data.get("recorded_at") or beijing_now()
    if recorded_at.tzinfo is not None:
        from app.core.time import to_beijing_naive
        recorded_at = to_beijing_naive(recorded_at)

    billing = _get_or_create_billing(db, provider_id, actor_id=actor_id)
    prev_cp = (
        db.query(AiBalanceCheckpoint).filter(AiBalanceCheckpoint.id == billing.latest_checkpoint_id).first()
        if billing.latest_checkpoint_id
        else None
    )
    est_before = None
    if (
        prev_cp is not None
        and prev_cp.balance_currency == currency
        and recorded_at >= prev_cp.recorded_at
    ):
        snap = _compute_balance_snapshot(
            db, provider_id, billing, prev_cp, 0, beijing_today(), as_of=recorded_at,
        )
        if snap.get("status") == "ok":
            est_before = snap["estimated_decimal"]

    cp = AiBalanceCheckpoint(
        provider_id=provider_id,
        checkpoint_kind=kind,
        balance_amount=amount,
        balance_currency=currency,
        recorded_at=recorded_at,
        estimated_before_amount=est_before,
        remark=(data.get("remark") or "").strip() or None,
        created_at=beijing_now(),
        created_by=actor_id,
    )
    db.add(cp)
    db.flush()

    # 若新截点不早于当前最新截点，则更新指针
    if prev_cp is None or (cp.recorded_at, cp.id) >= (prev_cp.recorded_at, prev_cp.id):
        billing.latest_checkpoint_id = cp.id
    billing.updated_at = beijing_now()
    billing.updated_by = actor_id
    db.commit()
    db.refresh(cp)

    drift = _format_decimal(amount - est_before, QUANT_4) if est_before is not None else None
    return {
        "id": cp.id,
        "provider_id": cp.provider_id,
        "checkpoint_kind": cp.checkpoint_kind,
        "balance_amount": _format_decimal(cp.balance_amount, QUANT_4),
        "balance_currency": cp.balance_currency,
        "recorded_at": cp.recorded_at.isoformat(),
        "estimated_before_amount": _format_decimal(cp.estimated_before_amount, QUANT_4),
        "drift_amount": drift,
        "remark": cp.remark,
    }


def list_model_prices(db: Session, provider_id: int) -> list[dict]:
    get_provider(db, provider_id)
    rows = (
        db.query(AiModelPrice)
        .filter(AiModelPrice.provider_id == provider_id)
        .order_by(AiModelPrice.model.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "provider_id": r.provider_id,
            "model": r.model,
            "pricing_mode": r.pricing_mode,
            "input_per_million": _format_decimal(r.input_per_million, QUANT_6),
            "output_per_million": _format_decimal(r.output_per_million, QUANT_6),
            "per_call_amount": _format_decimal(r.per_call_amount, QUANT_6),
            "currency": r.currency,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def replace_model_prices(
    db: Session,
    provider_id: int,
    items: list[dict],
    *,
    actor_id: Optional[int] = None,
) -> list[dict]:
    get_provider(db, provider_id)
    seen: set[str] = set()
    normalized: list[dict] = []

    for item in items:
        model = (item.get("model") or "").strip()
        if not model or len(model) > 128:
            raise ValueError("模型名称不能为空且不超过 128 字")
        if model in seen:
            raise ValueError(f"模型 '{model}' 重复配置")
        seen.add(model)

        mode = item.get("pricing_mode", "token")
        if mode not in ALLOWED_PRICING_MODES:
            raise ValueError(f"模型 '{model}' 计价模式无效")
        currency = "USD" if mode == "image_rate_card" else (item.get("currency") or "CNY").upper()
        if currency not in ALLOWED_CURRENCIES:
            raise ValueError(f"模型 '{model}' 币种仅支持 CNY 或 USD")

        inp = out = per_call = None
        if mode == "token":
            if item.get("input_per_million") is None or item.get("output_per_million") is None:
                raise ValueError(f"模型 '{model}' 需填写每百万输入与输出单价")
            inp = Decimal(str(item["input_per_million"]))
            out = Decimal(str(item["output_per_million"]))
            if inp < 0 or out < 0 or inp > Decimal("1000000") or out > Decimal("1000000"):
                raise ValueError(f"模型 '{model}' 单价须在 0–1000000 之间")
        elif mode == "per_call":
            if item.get("per_call_amount") is None:
                raise ValueError(f"模型 '{model}' 按次计费需填写单次费用")
            per_call = Decimal(str(item["per_call_amount"]))
            if per_call < 0 or per_call > Decimal("1000000"):
                raise ValueError(f"模型 '{model}' 单次费用须在 0–1000000 之间")

        normalized.append({
            "model": model,
            "pricing_mode": mode,
            "input_per_million": inp,
            "output_per_million": out,
            "per_call_amount": per_call,
            "currency": currency,
        })

    existing = {
        r.model: r
        for r in db.query(AiModelPrice).filter(AiModelPrice.provider_id == provider_id).all()
    }
    now = beijing_now()

    for old_model, old_row in existing.items():
        if old_model not in seen:
            db.delete(old_row)

    for entry in normalized:
        row = existing.get(entry["model"])
        if row is None:
            row = AiModelPrice(
                provider_id=provider_id,
                model=entry["model"],
                created_at=now,
                created_by=actor_id,
            )
            db.add(row)
        row.pricing_mode = entry["pricing_mode"]
        row.input_per_million = entry["input_per_million"]
        row.output_per_million = entry["output_per_million"]
        row.per_call_amount = entry["per_call_amount"]
        row.currency = entry["currency"]
        row.updated_at = now
        row.updated_by = actor_id

    db.commit()
    return list_model_prices(db, provider_id)


def upload_provider_logo(
    db: Session,
    provider_id: int,
    content: bytes,
    *,
    actor_id: Optional[int] = None,
) -> dict:
    get_provider(db, provider_id)
    new_key, mime = save_logo(provider_id, content)
    billing = _get_or_create_billing(db, provider_id, actor_id=actor_id)
    old_key = billing.logo_storage_key
    billing.logo_storage_key = new_key
    billing.updated_at = beijing_now()
    billing.updated_by = actor_id
    try:
        db.commit()
    except Exception:
        db.rollback()
        delete_logo_quietly(new_key)
        raise
    if old_key and old_key != new_key:
        delete_logo_quietly(old_key)
    return {
        "provider_id": provider_id,
        "logo_storage_key": new_key,
        "content_type": mime,
        "logo_url": f"/api/ai/providers/{provider_id}/logo",
    }


def get_provider_logo_file(db: Session, provider_id: int) -> tuple[bytes, str, str]:
    get_provider(db, provider_id)
    billing = db.query(AiProviderBilling).filter(AiProviderBilling.provider_id == provider_id).first()
    if billing is None or not billing.logo_storage_key:
        raise FileNotFoundError("该提供商未上传 LOGO")
    path = read_logo_path(billing.logo_storage_key)
    if not path.is_file():
        raise FileNotFoundError("LOGO 文件不存在")
    return path.read_bytes(), mime_for_key(billing.logo_storage_key), billing.logo_storage_key
