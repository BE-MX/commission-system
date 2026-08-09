"""Provider-neutral streaming chat for the shared AI facade."""

import json
import logging
import time
from typing import Iterable, Iterator, Optional

import httpx
from sqlalchemy.orm import Session

from app.ai.http_client import (
    build_anthropic_body,
    build_chat_url,
    build_headers,
)
from app.ai.keyring import decrypt_key
from app.ai.log_snapshot import serialize_response_snapshot
from app.ai.models import AiCallLog, AiPreset
from app.ai.provider_service import get_provider

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
    base = provider.timeout_sec or 0
    if _has_image_message(messages):
        return max(base, MIN_MULTIMODAL_STREAM_TIMEOUT_SEC)
    return base


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
            yield {"type": "done", **_normalized_usage(input_tokens, output_tokens, total_tokens)}
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
                model = message.get("model")
                if model and not meta_emitted:
                    meta_emitted = True
                    yield {"type": "meta", "model": model}
            elif event_type == "content_block_delta":
                delta = data.get("delta") or {}
                text = delta.get("text") if delta.get("type") == "text_delta" else None
                if isinstance(text, str) and text:
                    yield {"type": "delta", "text": text}
            elif event_type == "message_delta":
                usage = data.get("usage") or {}
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
                delta = data.get("delta") or {}
                if delta.get("stop_reason") == "refusal":
                    yield _stream_error("provider_error")
                    return
            elif event_type == "message_stop":
                yield {"type": "done", **_normalized_usage(input_tokens, output_tokens)}
                return
        else:
            usage = data.get("usage") or {}
            input_tokens = usage.get("prompt_tokens", input_tokens)
            output_tokens = usage.get("completion_tokens", output_tokens)
            total_tokens = usage.get("total_tokens", total_tokens)
            model = data.get("model")
            if model and not meta_emitted:
                meta_emitted = True
                yield {"type": "meta", "model": model}
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                delta = choices[0].get("delta") or {}
                text = delta.get("content")
                if not text:
                    text = delta.get("reasoning_content") or delta.get("reasoning")
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
) -> None:
    usage_detail = dict(usage)
    if termination:
        usage_detail["termination"] = termination
    safe_text = text.replace(api_key, "[REDACTED]") if api_key else text
    final_values = {
        "status": status,
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

    def apply_values(target: AiCallLog) -> None:
        for field, value in final_values.items():
            setattr(target, field, value)

    log_id = log.id
    apply_values(log)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("AI stream log commit failed, retrying once: %s", type(exc).__name__)
        print(f"[AI] stream log commit failed, retrying: {type(exc).__name__}", flush=True)
        try:
            retry_log = db.query(AiCallLog).filter(AiCallLog.id == log_id).first()
            if retry_log is None:
                raise RuntimeError("AI stream log row disappeared before retry")
            apply_values(retry_log)
            db.commit()
        except Exception as retry_exc:
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
) -> Iterator[dict]:
    """Stream a direct model call and finalize its log on every exit path."""
    preset, provider = _load_direct_preset(db, preset_name)
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
                params.update(preset.parameters)
            params.setdefault("stream_options", {"include_usage": True})
        params["stream"] = True

        api_key = decrypt_key(provider.api_key) if provider.api_key else None
        headers = build_headers(provider, api_key)
        url = build_chat_url(provider.api_base, api_type)
        timeout_sec = _effective_stream_timeout(provider, full_messages)

        with httpx.Client(timeout=timeout_sec) as client:
            with client.stream("POST", url, headers=headers, json=params) as response:
                response.raise_for_status()
                yield {"type": "meta", "log_id": log.id, "model": preset.model}
                for event in parse_provider_stream(api_type, response.iter_lines()):
                    event_type = event["type"]
                    if event_type == "meta":
                        continue
                    if event_type == "delta":
                        text_length = _append_bounded_text(
                            text_parts, event["text"], text_length
                        )
                        yield event
                    else:
                        terminal_event = event
                        if event_type == "done":
                            usage = {
                                "input_tokens": event.get("input_tokens"),
                                "output_tokens": event.get("output_tokens"),
                                "total_tokens": event.get("total_tokens"),
                            }
                        break
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
        )
        yield {"type": "error", "code": code, "message": message}
        return

    text = "".join(text_parts)
    if terminal_event and terminal_event["type"] == "done":
        _finalize_log(db, log, start, "success", usage, text, api_key=api_key)
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
        )
    yield terminal_event
