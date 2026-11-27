"""Provider-neutral streaming chat for the shared AI facade."""

from app.ai.stream_bridge import network_events
from app.ai.http_client import apply_token_parameter, transport_http_timeout

import json
import logging
import time
from typing import Iterable, Iterator, Optional

from app.ai.provider_config import request_timeout, transport_options

import httpx
from sqlalchemy.orm import Session

from app.ai.http_client import (
    build_anthropic_body,
    build_chat_url,
    build_headers,
)
from app.ai.keyring import decrypt_key
from app.ai.log_snapshot import serialize_response_snapshot
from app.ai.preset_config import text_request_parameters
from app.ai.models import AiCallLog, AiPreset
from app.ai.provider_service import get_provider
from app.ai.text_snapshot import TextChatSnapshot, freeze_text_call_config
from app.ai.billing_service import compute_cost_fields
from app.core.time import beijing_now

logger = logging.getLogger("commission.ai")

MIN_MULTIMODAL_STREAM_TIMEOUT_SEC = 120
MAX_STREAM_TEXT_SNAPSHOT_CHARS = 50000

_STREAM_ERROR_MESSAGES = {
    "provider_error": "上游模型返回错误",
    "invalid_stream": "上游流响应格式无效",
    "stream_incomplete": "上游流响应未正常结束",
}


def _has_image_message(messages: list) -> bool:
    return any(
        isinstance(message.get("content"), list)
        and any(block.get("type") == "image_url" for block in message["content"])
        for message in messages
    )


def _effective_stream_timeout(provider, messages: list) -> int:
    return request_timeout(provider, "multimodal" if _has_image_message(messages) else "text")


def _normalized_usage(
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    total_tokens: Optional[int] = None,
) -> dict:
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _stream_error(code: str) -> dict:
    return {
        "type": "error",
        "code": code,
        "message": _STREAM_ERROR_MESSAGES[code],
    }


def parse_provider_stream(api_type: str, lines: Iterable[str]) -> Iterator[dict]:
    """Convert Anthropic or OpenAI SSE lines into neutral business events."""
    if api_type not in {"anthropic", "openai"}:
        raise ValueError(f"不支持的 AI API 类型: {api_type}")

    finish = {}
    input_tokens = None
    output_tokens = None
    total_tokens = None
    meta_emitted = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        if api_type == "openai" and payload == "[DONE]":
            yield {"type": "done", **_normalized_usage(input_tokens, output_tokens, total_tokens), **finish}
            return
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            yield _stream_error("invalid_stream")
            return
        if not isinstance(data, dict):
            yield _stream_error("invalid_stream")
            return

        if data.get("error") or (api_type == "anthropic" and data.get("type") == "error"):
            yield _stream_error("provider_error")
            return

        if api_type == "anthropic":
            event_type = data.get("type")
            if event_type == "message_start":
                message = data.get("message") or {}
                usage = message.get("usage") or {}
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
                yield {"type": "usage", **_normalized_usage(input_tokens, output_tokens)}
                model = message.get("model")
                if model and not meta_emitted:
                    meta_emitted = True
                    yield {"type": "meta", "model": model}
            elif event_type == "content_block_delta":
                delta = data.get("delta") or {}
                if delta.get("type") == "thinking_delta" and isinstance(delta.get("thinking"), str):
                    yield {"type": "reasoning", "text": delta["thinking"]}
                text = delta.get("text") if delta.get("type") == "text_delta" else None
                if isinstance(text, str) and text:
                    yield {"type": "delta", "text": text}
            elif event_type == "message_delta":
                usage = data.get("usage") or {}
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
                yield {"type": "usage", **_normalized_usage(input_tokens, output_tokens)}
                delta = data.get("delta") or {}
                if delta.get("stop_reason") == "refusal":
                    yield _stream_error("provider_error")
                    return
                if delta.get("stop_reason"):
                    finish = {"finish_reason": delta["stop_reason"]}
            elif event_type == "message_stop":
                yield {"type": "done", **_normalized_usage(input_tokens, output_tokens), **finish}
                return
        else:
            usage = data.get("usage") or {}
            input_tokens = usage.get("prompt_tokens", input_tokens)
            output_tokens = usage.get("completion_tokens", output_tokens)
            total_tokens = usage.get("total_tokens", total_tokens)
            if usage:
                yield {"type": "usage", **_normalized_usage(input_tokens, output_tokens, total_tokens)}
            model = data.get("model")
            if model and not meta_emitted:
                meta_emitted = True
                yield {"type": "meta", "model": model}
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                if choices[0].get("finish_reason"):
                    finish = {"finish_reason": choices[0]["finish_reason"]}
                delta = choices[0].get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(reasoning, str) and reasoning:
                    yield {"type": "reasoning", "text": reasoning}
                text = delta.get("content")
                if isinstance(text, str) and text:
                    yield {"type": "delta", "text": text}

    yield _stream_error("stream_incomplete")


def _append_bounded_text(parts: list[str], text: str, current_length: int) -> int:
    remaining = MAX_STREAM_TEXT_SNAPSHOT_CHARS - current_length
    if remaining > 0:
        parts.append(text[:remaining])
        current_length += min(len(text), remaining)
    return current_length


def _finalize_log(
    db: Session,
    log: AiCallLog,
    start: float,
    status: str,
    usage: dict,
    text: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    termination: Optional[str] = None,
    api_key: Optional[str] = None,
    preset=None,
    provider=None,
) -> None:
    usage_detail = dict(usage)
    usage_detail['complete'] = status == 'success'
    if termination:
        usage_detail["termination"] = termination
    safe_text = text.replace(api_key, "[REDACTED]") if api_key else text
    finished_at = beijing_now()
    log_id = log.id
    snap_provider_id = getattr(provider, "id", None) or getattr(log, "provider_id", None)
    snap_provider_type = getattr(provider, "provider_type", None) or getattr(log, "provider_type", None)
    snap_model = getattr(preset, "model", None) or getattr(log, "model", None)
    snap_preset_name = getattr(preset, "preset_name", None) or getattr(log, "preset_name", None)
    snap_caller_module = getattr(log, "caller_module", None)
    snap_preset_params = dict(preset.parameters) if isinstance(getattr(preset, "parameters", None), dict) else None

    cost_fields = compute_cost_fields(
        db,
        provider_id=snap_provider_id,
        provider_type=snap_provider_type,
        model=snap_model,
        preset_name=snap_preset_name,
        caller_module=snap_caller_module,
        status=status,
        tokens_prompt=usage.get("input_tokens"),
        tokens_completion=usage.get("output_tokens"),
        usage_detail=usage_detail,
        preset_parameters=snap_preset_params,
    )
    core_values = {
        "status": status,
        "finished_at": finished_at,
        "tokens_prompt": usage.get("input_tokens"),
        "tokens_completion": usage.get("output_tokens"),
        "tokens_used": usage.get("total_tokens"),
        "duration_ms": int((time.time() - start) * 1000),
        "error_code": error_code,
        "error_message": error_message,
        "usage_detail": usage_detail,
        "response_snapshot": serialize_response_snapshot(
            {"content": safe_text, "usage": usage_detail}
        ),
    }
    final_values = {**core_values, **cost_fields}

    def apply_values(target_id: int, values: dict) -> None:
        # Recovery owns an interrupted terminal state; late workers cannot undo it.
        db.query(AiCallLog).filter(AiCallLog.id == target_id, AiCallLog.status == "pending").update(
            values, synchronize_session=False)

    try:
        apply_values(log_id, final_values)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("AI stream log commit failed, retrying once: %s", type(exc).__name__)
        print(f"[AI] stream log commit failed, retrying: {type(exc).__name__}", flush=True)
        try:
            retry_log = db.query(AiCallLog).filter(AiCallLog.id == log_id).first()
            if retry_log is None:
                raise RuntimeError("AI stream log row disappeared before retry")
            apply_values(retry_log.id, final_values)
            db.commit()
        except Exception as retry_exc:
            db.rollback()
            # 兜底隔离：若是计费列写入异常，剥离费用列后再保底落盘终态日志，绝不破坏已完成的流式响应
            if cost_fields.get("cost_amount") is not None or cost_fields.get("price_snapshot") is not None:
                try:
                    fallback_values = {
                        **core_values,
                        "cost_status": "unpriced" if status == "success" else "failed",
                        "cost_amount": None,
                        "cost_currency": None,
                        "price_snapshot": None,
                    }
                    retry_log = db.query(AiCallLog).filter(AiCallLog.id == log_id).first()
                    if retry_log is not None:
                        apply_values(retry_log.id, fallback_values)
                        db.commit()
                        logger.warning(
                            "AI stream billing columns dropped on fallback commit log_id=%s err=%s",
                            log_id, type(retry_exc).__name__,
                        )
                        print(f"[AI-BILLING] stream fallback dropped cost cols log_id={log_id}", flush=True)
                        return
                except Exception:  # noqa: BLE001
                    db.rollback()
            logger.warning("Failed to finalize AI stream log after retry: %s", type(retry_exc).__name__)
            print(
                f"[AI] failed to finalize stream log after retry: {type(retry_exc).__name__}",
                flush=True,
            )
            raise


def _safe_role(role) -> str:
    return role if role in {"system", "user", "assistant", "tool"} else "unknown"


def _content_summary(content) -> dict:
    if isinstance(content, str):
        return {"content_type": "text", "content_length": len(content)}
    if isinstance(content, list):
        block_types = []
        block_lengths = []
        for block in content:
            if not isinstance(block, dict):
                block_types.append("unknown")
                block_lengths.append(len(str(block)))
                continue
            block_type = block.get("type")
            if block_type not in {"text", "image_url", "image"}:
                block_type = "unknown"
            block_types.append(block_type)
            if block_type == "text":
                value = block.get("text")
            elif block_type == "image_url":
                image_url = block.get("image_url")
                value = image_url.get("url") if isinstance(image_url, dict) else image_url
            else:
                value = block
            block_lengths.append(len(value) if isinstance(value, str) else len(str(value)))
        return {
            "content_type": "blocks",
            "content_length": len(content),
            "block_types": block_types,
            "block_lengths": block_lengths,
        }
    if content is None:
        return {"content_type": "empty", "content_length": 0}
    return {"content_type": "unknown", "content_length": len(str(content))}


def _prompt_snapshot(full_messages: list) -> str:
    messages = []
    roles = []
    for message in full_messages:
        role = _safe_role(message.get("role")) if isinstance(message, dict) else "unknown"
        content = message.get("content") if isinstance(message, dict) else None
        roles.append(role)
        messages.append({"role": role, **_content_summary(content)})
    summary = {
        "message_count": len(full_messages),
        "roles": roles,
        "has_image": _has_image_message(full_messages),
        "messages": messages,
    }
    return json.dumps(summary, ensure_ascii=False)


def _create_pending_log(
    db: Session,
    preset: AiPreset,
    provider,
    full_messages: list,
    caller_module: str,
    caller_user_id: Optional[int],
) -> AiCallLog:
    log = AiCallLog(
        caller_module=caller_module,
        caller_user_id=caller_user_id,
        preset_id=preset.id,
        preset_name=preset.preset_name,
        provider_id=provider.id,
        provider_type=provider.provider_type,
        model=preset.model,
        prompt_snapshot=_prompt_snapshot(full_messages),
        status="pending",
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def _load_direct_preset(db: Session, preset_name: str):
    preset = (
        db.query(AiPreset)
        .filter(AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None))
        .first()
    )
    if not preset:
        raise ValueError(f"Preset '{preset_name}' 不存在")
    if not preset.is_enabled:
        raise ValueError(f"Preset '{preset_name}' 已被禁用")
    provider = get_provider(db, preset.provider_id)
    if provider.provider_type != "direct":
        raise ValueError(
            f"Preset '{preset_name}' 绑定的是 accio_work 类型 Provider，请使用 delegate 接口"
        )
    if not provider.is_enabled:
        raise ValueError(f"Provider '{provider.name}' 当前不可用")
    return preset, provider


def chat_stream(
    db: Session,
    preset_name: str,
    messages: list,
    caller_module: str,
    caller_user_id: Optional[int] = None,
    *,
    config_snapshot: TextChatSnapshot | None = None,
) -> Iterator[dict]:
    """Stream a direct model call and finalize its log on every exit path."""
    if config_snapshot is None:
        config_snapshot = freeze_text_call_config(*_load_direct_preset(db, preset_name))
    if not isinstance(config_snapshot, TextChatSnapshot) or config_snapshot.preset.preset_name != preset_name:
        raise ValueError("Invalid trusted stream configuration")
    preset, provider = config_snapshot.preset, config_snapshot.provider
    full_messages = []
    if preset.system_prompt:
        full_messages.append({"role": "system", "content": preset.system_prompt})
    full_messages.extend(messages)
    log = _create_pending_log(
        db, preset, provider, full_messages, caller_module, caller_user_id
    )

    start = time.time()
    usage = _normalized_usage(None, None)
    text_parts: list[str] = []
    text_length = 0
    terminal_event = None
    api_key = None

    try:
        api_type = getattr(provider, "api_type", "openai") or "openai"
        if api_type == "anthropic":
            params = build_anthropic_body(
                model=preset.model,
                messages=full_messages,
                system_prompt=preset.system_prompt,
                parameters=preset.parameters,
            )
        else:
            params = {"model": preset.model, "messages": full_messages}
            if preset.parameters:
                params.update(text_request_parameters(preset.parameters))
            params.setdefault("stream_options", {"include_usage": True})
        params["stream"] = True

        api_key = decrypt_key(provider.api_key) if provider.api_key else None
        headers = build_headers(provider, api_key)
        apply_token_parameter(params, provider)
        url = build_chat_url(provider.api_base, api_type, provider=provider)
        timeout_sec = request_timeout(provider, "multimodal" if _has_image_message(full_messages) else "text", preset)

        yield {"type": "meta", "log_id": log.id, "model": preset.model}
        events = network_events(
            lambda: httpx.Client(timeout=transport_http_timeout(timeout_sec, transport_options(provider, preset)), verify=True, follow_redirects=False),
            parse_provider_stream, api_type, url, headers, params)
        try:
            for event in events:
                event_type = event["type"]
                if event_type == "usage":
                    usage = {key: event.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")}
                    continue
                if event_type == "meta":
                    continue
                if event_type in {"reasoning", "heartbeat"}:
                    yield event
                elif event_type == "delta":
                    text_length = _append_bounded_text(text_parts, event["text"], text_length)
                    yield event
                else:
                    terminal_event = event
                    if event_type == "done":
                        usage = {key: event.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")}
                    break
        finally:
            events.close()
    except GeneratorExit:
        _finalize_log(
            db,
            log,
            start,
            "error",
            usage,
            "".join(text_parts),
            error_code="consumer_stopped",
            error_message="调用方已停止接收流式响应",
            termination="stopped",
            api_key=api_key,
            preset=preset,
            provider=provider,
        )
        raise
    except Exception as exc:
        db.rollback()
        if isinstance(exc, httpx.HTTPStatusError):
            code = "upstream_http_error"
            message = f"上游模型请求失败 (HTTP {exc.response.status_code})"
        else:
            code = "upstream_request_failed"
            message = "上游模型连接失败"
        logger.warning("AI stream failed: %s", type(exc).__name__)
        print(f"[AI] stream failed: {type(exc).__name__}", flush=True)
        _finalize_log(
            db,
            log,
            start,
            "error",
            usage,
            "".join(text_parts),
            error_code=code,
            error_message=message,
            api_key=api_key,
            preset=preset,
            provider=provider,
        )
        yield {"type": "error", "code": code, "message": message}
        return

    text = "".join(text_parts)
    if terminal_event and terminal_event["type"] == "done":
        _finalize_log(db, log, start, "success", usage, text, api_key=api_key, preset=preset, provider=provider)
    else:
        terminal_event = terminal_event or _stream_error("stream_incomplete")
        _finalize_log(
            db,
            log,
            start,
            "error",
            usage,
            text,
            error_code=terminal_event["code"],
            error_message=terminal_event["message"],
            api_key=api_key,
            preset=preset,
            provider=provider,
        )
    yield terminal_event
