"""Strict privacy-safe AI translation and in-process idempotency."""

import json
import logging
import threading
import time
from collections import OrderedDict

import httpx

from app.ai.call_service import chat
from app.core.config import get_settings
from app.whatsapp_translation.auth import require_supported_extension
from app.whatsapp_translation.constants import DETECTED_SOURCE_LANGUAGES
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.glossary_service import glossary_for
from app.whatsapp_translation.quota_service import (
    BoundedSlidingWindowLimiter,
    record_failure,
    record_success,
    reserve_daily_input,
)
from app.whatsapp_translation.schemas import TranslateRequest, TranslateResponse, TranslationModelOutput


logger = logging.getLogger("commission.whatsapp_translation")



class TranslationCoordinator:
    def __init__(self, max_keys: int = 10_000, cache_seconds: int = 300) -> None:
        self.max_keys = max_keys
        self.cache_seconds = cache_seconds
        self.lock = threading.Lock()
        self.events: OrderedDict[tuple[int, str], dict[str, object]] = OrderedDict()
        self.outcomes: OrderedDict[tuple[int, str], tuple[float, object]] = OrderedDict()

    def _cached_outcome(self, key: tuple[int, str]):
        with self.lock:
            cached = self.outcomes.get(key)
            if cached is None:
                return None
            stored_at, outcome = cached
            if time.monotonic() - stored_at > self.cache_seconds:
                self.outcomes.pop(key, None)
                return None
            self.outcomes.move_to_end(key)
            return outcome

    def _store_outcome(self, key: tuple[int, str], outcome: object) -> None:
        with self.lock:
            self.outcomes[key] = (time.monotonic(), outcome)
            if len(self.outcomes) > self.max_keys:
                self.outcomes.popitem(last=False)

    def execute(self, device_id: int, request_id: str, callback, timeout_seconds: float = 10.0):
        key = (device_id, request_id)
        cached = self._cached_outcome(key)
        if cached is not None:
            return cached

        with self.lock:
            in_flight = self.events.get(key)
            if in_flight is None:
                in_flight = {"event": threading.Event(), "outcome": None}
                self.events[key] = in_flight
                if len(self.events) > self.max_keys:
                    self.events.popitem(last=False)
                owner = True
            else:
                owner = False

        if not owner:
            event = in_flight["event"]
            assert isinstance(event, threading.Event)
            completed = event.wait(timeout=timeout_seconds)
            if not completed:
                return "ai_unavailable"
            outcome = in_flight["outcome"]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        try:
            result = callback()
        except WhatsAppTranslationError as exc:
            result = exc
        except TimeoutError:
            result = WhatsAppTranslationError(503, "ai_timeout", "Translation AI timed out")
        except Exception:
            result = WhatsAppTranslationError(503, "ai_unavailable", "Translation AI unavailable")
        finally:
            in_flight["outcome"] = result
            if not isinstance(result, Exception):
                self._store_outcome(key, result)
            event = in_flight["event"]
            assert isinstance(event, threading.Event)
            event.set()
            with self.lock:
                self.events.pop(key, None)
        if isinstance(result, Exception):
            raise result
        return result

    def clear(self) -> None:
        with self.lock:
            self.events.clear()
            self.outcomes.clear()


translation_limiter = BoundedSlidingWindowLimiter(limit=get_settings().WHATSAPP_TRANSLATION_RATE_PER_MINUTE)
translation_coordinator = TranslationCoordinator()


def _response_error(error_code: str) -> WhatsAppTranslationError:
    return WhatsAppTranslationError(502, error_code, "Translation AI returned an invalid response")


def _parse_model_output(
    content: str,
    direction: str,
    target_language: str,
    original_text: str,
) -> TranslationModelOutput:
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        raise _response_error("translation_invalid_response")
    if not isinstance(payload, dict):
        raise _response_error("translation_invalid_response")
    try:
        output = TranslationModelOutput.model_validate(payload)
    except Exception:
        raise _response_error("translation_invalid_response")
    if output.detected_source_language not in DETECTED_SOURCE_LANGUAGES:
        raise _response_error("translation_invalid_response")
    if output.detected_source_language == target_language:
        return TranslationModelOutput(
            translated_text=original_text,
            detected_source_language=output.detected_source_language,
            back_translation=original_text if direction == "outgoing" else None,
        )
    if direction == "outgoing":
        if not (output.back_translation or "").strip():
            raise _response_error("translation_invalid_response")
        return output
    if output.back_translation is not None:
        return TranslationModelOutput(
            translated_text=output.translated_text,
            detected_source_language=output.detected_source_language,
        )
    return output


def _preset_name_for(direction: str) -> str:
    settings = get_settings()
    if direction == "outgoing":
        return settings.WHATSAPP_TRANSLATION_OUTGOING_PRESET_NAME
    return settings.WHATSAPP_TRANSLATION_PRESET_NAME


def _is_transient_provider_error(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {502, 503, 504}
    return isinstance(error, httpx.TransportError) and not isinstance(error, httpx.TimeoutException)


def _chat_with_transient_retry(db, **kwargs):
    timeout_seconds = float(kwargs.get("timeout_sec") or 0)
    started_at = time.monotonic()
    for attempt in range(2):
        try:
            return chat(db, **kwargs)
        except Exception as error:
            if attempt == 0 and _is_transient_provider_error(error):
                remaining_seconds = timeout_seconds - (time.monotonic() - started_at)
                if remaining_seconds < 1.0:
                    raise
                logger.warning(
                    "translation provider transient failure, retrying once error_type=%s",
                    type(error).__name__,
                )
                kwargs["timeout_sec"] = remaining_seconds
                continue
            raise
    raise RuntimeError("unreachable")


def translate_text(db, identity, request: TranslateRequest) -> TranslateResponse:
    require_supported_extension(identity)

    def execute():
        allowed, retry_after = translation_limiter.allow(str(identity.device_id))
        if not allowed:
            raise WhatsAppTranslationError(429, "rate_limited", "Translation rate limit exceeded", retry_after)

        start = time.monotonic()
        row = reserve_daily_input(db, identity, len(request.text))
        glossary = glossary_for(
            db,
            direction=request.direction,
            text=request.text,
            target_language=request.target_language,
        )
        input_payload = json.dumps({
            "direction": request.direction,
            "source_language": request.source_language,
            "target_language": request.target_language,
            "allowed_source_languages": list(DETECTED_SOURCE_LANGUAGES),
            "glossary": glossary,
            "text": request.text,
        }, ensure_ascii=False)
        try:
            ai_result = _chat_with_transient_retry(
                db,
                preset_name=_preset_name_for(request.direction),
                messages=[{"role": "user", "content": input_payload}],
                caller_module="whatsapp_translation",
                caller_user_id=identity.user_id,
                snapshot_mode="metadata",
                timeout_sec=get_settings().WHATSAPP_TRANSLATION_AI_TIMEOUT_SECONDS,
            )
            output = _parse_model_output(
                ai_result["content"],
                request.direction,
                request.target_language,
                request.text,
            )
            record_success(
                db,
                row,
                direction=request.direction,
                source_language=output.detected_source_language,
                target_language=request.target_language,
                duration_ms=int(ai_result.get("duration_ms") or 0),
                input_tokens=int(ai_result.get("tokens_prompt") or 0),
                output_tokens=int(ai_result.get("tokens_completion") or 0),
            )
            logger.info(
                "translation completed request_id=%s user_id=%s device_id=%s chars=%d direction=%s source=%s target=%s model_log_id=%s duration_ms=%d",
                str(request.request_id), identity.user_id, identity.device_id, len(request.text),
                request.direction, output.detected_source_language, request.target_language,
                ai_result.get("log_id"), int(ai_result.get("duration_ms") or 0),
            )
            return TranslateResponse(
                request_id=request.request_id,
                translated_text=output.translated_text,
                detected_source_language=output.detected_source_language,
                back_translation=output.back_translation,
                model_log_id=int(ai_result["log_id"]),
            )
        except WhatsAppTranslationError as exc:
            record_failure(db, row, direction=request.direction, error_code=exc.error_code)
            logger.info(
                "translation failed request_id=%s user_id=%s device_id=%s chars=%d direction=%s source=%s target=%s duration_ms=%d error_code=%s",
                str(request.request_id), identity.user_id, identity.device_id, len(request.text),
                request.direction, request.source_language, request.target_language,
                int((time.monotonic() - start) * 1000), exc.error_code,
            )
            raise
        except (TimeoutError, httpx.TimeoutException):
            error = WhatsAppTranslationError(503, "ai_timeout", "Translation AI timed out")
            record_failure(db, row, direction=request.direction, error_code=error.error_code)
            logger.info(
                "translation failed request_id=%s user_id=%s device_id=%s chars=%d direction=%s source=%s target=%s duration_ms=%d error_code=%s",
                str(request.request_id), identity.user_id, identity.device_id, len(request.text),
                request.direction, request.source_language, request.target_language,
                int((time.monotonic() - start) * 1000), error.error_code,
            )
            raise error
        except Exception:
            error = WhatsAppTranslationError(503, "ai_unavailable", "Translation AI unavailable")
            record_failure(db, row, direction=request.direction, error_code=error.error_code)
            logger.info(
                "translation failed request_id=%s user_id=%s device_id=%s chars=%d direction=%s source=%s target=%s duration_ms=%d error_code=%s",
                str(request.request_id), identity.user_id, identity.device_id, len(request.text),
                request.direction, request.source_language, request.target_language,
                int((time.monotonic() - start) * 1000), error.error_code,
            )
            raise error

    result = translation_coordinator.execute(identity.device_id, str(request.request_id), execute)
    if result == "ai_unavailable":
        raise WhatsAppTranslationError(503, "ai_unavailable", "Translation AI unavailable")
    if isinstance(result, Exception):
        raise result
    return result
