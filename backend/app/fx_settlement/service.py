"""Recompute constraints server-side, then let AI explain one feasible candidate."""

import json
import logging
import threading
import time

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.ai.service import chat
from app.core.time import beijing_now
from app.fx_settlement.ai_evidence import build_choices, render_decision
from app.fx_settlement.engine import calculate_plan
from app.fx_settlement.market_service import get_market
from app.fx_settlement.schemas import AiDecision, SettlementInput

logger = logging.getLogger(__name__)
PRESET_NAME = "fx_settlement_advisor"
SYSTEM_PROMPT = """你是企业美元结汇决策分析助手。你只解释已计算的现金流、资金约束、压力情景和带时间戳的市场证据。
用户消息包含 allowed_strategy_ids、不可更改的 candidates、reason_choices 和 watchpoint_choices。
只能选择一个候选方案，再选择有助于解释该选择的理由 ID 和需要重新测算的条件 ID。
先保护即时人民币需求、美元付款预留和压力情景预算，再结合日度趋势解释是否偏向提前结汇。
银行公开参考价不是可执行成交价；历史日度报价不是实时行情。必须尊重 usable、as_of 与所有 warnings。
历史涨跌不等于预测概率，不能声称保证收益最大、必涨必跌、已执行交易或知道未提供的实时新闻。
没有新闻数据就不能引用宏观事件；无有效趋势时明确只按资金约束分析。
只返回 JSON，字段为 strategy_id、reason_ids（1至5个不重复理由ID）、watchpoint_ids（1至5个不重复条件ID）。
只允许用户消息给出的ID，不输出任何自由文字、HTML、分配金额、日期或新字段。系统会根据ID生成有证据支持的解释。
"""
_guard = threading.Lock()
_active: set[str] = set()
_last_call: dict[str, float] = {}


def build_plan(payload: SettlementInput) -> dict:
    return calculate_plan(payload, get_market(), beijing_now())


def generate_advice(db: Session, payload: SettlementInput, user_id: str) -> dict:
    with _guard:
        tick = time.monotonic()
        # Rate limiting is per process; it prevents repeated clicks and concurrent calls.
        for key in list(_last_call):
            if tick-_last_call[key] > 300:
                del _last_call[key]
        if user_id in _active or tick-_last_call.get(user_id, -1000) < 30:
            raise HTTPException(status_code=429, detail="AI 正在分析或刚刚完成，请稍候再试")
        _active.add(user_id)
        _last_call[user_id] = tick
    try:
        result = build_plan(payload)
        if result["cash_shortfall_cny"] > 0 or result["available_usd"] == 0:
            result["ai_status"] = "not_applicable"
            return result
        market = result["market"]
        reasons, watches = build_choices(result)
        evidence = {
            # The shared Anthropic adapter omits system-role message entries.
            # Repeat the domain contract here so both supported protocols retain it.
            "analysis_contract": SYSTEM_PROMPT,
            "generated_at": result["generated_at"], "inputs": result["input"],
            "rate": result["rate"], "rate_source": result["rate_source"], "rate_at": result["rate_at"],
            "trend": market.get("trend"), "market_checked_at": market["checked_at"],
            "intraday": market.get("intraday"), "reference_quote": market.get("quote"),
            "allowed_strategy_ids": [candidate["id"] for candidate in result["candidates"]],
            "candidates": result["candidates"], "warnings": result["warnings"],
            "reason_choices": reasons, "watchpoint_choices": watches,
            "assumptions": result["assumptions"],
        }
        try:
            response = chat(
                db, PRESET_NAME,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}],
                caller_module="fx_settlement", caller_user_id=int(user_id),
                snapshot_mode="metadata", timeout_sec=75, enforce_total_timeout=True,
            )
            text = (response.get("content") or "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            decision = AiDecision.model_validate(json.loads(text))
            explanation = render_decision(result, decision, reasons, watches)
            result.update({
                "selected_id": decision.strategy_id, "selection_source": "ai",
                "ai": explanation, "ai_status": "success",
                "ai_completed_at": beijing_now().isoformat(),
            })
        except Exception as exc:
            db.rollback()
            logger.warning("FX AI advice unavailable: %s", type(exc).__name__)
            print(f"[FX] AI advice unavailable: {type(exc).__name__}", flush=True)
            result.update({"ai_status": "unavailable", "ai_error": "AI 未能生成有效分析，当前显示规则测算。可稍后重试；若持续失败，请管理员检查结汇 AI 预设。"})
        return result
    finally:
        with _guard:
            _active.discard(user_id)
