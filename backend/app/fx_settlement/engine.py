"""Auditable cash-flow and stress-budget constraints; no fitted return forecast."""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN

from app.fx_settlement.schemas import SettlementInput

D = Decimal
CENT = D("0.01")


def amount(value: Decimal) -> float:
    return float(value.quantize(CENT))


def _ceil(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_CEILING)


def _floor(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_DOWN)


def select_rate(payload: SettlementInput, market: dict, now: datetime) -> tuple[Decimal, str, str]:
    if payload.bank_rate is not None:
        age = (now - payload.bank_quote_at).total_seconds()
        if not -300 <= age <= 900:
            raise ValueError("手动银行报价已超过 15 分钟或来自未来，请重新询价并更新报价时间")
        return payload.bank_rate, "用户填写的银行报价", payload.bank_quote_at.isoformat()
    quote = market.get("quote")
    if not quote or not quote.get("usable"):
        raise ValueError("暂无新鲜参考报价，请填写银行当前可成交报价及时间后计算")
    age = (now - datetime.fromisoformat(quote["as_of"])).total_seconds()
    if not -300 <= age <= 1800:
        raise ValueError("银行参考报价已过期，请刷新或填写当前银行报价")
    return D(str(quote["rate"])), "中国银行现汇买入参考价（非成交承诺）", quote["as_of"]


def _schedule(wait_usd: Decimal, days: int, today) -> list[dict]:
    if wait_usd <= 0 or days <= 0:
        return []
    dates = sorted({today + timedelta(days=max(1, days * index // 3)) for index in (1, 2, 3)})
    chunk = _floor(wait_usd / len(dates))
    return [
        {"date": day.isoformat(), "usd": amount(chunk if index < len(dates)-1 else wait_usd-chunk*(len(dates)-1))}
        for index, day in enumerate(dates)
        if chunk > 0 or index == len(dates)-1
    ]


def calculate_plan(payload: SettlementInput, market: dict, now: datetime) -> dict:
    days = (payload.settle_by - now.date()).days
    if not 0 <= days <= 365:
        raise ValueError("最晚结汇日期须为北京时间今天至未来 365 天以内")
    rate, rate_source, rate_at = select_rate(payload, market, now)
    effective = rate * (1 - payload.fee_bps / D("10000"))
    available = payload.usd_balance - payload.reserved_usd
    need = payload.immediate_cny_need
    cash_required = min(available, _ceil(need / effective))
    shortfall = max(D("0"), need - available * effective)
    years = D(days) / D("365")
    usd_growth = 1 + payload.usd_interest_pct / 100 * years
    cny_interest = payload.cny_interest_pct / 100 * years
    # Immediate cash needed for spending earns no interest. All scenarios share
    # that consumption; the available surplus uses simple actual/365 carry.
    def immediate_value(usd):
        principal = usd * effective
        return principal + max(D("0"), principal - need) * cny_interest

    baseline = immediate_value(available)
    drop = payload.stress_drop_pct / 100
    loss_per_usd = max(D("0"), effective * (1+cny_interest) - effective * (1-drop) * usd_growth)
    wait_limit = min(available, _floor(payload.max_loss_cny / loss_per_usd)) if loss_per_usd > 0 else available
    minimum_now = available if days == 0 or shortfall > 0 or payload.max_loss_cny == 0 else max(cash_required, available-wait_limit)
    allocations = [
        ("immediate", "立即结汇", available),
        ("balanced", "均衡分批", min(available, _ceil((minimum_now+available)/2))),
        ("flexible", "保留机动", minimum_now),
    ]
    candidates = []
    for code, label, now_usd in allocations:
        waiting = available-now_usd
        scenarios = []
        for title, move in (("美元下跌", -drop), ("汇率不变", D("0")), ("美元上涨", drop)):
            future_rate = rate*(1+move)
            total = immediate_value(now_usd) + waiting*usd_growth*future_rate*(1-payload.fee_bps/10000)
            scenarios.append({
                "label": title, "change_pct": float(move*100), "rate": float(future_rate.quantize(D("0.0001"))),
                "total_cny": amount(total), "vs_immediate_cny": amount(total-baseline),
            })
        candidates.append({
            "id": code, "label": label,
            "now_usd": amount(now_usd), "later_usd": amount(waiting),
            "now_cny": amount(now_usd*effective),
            "stress_loss_cny": amount(max(D("0"), waiting*loss_per_usd)),
            "schedule": _schedule(waiting, days, now.date()), "scenarios": scenarios,
        })
    warnings = list(market.get("warnings", []))
    if shortfall > 0:
        warnings.append(f"可结汇资金不足，仍有 {amount(shortfall):,.2f} 元人民币缺口；预留美元未被挪用。")
    if available == 0:
        warnings.append("美元已全部预留，没有可用于本次结汇的余额。")
    if not (market.get("trend") or {}).get("usable"):
        warnings.append("日度趋势缺失或已超过 10 天，不能据此判断当前趋势。")
    if payload.bank_rate is None:
        warnings.append("当前测算使用银行公开参考价；执行前须核对你的实际可成交价。")
    warnings.append("压力跌幅是情景假设，行情跌幅更大时，实际损失可能超过所填预算。")
    return {
        "generated_at": now.isoformat(), "input": payload.model_dump(mode="json"),
        "market": market, "rate": float(rate), "effective_rate": float(effective),
        "rate_source": rate_source, "rate_at": rate_at,
        "available_usd": amount(available), "reserved_usd": amount(payload.reserved_usd),
        "cash_shortfall_cny": amount(shortfall), "minimum_now_usd": amount(minimum_now),
        "maximum_later_usd": amount(available-minimum_now), "horizon_days": days,
        "candidates": candidates,
        "selected_id": "immediate" if minimum_now == available else "balanced",
        "selection_source": "rules", "ai": None, "warnings": warnings,
        "assumptions": [
            "人民币需求为现在必须覆盖的净缺口；预留美元只保留本金，不参与结汇比较。",
            "利息按单利、实际天数/365估算；已用于人民币支出的部分不计利息。",
            "待结汇部分统一按最晚日价格测算，分批日期只是执行提醒，并非各日价格预测。",
            "对比基准为全部可结汇美元现在结汇后的同期限人民币价值，包含相同费用与利息口径。",
            "计划日期为日历日期，银行休市或转账到账时间可能要求提前执行。",
            "没有足够证据支持固定星期的结汇优势；历史趋势不代表未来涨跌概率。",
        ],
    }
