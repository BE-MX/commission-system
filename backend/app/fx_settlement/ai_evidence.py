"""AI selects supported evidence IDs; financial instructions stay deterministic."""

from app.fx_settlement.schemas import AiDecision


def build_choices(plan: dict) -> tuple[dict, dict]:
    inputs, market = plan["input"], plan["market"]
    reasons = {
        "cash_need": f"现在需要补足 {float(inputs['immediate_cny_need']):,.2f} 元人民币；所有候选方案都先满足这项需求。",
        "reserved": f"必须保留的 {plan['reserved_usd']:,.2f} 美元已排除在结汇方案之外。",
        "loss_budget": f"按美元下跌 {inputs['stress_drop_pct']}% 的情景，可等待本金上限为 {plan['maximum_later_usd']:,.2f} 美元；更大跌幅仍可能突破预算。",
        "deadline": f"距离最晚结汇日 {inputs['settle_by']} 还有 {plan['horizon_days']} 天，分批计划必须在此之前完成。",
        "quote": f"本次按 {plan['rate']:.4f} 测算，来源为{plan['rate_source']}；执行前仍要核对报价。",
        "carry": f"比较已纳入美元年化利率 {inputs['usd_interest_pct']}%、人民币年化利率 {inputs['cny_interest_pct']}% 和额外费用 {inputs['fee_bps']} 基点。",
    }
    trend = market.get("trend")
    if trend and trend.get("usable"):
        for days in (5, 20):
            change = trend.get(f"change_{days}d_pct")
            if change is not None:
                reasons[f"trend_{days}d"] = f"截至 {trend['as_of']}，最近 {days} 个观测日美元兑人民币变动 {change:+.3f}%；这只是历史变化，不代表未来方向。"
    else:
        reasons["no_trend"] = "历史趋势缺失或过期，本次只按资金条件和压力情景判断，无法确认最新市场趋势。"
    intraday, quote = market.get("intraday"), market.get("quote")
    if intraday and quote and quote.get("usable"):
        reasons["intraday"] = f"中国银行 {intraday['from_at']} 至 {intraday['to_at']} 的两次参考报价变动 {intraday['change_pct']:+.4f}%；短时变化不构成收益预测。"
    watches = {
        "quote_change": "银行实际报价变化或超过有效时间时，重新询价并测算。",
        "cash_change": "人民币付款提前、金额增加，或美元付款预留变化时，优先更新资金条件。",
        "stress_change": "当你认为可能跌得更多时，提高压力跌幅重新计算；损失预算并非保证上限。",
        "deadline": f"到 {inputs['settle_by']} 前完成计划；银行休市、到账时间或期限变更时提前调整。",
        "trend_refresh": "新的日度数据发布或盘中方向明显变化时，重新分析，不机械照搬本次结论。",
    }
    return reasons, watches


def render_decision(plan: dict, decision: AiDecision, reasons: dict, watches: dict) -> dict:
    candidate = next((item for item in plan["candidates"] if item["id"] == decision.strategy_id), None)
    if candidate is None or any(key not in reasons for key in decision.reason_ids) or any(key not in watches for key in decision.watchpoint_ids):
        raise ValueError("AI decision used unsupported strategy or evidence")
    if len(set(decision.reason_ids)) != len(decision.reason_ids) or len(set(decision.watchpoint_ids)) != len(decision.watchpoint_ids):
        raise ValueError("AI decision repeated evidence")
    return {
        "strategy_id": decision.strategy_id,
        "summary": f"在本次资金条件与行情证据下，AI 选择「{candidate['label']}」：现在结汇 {candidate['now_usd']:,.2f} 美元，余下 {candidate['later_usd']:,.2f} 美元按计划处理。该判断不保证收益最高。",
        "reasons": [reasons[key] for key in decision.reason_ids],
        "watchpoints": [watches[key] for key in decision.watchpoint_ids],
    }
