"""Serialized admission and conservative accounting for paid text calls."""

from dataclasses import dataclass
from datetime import timedelta
import secrets
import time

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.ai.service import chat, prepare_text_chat
from app.ai_gateway.errors import GatewayError, report_failure
from app.ai_gateway.models import GatewayApp, GatewayAppPreset, GatewayRequest
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.core.time import beijing_now

OCCUPIED = ("pending", "unknown")


def lock_app(db, app_id):
    app = db.execute(select(GatewayApp).where(GatewayApp.id == app_id)
                     .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if app is None:
        raise GatewayError(404, "app_not_found", "站点应用不存在")
    return app


def require_owner(db, owner_id):
    # Read scalar columns: avoid ArkUser's joined role relationship/outer joins.
    owner = db.execute(select(ArkUser.id).where(
        ArkUser.id == owner_id, ArkUser.is_active.is_(True), ArkUser.deleted_at.is_(None),
    ).with_for_update(read=True)).scalar_one_or_none()
    if owner is None:
        raise GatewayError(403, "app_disabled", "负责人账号已停用或不存在")


def day_window(now):
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


@dataclass(frozen=True)
class Admission:
    row_id: int
    app_id: int
    owner_id: int
    snapshot: object


def admit(db, key_hash, request_id, data):
    settings = get_settings()
    try:
        app_id = db.execute(select(GatewayApp.id).where(GatewayApp.key_hash == key_hash)).scalar_one_or_none()
        if app_id is None:
            raise GatewayError(401, "invalid_api_key", "站点密钥无效")
        app = lock_app(db, app_id)
        if not secrets.compare_digest(app.key_hash, key_hash):
            raise GatewayError(401, "invalid_api_key", "站点密钥已失效")
        if not app.is_enabled:
            raise GatewayError(403, "app_disabled", "站点应用已停用")
        require_owner(db, app.owner_user_id)
        duplicate = db.execute(select(GatewayRequest.id).where(
            GatewayRequest.app_id == app.id, GatewayRequest.request_id == request_id,
        ).with_for_update()).first()
        if duplicate:
            raise GatewayError(409, "duplicate_request", "该请求已受理，请勿重复调用")
        # Authorization check precedes availability checks to avoid leaking presets.
        from app.ai.models import AiPreset
        permitted = db.execute(select(AiPreset.id).join(
            GatewayAppPreset, GatewayAppPreset.preset_id == AiPreset.id,
        ).where(GatewayAppPreset.app_id == app.id, AiPreset.preset_name == data.preset)
            .with_for_update(read=True)).scalar_one_or_none()
        if permitted is None:
            raise GatewayError(403, "preset_not_allowed", "该站点未获授权使用此能力")
        try:
            snapshot = prepare_text_chat(db, data.preset, min(app.max_output_tokens, settings.AI_GATEWAY_MAX_OUTPUT_TOKENS))
        except ValueError as exc:
            report_failure(exc, request_id)
            raise GatewayError(503, "preset_unavailable", "文本能力配置不可用，请联系管理员") from None
        now = beijing_now()
        start, end = day_window(now)
        minute = now.replace(second=0, microsecond=0)
        # Locking reads are current reads even if the initial key lookup established
        # a REPEATABLE READ snapshot. All writers serialize on the app row first.
        rows = db.execute(select(GatewayRequest.created_at, GatewayRequest.status).where(
            GatewayRequest.app_id == app.id,
            or_(GatewayRequest.created_at >= start, GatewayRequest.status.in_(OCCUPIED)),
        ).with_for_update()).all()
        if sum(start <= r.created_at < end for r in rows) >= app.daily_limit:
            raise GatewayError(429, "daily_limit_exceeded", "今日调用次数已用完", max(1, int((end - now).total_seconds())))
        if sum(minute <= r.created_at < minute + timedelta(minutes=1) for r in rows) >= app.rpm_limit:
            raise GatewayError(429, "rate_limit_exceeded", "请求过于频繁，请稍后再试", max(1, 60 - now.second))
        if sum(r.status in OCCUPIED for r in rows) >= app.concurrency_limit:
            raise GatewayError(429, "concurrency_limit_exceeded", "并发已满；若持续出现，请管理员核查待处理请求")
        row = GatewayRequest(app_id=app.id, request_id=request_id, owner_user_id=app.owner_user_id,
                             preset_id=snapshot.preset.id, preset_name=snapshot.preset.preset_name,
                             model=snapshot.preset.model, status="pending", created_at=now)
        db.add(row)
        db.flush()
        admission = Admission(row.id, app.id, app.owner_user_id, snapshot)
        db.commit()
        return admission
    except Exception as exc:
        db.rollback()
        if not isinstance(exc, GatewayError):
            report_failure(exc, request_id)
        raise


def usage_fields(result):
    fields = {}
    for key in ("tokens_prompt", "tokens_completion", "tokens_used"):
        value = result.get(key)
        fields[key] = value if type(value) is int and 0 <= value <= 2147483647 else None
    if fields["tokens_used"] is None and all(fields[k] is not None for k in ("tokens_prompt", "tokens_completion")):
        total = fields["tokens_prompt"] + fields["tokens_completion"]
        fields["tokens_used"] = total if total <= 2147483647 else None
    present = sum(v is not None for v in fields.values())
    fields["usage_status"] = "known" if present == 3 else "partial" if present else "unknown"
    return fields


def finish(db, row_id, **values):
    try:
        changed = db.execute(update(GatewayRequest).where(
            GatewayRequest.id == row_id, GatewayRequest.status == "pending",
        ).values(**values)).rowcount
        if changed != 1:
            raise GatewayError(503, "gateway_unavailable", "请求状态待核查，请勿重复调用")
        db.commit()
    except Exception as exc:
        db.rollback()
        if not isinstance(exc, GatewayError):
            report_failure(exc)
        raise


def invoke(db, key_hash, request_id, data):
    admission = admit(db, key_hash, request_id, data)
    started = time.monotonic()
    try:
        result = chat(db, preset_name=data.preset, messages=[m.model_dump() for m in data.messages],
                      caller_module=f"ai_gateway:{admission.app_id}", caller_user_id=admission.owner_id,
                      snapshot_mode="metadata", timeout_sec=get_settings().AI_GATEWAY_TIMEOUT_SEC,
                      enforce_total_timeout=True, trusted_text_snapshot=admission.snapshot)
    except Exception as exc:
        db.rollback()
        report_failure(exc, request_id)
        uncertain = not isinstance(exc, httpx.HTTPStatusError)
        error = "upstream_timeout" if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else "upstream_error"
        # Persistence failures are also unknown: the paid call may have finished.
        if isinstance(exc, SQLAlchemyError):
            raise GatewayError(503, "gateway_unavailable", "调用结果待核查，请勿重复调用") from None
        finish(db, admission.row_id, status="unknown" if uncertain else "error",
               error_code=error, duration_ms=int((time.monotonic() - started) * 1000), finished_at=beijing_now())
        raise GatewayError(504 if error == "upstream_timeout" else 502, error,
                           "上游结果待核查，请勿自动重试" if uncertain else "上游调用失败，请联系管理员") from None
    usage = usage_fields(result)
    finish(db, admission.row_id, status="success", ai_log_id=result["log_id"],
           duration_ms=int((time.monotonic() - started) * 1000), finished_at=beijing_now(), **usage)
    return {"request_id": request_id, "content": result["content"], "usage": {
        "input_tokens": usage["tokens_prompt"], "output_tokens": usage["tokens_completion"],
        "total_tokens": usage["tokens_used"], "status": usage["usage_status"],
    }}
