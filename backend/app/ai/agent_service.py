"""OpenAI-compatible streaming gateway for governed Agent runs.

The runtime owns orchestration. Ark still owns model selection, credentials,
budgets and audit metadata.  Business modules import this through
``app.ai.service`` so model access keeps a single governed facade.
"""

from __future__ import annotations

from datetime import datetime
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
from app.ai.http_client import build_chat_url, build_headers
from app.ai.keyring import decrypt_key
from app.ai.models import AiCallLog, AiPreset
from app.ai.provider_service import get_provider
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

    run = db.query(AgentRun).filter(AgentRun.id == run_id).one_or_none()
    profile = db.query(AgentProfile).filter(AgentProfile.id == profile_id).one_or_none()
    if run is None or profile is None:
        raise ForbiddenError("Agent Run 委托范围不存在")
    if run.profile_id != profile.id or run.owner_user_id != owner_id:
        raise ForbiddenError("Agent Run 委托范围与任务不匹配")
    if claims.get("session_id") != run.session_id or claims.get("profile_key") != profile.profile_key:
        raise ForbiddenError("Agent Run 委托范围已经失效")
    if claims.get("runtime") != run.source_runtime:
        raise ForbiddenError("Agent Runtime 与委托范围不匹配")
    if profile.status != "active":
        raise ForbiddenError("Agent Profile 已停用")
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


def _check_budget(db: Session, run: AgentRun, profile: AgentProfile) -> None:
    settings = get_settings()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    used_today = db.query(func.coalesce(func.sum(AiCallLog.tokens_used), 0)).filter(
        AiCallLog.caller_module == "agent_runtime",
        AiCallLog.created_at >= today,
        AiCallLog.status == "success",
    ).scalar() or 0
    if int(used_today) >= settings.AGENT_RUNTIME_DAILY_TOKEN_BUDGET:
        raise ConflictError("Agent Runtime 今日 Token 预算已用尽")
    run_limit = int((profile.limits_json or {}).get("max_total_tokens") or 0)
    if run_limit and run.prompt_tokens + run.completion_tokens >= run_limit:
        raise ConflictError("Agent Run Token 预算已用尽")


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

    run, profile = _load_run_and_profile(db, claims)
    effective_tools = _filter_tools(profile, claims, tools, tool_choice)
    _check_budget(db, run, profile)
    preset, provider = _load_openai_preset(db, profile)

    body = {"model": preset.model, "messages": messages, "stream": True}
    for key, value in (preset.parameters or {}).items():
        if key in _SERVER_PARAMETER_KEYS:
            body[key] = value
    max_output = int((profile.limits_json or {}).get("max_output_tokens") or 0)
    if max_output:
        configured = body.get("max_completion_tokens", body.get("max_tokens", max_output))
        body["max_tokens"] = min(int(configured), max_output)
        body.pop("max_completion_tokens", None)
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
        prompt_snapshot=_message_snapshot(messages, effective_tools),
        status="pending",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    api_key = decrypt_key(provider.api_key) if provider.api_key else None
    headers = build_headers(provider, api_key)
    url = build_chat_url(provider.api_base, "openai")
    timeout = max(int(provider.timeout_sec or 0), int((profile.limits_json or {}).get("timeout_seconds") or 0))

    def generate() -> Iterator[bytes]:
        started = time.time()
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
            with httpx.Client(timeout=timeout, verify=True, follow_redirects=False) as client:
                with client.stream("POST", url, headers=headers, json=body) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
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
                current_log.status = status
                current_log.tokens_prompt = usage["prompt_tokens"] or None
                current_log.tokens_completion = usage["completion_tokens"] or None
                current_log.tokens_used = usage["total_tokens"] or None
                current_log.duration_ms = int((time.time() - started) * 1000)
                current_log.error_code = error_code
                current_log.error_message = error_message
                current_log.usage_detail = {**usage, "finish_reason": finish_reason}
                current_log.response_snapshot = json.dumps({
                    "content_length": response_chars,
                    "content_sha256": response_hash.hexdigest(),
                    "tool_names": sorted(response_tools),
                    "finish_reason": finish_reason,
                }, ensure_ascii=False, sort_keys=True)
            if current_run is not None and status == "success":
                current_run.prompt_tokens += usage["prompt_tokens"]
                current_run.completion_tokens += usage["completion_tokens"]
            db.commit()

    return generate(), preset.model
