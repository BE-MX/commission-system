"""AI 全链路调用费用结算与终态兜底。

硬约束：
1. 计费代码绝不放进业务调用的 try 块内，且内部自带独立 try/except；
   任何计费异常都只记录 warning + print(flush=True)，绝不改变成功调用的结果。
2. 统一优先读取 ark_ai_model_prices（单一真相源），过渡期兼容回退
   preset.parameters.rate_card 与 preset.parameters.chat.pricing。
3. Agent Runtime 的保守预扣（accounting_source == 'reservation'）严禁当真实消费计费。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.models import AiCallLog, AiModelPrice
from app.core.time import beijing_now

logger = logging.getLogger("commission.ai.billing")

MILLION = Decimal("1000000")
QUANT_6 = Decimal("0.000001")
MAX_COST_AMOUNT = Decimal("99999999.999999")

TEST_CALLER_MODULES = {"ai_preset_test"}
TEST_PRESET_WHITELIST = {"mail_outreach_internal_test"}


def terminal_failed_fields(now: Optional[datetime] = None) -> dict:
    """外部 pending 兜底清理统一补写的终态字段。"""
    return {
        "finished_at": now or beijing_now(),
        "cost_status": "failed",
    }


def mark_log_terminal_failed(
    db: Session,
    log: Optional[AiCallLog],
    *,
    finished_at: Optional[datetime] = None,
) -> None:
    if log is None:
        return
    log.finished_at = finished_at or beijing_now()
    log.cost_status = "failed"


def _quantize6(value: Decimal) -> Decimal:
    return value.quantize(QUANT_6, rounding=ROUND_HALF_UP)


def _compute_token_cost(
    input_per_million: Decimal,
    output_per_million: Decimal,
    tokens_prompt: Optional[int],
    tokens_completion: Optional[int],
) -> Optional[Decimal]:
    if tokens_prompt is None or tokens_completion is None:
        return None
    if tokens_prompt < 0 or tokens_completion < 0:
        return None
    raw = (
        input_per_million * Decimal(tokens_prompt)
        + output_per_million * Decimal(tokens_completion)
    ) / MILLION
    return _quantize6(raw)


def _compute_rate_card_cost(rate_card: Optional[dict], usage_detail: Optional[dict]) -> Optional[Decimal]:
    if not isinstance(rate_card, dict) or not isinstance(usage_detail, dict):
        return None
    from app.ai.image_job_runtime import estimated_cost_microusd
    microusd = estimated_cost_microusd(rate_card, usage_detail)
    if microusd is None:
        return None
    return _quantize6(Decimal(microusd) / MILLION)


def _compute_fallback_chat_pricing(
    chat_pricing: Optional[dict],
    tokens_prompt: Optional[int],
    tokens_completion: Optional[int],
) -> tuple[Optional[Decimal], Optional[str], Optional[dict]]:
    if not isinstance(chat_pricing, dict):
        return None, None, None
    currency = chat_pricing.get("currency")
    if currency not in {"CNY", "USD"}:
        return None, None, None
    try:
        inp = Decimal(str(chat_pricing["input_per_million"]))
        out = Decimal(str(chat_pricing["output_per_million"]))
    except (KeyError, ValueError, InvalidOperation):
        return None, None, None
    cost = _compute_token_cost(inp, out, tokens_prompt, tokens_completion)
    if cost is None:
        return None, None, None
    return cost, currency, {
        "source": "fallback_chat_pricing",
        "pricing_mode": "token",
        "currency": currency,
        "input_per_million": str(inp),
        "output_per_million": str(out),
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
    }


def _resolve_cost(
    db: Session,
    *,
    provider_id: Optional[int],
    provider_type: Optional[str],
    model: Optional[str],
    preset_name: Optional[str],
    caller_module: Optional[str],
    status: str,
    tokens_prompt: Optional[int],
    tokens_completion: Optional[int],
    usage_detail: Optional[dict],
    preset_parameters: Optional[dict],
    accounting_source: Optional[str],
) -> tuple[str, Optional[Decimal], Optional[str], Optional[dict]]:
    if caller_module in TEST_CALLER_MODULES or preset_name in TEST_PRESET_WHITELIST:
        return "test", None, None, {"reason": "test_call"}

    if provider_type == "accio_work":
        return "not_billed", None, None, {"reason": "accio_work"}

    if status != "success":
        return "failed", None, None, {"reason": f"status_{status}"}

    # Agent Runtime 未拿到真实 provider usage 时保留的保守预扣不得算作实际消费
    if accounting_source == "reservation":
        return "no_usage", None, None, {"reason": "agent_reservation_not_billable"}

    params = preset_parameters if isinstance(preset_parameters, dict) else {}

    # 优先级 1：统一单价表 ark_ai_model_prices（带唯一索引直查，避免多 worker 缓存脏读）
    price_row = None
    if provider_id is not None and model:
        price_row = (
            db.query(AiModelPrice)
            .filter(
                AiModelPrice.provider_id == provider_id,
                AiModelPrice.model == model,
            )
            .first()
        )

    if price_row is not None:
        mode = price_row.pricing_mode
        if mode == "per_call":
            if price_row.per_call_amount is None:
                return "unpriced", None, None, {"source": "model_prices", "reason": "missing_per_call_amount"}
            amount = _quantize6(Decimal(price_row.per_call_amount))
            return "priced", amount, price_row.currency, {
                "source": "model_prices",
                "pricing_mode": "per_call",
                "currency": price_row.currency,
                "per_call_amount": str(amount),
            }

        if mode == "image_rate_card":
            rate_card = params.get("rate_card")
            amount = _compute_rate_card_cost(rate_card, usage_detail)
            if amount is None:
                if not usage_detail:
                    return "no_usage", None, None, {"source": "model_prices", "pricing_mode": "image_rate_card", "reason": "no_usage"}
                return "unpriced", None, None, {"source": "model_prices", "pricing_mode": "image_rate_card", "reason": "rate_card_unmatched"}
            return "priced", amount, "USD", {
                "source": "model_prices_rate_card",
                "pricing_mode": "image_rate_card",
                "currency": "USD",
                "rate_card": rate_card,
            }

        # mode == "token"
        if price_row.input_per_million is None or price_row.output_per_million is None:
            return "unpriced", None, None, {"source": "model_prices", "reason": "incomplete_token_price"}
        if tokens_prompt is None or tokens_completion is None:
            return "no_usage", None, None, {"source": "model_prices", "reason": "missing_tokens"}
        amount = _compute_token_cost(
            Decimal(price_row.input_per_million),
            Decimal(price_row.output_per_million),
            tokens_prompt,
            tokens_completion,
        )
        if amount is None:
            return "no_usage", None, None, {"source": "model_prices", "reason": "invalid_tokens"}
        return "priced", amount, price_row.currency, {
            "source": "model_prices",
            "pricing_mode": "token",
            "currency": price_row.currency,
            "input_per_million": str(price_row.input_per_million),
            "output_per_million": str(price_row.output_per_million),
            "tokens_prompt": tokens_prompt,
            "tokens_completion": tokens_completion,
        }

    # 优先级 2（兼容过渡期）：复用 preset.parameters.rate_card 或 parameters.chat.pricing
    if isinstance(params.get("rate_card"), dict):
        amount = _compute_rate_card_cost(params["rate_card"], usage_detail)
        if amount is not None:
            return "priced", amount, "USD", {
                "source": "fallback_rate_card",
                "pricing_mode": "image_rate_card",
                "currency": "USD",
                "rate_card": params["rate_card"],
            }

    chat_cfg = params.get("chat") if isinstance(params.get("chat"), dict) else None
    if chat_cfg and isinstance(chat_cfg.get("pricing"), dict):
        amount, currency, snap = _compute_fallback_chat_pricing(
            chat_cfg["pricing"], tokens_prompt, tokens_completion,
        )
        if amount is not None and currency is not None:
            return "priced", amount, currency, snap
        if tokens_prompt is None or tokens_completion is None:
            return "no_usage", None, None, {"source": "fallback_chat_pricing", "reason": "missing_tokens"}

    if tokens_prompt is None and tokens_completion is None:
        return "no_usage", None, None, {"reason": "no_price_and_no_usage"}
    return "unpriced", None, None, {"reason": "no_price_configured"}


def _sanitize_cost_result(
    cost_status: str,
    cost_amount: Optional[Decimal],
    cost_currency: Optional[str],
    snapshot: Optional[dict],
) -> tuple[str, Optional[Decimal], Optional[str], Optional[dict]]:
    if cost_amount is not None and (cost_amount < 0 or cost_amount > MAX_COST_AMOUNT):
        logger.warning("AI billing cost out of DECIMAL(14,6) range: %s", cost_amount)
        print(f"[AI-BILLING] cost out of range: {cost_amount}", flush=True)
        return "unpriced", None, None, {"reason": "cost_out_of_range", "raw_amount": str(cost_amount)}
    return cost_status, cost_amount, cost_currency, snapshot


def compute_cost_fields(
    db: Session,
    *,
    provider_id: Optional[int],
    provider_type: Optional[str],
    model: Optional[str],
    preset_name: Optional[str],
    caller_module: Optional[str],
    status: str,
    tokens_prompt: Optional[int] = None,
    tokens_completion: Optional[int] = None,
    usage_detail: Optional[dict] = None,
    preset_parameters: Optional[dict] = None,
    accounting_source: Optional[str] = None,
) -> dict:
    """独立计算费用列字典，内部吞并所有计费异常，永不向上抛错。"""
    try:
        cost_status, cost_amount, cost_currency, snapshot = _sanitize_cost_result(*_resolve_cost(
            db,
            provider_id=provider_id,
            provider_type=provider_type,
            model=model,
            preset_name=preset_name,
            caller_module=caller_module,
            status=status,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            usage_detail=usage_detail,
            preset_parameters=preset_parameters,
            accounting_source=accounting_source,
        ))
        return {
            "cost_status": cost_status,
            "cost_amount": cost_amount,
            "cost_currency": cost_currency,
            "price_snapshot": snapshot,
        }
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("AI billing calculation failed model=%s: %s", model, type(exc).__name__)
        print(f"[AI-BILLING] calculation failed model={model} err={type(exc).__name__}", flush=True)
        return {
            "cost_status": "unpriced" if status == "success" else "failed",
            "cost_amount": None,
            "cost_currency": None,
            "price_snapshot": {"error": type(exc).__name__},
        }


def settle_call_log_cost(
    db: Session,
    log_id: Optional[int],
    *,
    provider_id: Optional[int],
    provider_type: Optional[str],
    model: Optional[str],
    preset_name: Optional[str],
    caller_module: Optional[str],
    status: str,
    tokens_prompt: Optional[int] = None,
    tokens_completion: Optional[int] = None,
    usage_detail: Optional[dict] = None,
    preset_parameters: Optional[dict] = None,
    accounting_source: Optional[str] = None,
    finished_at: Optional[datetime] = None,
) -> None:
    """在调用主事务提交后独立结算费用。任何异常均内部吸收，绝不影响业务返回。"""
    if not log_id:
        return
    try:
        cost_status, cost_amount, cost_currency, snapshot = _sanitize_cost_result(*_resolve_cost(
            db,
            provider_id=provider_id,
            provider_type=provider_type,
            model=model,
            preset_name=preset_name,
            caller_module=caller_module,
            status=status,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            usage_detail=usage_detail,
            preset_parameters=preset_parameters,
            accounting_source=accounting_source,
        ))
        log_row = db.query(AiCallLog).filter(AiCallLog.id == log_id).first()
        if log_row is None:
            return
        if log_row.provider_id is None and provider_id is not None:
            log_row.provider_id = provider_id
        if log_row.finished_at is None:
            log_row.finished_at = finished_at or beijing_now()
        log_row.cost_status = cost_status
        log_row.cost_amount = cost_amount
        log_row.cost_currency = cost_currency
        log_row.price_snapshot = snapshot
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI billing settlement failed for log_id=%s: %s", log_id, type(exc).__name__)
        print(f"[AI-BILLING] settlement failed log_id={log_id} err={type(exc).__name__}", flush=True)
        try:
            db.rollback()
            log_row = db.query(AiCallLog).filter(AiCallLog.id == log_id).first()
            if log_row is not None and log_row.cost_status is None:
                log_row.cost_status = "unpriced" if status == "success" else "failed"
                if log_row.finished_at is None:
                    log_row.finished_at = finished_at or beijing_now()
                log_row.price_snapshot = {"error": type(exc).__name__}
                db.commit()
        except Exception as fallback_exc:  # noqa: BLE001
            db.rollback()
            logger.warning(
                "AI billing fallback write failed for log_id=%s: %s",
                log_id,
                type(fallback_exc).__name__,
            )
            print(
                f"[AI-BILLING] fallback write failed log_id={log_id} err={type(fallback_exc).__name__}",
                flush=True,
            )
