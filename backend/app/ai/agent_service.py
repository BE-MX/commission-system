"""OpenAI-compatible streaming gateway for governed Agent runs.

The runtime owns orchestration. Ark still owns model selection, credentials,
budgets and audit metadata.  Business modules import this through
``app.ai.service`` so model access keeps a single governed facade.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import logging
import time
from typing import Iterator

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import RunStatus
from app.agent_runtime.errors import ConflictError, ForbiddenError
from app.agent_runtime.models import AgentProfile, AgentRun
from app.agent_runtime.models import AgentEvent
from app.ai.http_client import build_chat_url, build_headers
from app.ai.keyring import decrypt_key
from app.ai.models import AiCallLog, AiPreset
from app.ai.provider_service import get_provider
from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.core.config import get_settings


logger = logging.getLogger("commission.ai.agent_gateway")

_SERVER_PARAMETER_KEYS = {
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "stop",
    "reasoning_effort",
}
_RUNNABLE_STATUSES = {RunStatus.RUNNING.value, RunStatus.WAITING_INPUT.value}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _message_snapshot(messages: list[dict], tools: list[dict]) -> str:
    rows = []
    for message in messages:
        content = message.get("content")
        serialized = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
        rows.append({
            "role": str(message.get("role") or "unknown")[:32],
            "content_length": len(serialized),
            "content_sha256": _sha(serialized),
            "has_tool_calls": bool(message.get("tool_calls")),
        })
    return json.dumps({
        "message_count": len(rows),
        "messages": rows,
        "tools": sorted(_tool_name(item) for item in tools),
    }, ensure_ascii=False, sort_keys=True)


def _tool_name(tool: dict) -> str:
    function = tool.get("function") if isinstance(tool, dict) else None
    return str((function or {}).get("name") or "")


def _raw_tool_name(name: str) -> str:
    # DSH MCP client exposes mcp__<server>__<raw-name>.  Ark currently uses the
    # stable server name "ark" but accepts any server prefix and scopes the raw
    # tool name, avoiding accidental coupling to a runtime display name.
    if name.startswith("mcp__") and "__" in name[5:]:
        return name.split("__", 2)[-1]
    return name


def _load_run_and_profile(db: Session, claims: dict) -> tuple[AgentRun, AgentProfile]:
    try:
        run_id = int(claims["run_id"])
        profile_id = int(claims["profile_id"])
        owner_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ForbiddenError("Agent Run 委托令牌缺少必要范围") from exc

    run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one_or_none()
    profile = db.query(AgentProfile).filter(AgentProfile.id == profile_id).one_or_none()
    user = db.query(ArkUser).filter(ArkUser.id == owner_id).one_or_none()
    if run is None or profile is None or user is None or not user.is_active or user.deleted_at is not None:
        raise ForbiddenError("Agent Run 委托范围不存在")
    if run.profile_id != profile.id or run.owner_user_id != owner_id:
        raise ForbiddenError("Agent Run 委托范围与任务不匹配")
    if claims.get("session_id") != run.session_id or claims.get("profile_key") != profile.profile_key:
        raise ForbiddenError("Agent Run 委托范围已经失效")
    if claims.get("runtime") != run.source_runtime:
        raise ForbiddenError("Agent Runtime 与委托范围不匹配")
    if claims.get("attempt_no") != run.attempt_no or claims.get("lease_nonce") != run.lease_token_hash:
        raise ForbiddenError("Agent Run 委托令牌不属于当前租约")
    if profile.status != "active":
        raise ForbiddenError("Agent Profile 已停用")
    delegated_permissions = set(claims.get("permissions") or [])
    frozen_permissions = set((run.context_snapshot or {}).get("permissions") or [])
    current_permissions = set(get_user_permissions(user))
    current_roles = set(get_user_roles(user))
    if "agent_runtime:invoke" not in delegated_permissions or delegated_permissions != frozen_permissions:
        raise ForbiddenError("Agent Run 委托权限与任务快照不匹配")
    if "super_admin" not in current_roles and "agent_runtime:invoke" not in current_permissions:
        raise ForbiddenError("当前账号的 Agent 调用权限已被撤销")
    if run.status not in _RUNNABLE_STATUSES:
        raise ConflictError("Agent Run 尚未开始或已经结束")
    if run.cancel_requested:
        raise ConflictError("Agent Run 已请求取消")
    if run.lease_expires_at is None or run.lease_expires_at <= datetime.utcnow():
        raise ConflictError("Agent Run 租约已过期")
    return run, profile


def _filter_tools(profile: AgentProfile, claims: dict, tools: list[dict], tool_choice) -> list[dict]:
    allowed = set(profile.tool_allowlist or [])
    token_allowed = set(claims.get("tools") or [])
    if token_allowed != allowed:
        raise ForbiddenError("Agent Run 工具范围与 Profile 版本不匹配")
    requested = [_raw_tool_name(_tool_name(item)) for item in tools]
    if any(not name for name in requested):
        raise ValueError("tools 中存在缺少 function.name 的定义")
    # Ark MCP serves personal-token and multiple Profile tools on one endpoint.
    # DSH discovers the superset; the model gateway projects only this Run's
    # immutable allowlist before any definition reaches the provider.
    effective = [item for item, raw_name in zip(tools, requested) if raw_name in allowed]
    if isinstance(tool_choice, dict):
        chosen = _raw_tool_name(str(((tool_choice.get("function") or {}).get("name")) or ""))
        if chosen not in allowed:
            raise ForbiddenError(f"Agent Run 无权强制调用工具: {chosen or 'unknown'}")
    return effective


def _load_openai_preset(db: Session, profile: AgentProfile):
    preset = db.query(AiPreset).filter(
        AiPreset.preset_name == profile.model_preset,
        AiPreset.deleted_at.is_(None),
        AiPreset.is_enabled.is_(True),
    ).one_or_none()
    if preset is None:
        raise ConflictError(f"Agent 模型预设 {profile.model_preset} 不存在或未启用")
    provider = get_provider(db, preset.provider_id)
    if provider.provider_type != "direct" or provider.api_type != "openai":
        raise ConflictError("DSH 当前只支持方舟 direct/openai 模型预设")
    if not provider.is_enabled or provider.deleted_at is not None:
        raise ConflictError("Agent 模型提供商当前不可用")
    return preset, provider


def _reserve_budget(
    db: Session, run: AgentRun, profile: AgentProfile,
    *, messages: list[dict], tools: list[dict], desired_output_tokens: int,
) -> tuple[int, int, int]:
    settings = get_settings()
    stale_before = datetime.utcnow() - timedelta(seconds=settings.AGENT_RUNTIME_RUN_TIMEOUT_SECONDS * 2)
    stale = db.query(AiCallLog).filter(
        AiCallLog.caller_module == "agent_runtime",
        AiCallLog.status == "pending",
        AiCallLog.created_at < stale_before,
    ).all()
    for item in stale:
        accounting_stage = (item.usage_detail or {}).get("accounting_stage")
        item.status = "timeout"
        item.error_code = "STALE_RESERVATION_RELEASED"
        if accounting_stage == "reserved":
            # The lazy stream was never advanced, so the provider request was
            # never dispatched and this reservation can be released safely.
            item.tokens_used = None
        else:
            # Unknown/legacy or dispatched reservations remain charged: after
            # a process crash we cannot prove the provider did not bill them.
            item.error_code = "STALE_DISPATCH_CHARGED"
    if stale:
        db.flush()
    if db.query(AiCallLog).filter(
        AiCallLog.caller_module == "agent_runtime",
        AiCallLog.status == "pending",
        AiCallLog.task_id.like(f"agent-run-{run.id}-%"),
    ).count():
        raise ConflictError("Agent Run 已有进行中的模型请求")
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = db.query(func.coalesce(func.sum(AiCallLog.tokens_used), 0)).filter(
        AiCallLog.caller_module == "agent_runtime",
        AiCallLog.created_at >= today,
        # Error/timeout requests may still have reached the provider. Their
        # conservative reservation remains a charge unless the stale-pending
        # cleanup above can prove that no final accounting was recorded.
        AiCallLog.tokens_used.isnot(None),
    ).scalar() or 0
    run_limit = int((profile.limits_json or {}).get("max_total_tokens") or 0)
    estimate_payload = json.dumps(
        {"messages": messages, "tools": tools}, ensure_ascii=False, sort_keys=True, default=str,
    ).encode("utf-8")
    # UTF-8 bytes are a conservative tokenizer-independent upper bound for
    # prompt tokens. Reserve before the request so concurrent calls cannot overshoot.
    estimated_prompt = max(1, len(estimate_payload))
    daily_remaining = settings.AGENT_RUNTIME_DAILY_TOKEN_BUDGET - int(used_today) - estimated_prompt
    run_remaining = run_limit - run.prompt_tokens - run.completion_tokens - estimated_prompt if run_limit else daily_remaining
    allowed_output = min(desired_output_tokens, daily_remaining, run_remaining)
    if allowed_output <= 0:
        raise ConflictError("Agent Run Token 预算已用尽")
    return allowed_output, estimated_prompt + allowed_output, estimated_prompt


def _remaining_runtime_seconds(db: Session, run: AgentRun, profile: AgentProfile) -> int:
    settings = get_settings()
    limits = profile.limits_json or {}
    max_steps = min(
        int(limits.get("max_steps", settings.AGENT_RUNTIME_MAX_STEPS_PER_RUN)),
        settings.AGENT_RUNTIME_MAX_STEPS_PER_RUN,
    )
    requested_steps = db.query(func.count(AgentEvent.id)).filter(
        AgentEvent.run_id == run.id,
        AgentEvent.event_type == "model.requested",
    ).scalar() or 0
    if int(requested_steps) > max_steps or run.steps_used > max_steps:
        raise ConflictError("Agent 步骤数超过 Profile 限制")
    timeout_seconds = min(
        int(limits.get("timeout_seconds", settings.AGENT_RUNTIME_RUN_TIMEOUT_SECONDS)),
        settings.AGENT_RUNTIME_RUN_TIMEOUT_SECONDS,
    )
    if run.started_at is None:
        return timeout_seconds
    remaining = timeout_seconds - int((datetime.utcnow() - run.started_at).total_seconds())
    if remaining <= 0:
        raise ConflictError("Agent 执行时间超过 Profile 限制")
    return remaining


def prepare_agent_chat(
    db: Session,
    *,
    claims: dict,
    messages: list[dict],
    tools: list[dict],
    tool_choice=None,
    parallel_tool_calls: bool | None = None,
) -> tuple[Iterator[bytes], str]:
    """Validate a delegated call and return a raw OpenAI SSE iterator + model."""
    settings = get_settings()
    if not settings.AGENT_RUNTIME_ENABLED:
        raise ConflictError("Agent Runtime 当前未启用")
    if not messages or len(messages) > 500:
        raise ValueError("messages 数量必须在 1 到 500 之间")
    if len(tools) > 100:
        raise ValueError("tools 数量不能超过 100")

    # A stable first Profile row is the daily-budget reservation mutex. The
    # Run row is locked by _load_run_and_profile for per-Run serialization.
    db.query(AgentProfile).order_by(AgentProfile.id).with_for_update().first()
    run, profile = _load_run_and_profile(db, claims)
    remaining_runtime = _remaining_runtime_seconds(db, run, profile)
    effective_tools = _filter_tools(profile, claims, tools, tool_choice)
    preset, provider = _load_openai_preset(db, profile)
    governed_messages = [
        {"role": "system", "content": profile.system_prompt},
        *(item for item in messages if item.get("role") != "system"),
    ]

    body = {"model": preset.model, "messages": governed_messages, "stream": True}
    for key, value in (preset.parameters or {}).items():
        if key in _SERVER_PARAMETER_KEYS:
            body[key] = value
    max_output = int((profile.limits_json or {}).get("max_output_tokens") or 0)
    if max_output:
        configured = body.get("max_completion_tokens", body.get("max_tokens", max_output))
        desired_output = min(int(configured), max_output)
        allowed_output, reserved_tokens, reserved_prompt_tokens = _reserve_budget(
            db, run, profile, messages=governed_messages, tools=effective_tools,
            desired_output_tokens=desired_output,
        )
        body["max_tokens"] = allowed_output
        body.pop("max_completion_tokens", None)
    else:
        raise ConflictError("Agent Profile 必须配置 max_output_tokens")
    if effective_tools:
        body["tools"] = effective_tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            body["parallel_tool_calls"] = parallel_tool_calls
    body["stream_options"] = {"include_usage": True}

    log = AiCallLog(
        task_id=f"agent-run-{run.id}-{int(time.time() * 1000)}",
        caller_module="agent_runtime",
        caller_user_id=run.owner_user_id,
        preset_id=preset.id,
        preset_name=preset.preset_name,
        provider_type=provider.provider_type,
        model=preset.model,
        prompt_snapshot=_message_snapshot(governed_messages, effective_tools),
        status="pending",
        tokens_used=reserved_tokens,
        usage_detail={
            "accounting_stage": "reserved",
            "reserved_tokens": reserved_tokens,
            "reserved_prompt_tokens": reserved_prompt_tokens,
            "reserved_completion_tokens": allowed_output,
        },
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    api_key = decrypt_key(provider.api_key) if provider.api_key else None
    headers = build_headers(provider, api_key)
    url = build_chat_url(provider.api_base, "openai")
    provider_timeout = int(provider.timeout_sec or remaining_runtime)
    timeout = max(1, min(provider_timeout, remaining_runtime))

    def generate() -> Iterator[bytes]:
        started = time.time()
        absolute_deadline = time.monotonic() + remaining_runtime
        next_scope_check = time.monotonic()
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        response_hash = hashlib.sha256()
        response_chars = 0
        response_tools: set[str] = set()
        finish_reason = None
        status = "error"
        error_code = None
        error_message = None
        saw_done = False
        try:
            # prepare_agent_chat returns a lazy iterator. Mark the reservation
            # dispatched only when that iterator is actually advanced, before
            # opening the upstream request.
            db.rollback()
            dispatched_log = db.query(AiCallLog).filter(AiCallLog.id == log.id).one_or_none()
            if dispatched_log is not None and dispatched_log.status == "pending":
                dispatched_log.usage_detail = {
                    **(dispatched_log.usage_detail or {}),
                    "accounting_stage": "dispatched",
                }
                db.commit()
            with httpx.Client(timeout=timeout, verify=True, follow_redirects=False) as client:
                with client.stream("POST", url, headers=headers, json=body) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        now_monotonic = time.monotonic()
                        if now_monotonic >= absolute_deadline:
                            raise RuntimeError("Agent model stream exceeded Run deadline")
                        if now_monotonic >= next_scope_check:
                            db.rollback()
                            current_scope = db.query(AgentRun).populate_existing().filter(
                                AgentRun.id == run.id,
                            ).one_or_none()
                            if (
                                current_scope is None
                                or current_scope.status not in _RUNNABLE_STATUSES
                                or current_scope.cancel_requested
                                or current_scope.lease_token_hash != claims.get("lease_nonce")
                            ):
                                raise RuntimeError("Agent Run scope was revoked during model stream")
                            db.rollback()
                            next_scope_check = now_monotonic + 2
                        encoded = (line + "\n").encode("utf-8")
                        yield encoded
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        if raw == "[DONE]":
                            saw_done = True
                            continue
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        chunk_usage = chunk.get("usage") or {}
                        for key in usage:
                            if chunk_usage.get(key) is not None:
                                usage[key] = int(chunk_usage[key])
                        for choice in chunk.get("choices") or []:
                            finish_reason = choice.get("finish_reason") or finish_reason
                            delta = choice.get("delta") or {}
                            content = delta.get("content") or delta.get("reasoning_content") or ""
                            if isinstance(content, str):
                                response_hash.update(content.encode("utf-8"))
                                response_chars += len(content)
                            for tool_call in delta.get("tool_calls") or []:
                                name = ((tool_call.get("function") or {}).get("name"))
                                if name:
                                    response_tools.add(name)
                    if not saw_done:
                        raise RuntimeError("OpenAI stream ended before [DONE]")
                    status = "success"
        except GeneratorExit:
            error_code = "CONSUMER_STOPPED"
            error_message = "Agent Runtime 已停止接收模型流"
            raise
        except httpx.HTTPStatusError as exc:
            error_code = "UPSTREAM_HTTP_ERROR"
            error_message = f"上游模型请求失败 (HTTP {exc.response.status_code})"
            payload = {"error": {"message": error_message, "type": "upstream_error", "code": error_code}}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode("utf-8")
        except Exception as exc:  # noqa: BLE001
            error_code = "UPSTREAM_REQUEST_FAILED"
            error_message = "上游模型连接失败"
            logger.warning("Agent model stream failed: %s", type(exc).__name__)
            payload = {"error": {"message": error_message, "type": "upstream_error", "code": error_code}}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\ndata: [DONE]\n\n".encode("utf-8")
        finally:
            db.rollback()
            current_log = db.query(AiCallLog).filter(AiCallLog.id == log.id).one_or_none()
            current_run = db.query(AgentRun).filter(AgentRun.id == run.id).with_for_update().one_or_none()
            if current_log is not None:
                actual_total = usage["total_tokens"] or usage["prompt_tokens"] + usage["completion_tokens"]
                has_authoritative_usage = status == "success" and actual_total > 0
                if has_authoritative_usage:
                    charged_total = actual_total
                    charged_prompt = usage["prompt_tokens"]
                    charged_completion = usage["completion_tokens"]
                    # Some OpenAI-compatible providers send only total_tokens.
                    # Preserve the full charge even when the split is absent.
                    charged_completion += max(0, charged_total - charged_prompt - charged_completion)
                    accounting_source = "provider_usage"
                else:
                    # Missing usage, a partial stream, or consumer disconnect
                    # must not release the reservation and make hard budgets
                    # fail open.
                    charged_total = reserved_tokens
                    charged_prompt = reserved_prompt_tokens
                    charged_completion = allowed_output
                    accounting_source = "reservation"
                current_log.status = status
                current_log.tokens_prompt = charged_prompt
                current_log.tokens_completion = charged_completion
                current_log.tokens_used = charged_total
                current_log.duration_ms = int((time.time() - started) * 1000)
                current_log.error_code = error_code
                current_log.error_message = error_message
                current_log.usage_detail = {
                    **usage,
                    "finish_reason": finish_reason,
                    "accounting_stage": "finalized",
                    "accounting_source": accounting_source,
                    "reserved_tokens": reserved_tokens,
                }
                current_log.response_snapshot = json.dumps({
                    "content_length": response_chars,
                    "content_sha256": response_hash.hexdigest(),
                    "tool_names": sorted(response_tools),
                    "finish_reason": finish_reason,
                }, ensure_ascii=False, sort_keys=True)
            if current_run is not None and current_log is not None:
                current_run.prompt_tokens += charged_prompt
                current_run.completion_tokens += charged_completion
            db.commit()

    return generate(), preset.model
