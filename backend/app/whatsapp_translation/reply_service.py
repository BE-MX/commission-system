"""Direct sales reply orchestration. Chat payloads live only in request memory."""

import json
import logging
import time
import re

import httpx

from app.ai.models import AiPreset, AiProvider
from app.ai.service import chat
from app.core.config import get_settings
from app.knowledge.reply_sources import parse_bindings, retrieve_reply_sources, revalidate_sources
from app.whatsapp_translation.auth import require_supported_extension
from app.whatsapp_translation.constants import SUPPORTED_TARGET_LANGUAGES
from app.whatsapp_translation.errors import WhatsAppTranslationError
from app.whatsapp_translation.glossary_service import glossary_for
from app.whatsapp_translation.reply_direct import RULES
from app.whatsapp_translation import reply_memory
from app.whatsapp_translation.reply_schemas import ReplyRequest, ReplyResponse, ReplySource
from app.whatsapp_translation.reply_state import (
    OWNER_ID, digest, error, finish_request, live_actor, reply_cache, reserve_request,
)


logger = logging.getLogger("commission.whatsapp_reply")


def preset_signature(db, settings) -> str:
    names = [settings.WHATSAPP_REPLY_GENERATOR_PRESET]
    if set(names).intersection({settings.WHATSAPP_TRANSLATION_PRESET_NAME, settings.WHATSAPP_TRANSLATION_OUTGOING_PRESET_NAME}):
        raise error("reply_configuration_invalid", 503)
    items = []
    for name in names:
        row = db.query(AiPreset, AiProvider).join(AiProvider, AiProvider.id == AiPreset.provider_id).filter(
            AiPreset.preset_name == name, AiPreset.deleted_at.is_(None), AiPreset.is_enabled.is_(True),
            AiProvider.deleted_at.is_(None), AiProvider.is_enabled.is_(True), AiProvider.provider_type == "direct",
        ).first()
        if row is None:
            raise error("reply_not_configured", 503)
        preset, provider = row
        parameters = preset.parameters or {}
        if set(parameters).intersection({"messages", "system", "tools", "tool_choice", "functions", "function_call", "stream", "model"}) or parameters.get("n", 1) != 1:
            raise error("reply_configuration_invalid", 503)
        items.append({
            "preset_id": preset.id, "model": preset.model, "prompt": preset.system_prompt,
            "parameters": preset.parameters, "provider_id": provider.id,
            "provider_revision": str(provider.updated_at), "preset_revision": str(preset.updated_at),
        })
    return digest(items)


def reply_capabilities(db, identity) -> dict:
    settings = get_settings()
    available = False
    if settings.WHATSAPP_REPLY_ENABLED:
        try:
            live_actor(db, identity)
            preset_signature(db, settings)
            available = True
        except WhatsAppTranslationError:
            # Expected disabled/ungranted capability; the request still rechecks.
            available = False
    return {
        "available": available, "history_enabled": True, "max_messages": 2000, "default_messages": 2000,
        "max_context_chars": min(120000, settings.WHATSAPP_REPLY_MAX_CONTEXT_CHARS),
        "max_draft_chars": 2000, "max_goal_chars": 500,
        "timeout_seconds": min(180, settings.WHATSAPP_REPLY_TIMEOUT_SECONDS),
        "memory_enabled": settings.WHATSAPP_REPLY_MEMORY_ENABLED,
        "memory_retention_days": settings.WHATSAPP_REPLY_MEMORY_RETENTION_DAYS,
    }


def _configuration_signature(settings, preset_version: str) -> str:
    return digest({"sources": settings.WHATSAPP_REPLY_SOURCE_BINDINGS, "presets": preset_version,
                   "generator": RULES,
                   "memory_enabled": settings.WHATSAPP_REPLY_MEMORY_ENABLED})


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise error("reply_timeout", 503)
    return remaining


def _call(db, identity, preset, system, payload, deadline):
    result = chat(
        db, preset_name=preset,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        caller_module="whatsapp_reply", caller_user_id=identity.user_id,
        snapshot_mode="metadata", timeout_sec=_remaining(deadline), enforce_total_timeout=True,
    )
    _remaining(deadline)
    return result["content"]


def _check_current(db, identity, sources, signature):
    actor = live_actor(db, identity)
    settings = get_settings()
    if not settings.WHATSAPP_REPLY_ENABLED or _configuration_signature(settings, preset_signature(db, settings)) != signature:
        raise error("reply_configuration_changed")
    if not revalidate_sources(db, actor, sources):
        raise error("reply_sources_changed")
    return actor


def _cached_response(db, identity, record, signature):
    if record.owner_id != OWNER_ID:
        raise error("reply_result_unavailable")
    cached = reply_cache.get(record.id)
    if cached is None:
        raise error("reply_in_progress" if record.status == "pending" else "reply_result_unavailable")
    response, sources, original_signature = cached
    if original_signature != signature:
        raise error("reply_configuration_changed")
    _check_current(db, identity, sources, original_signature)
    return response.model_copy(deep=True)


def suggest_reply(db, identity, request: ReplyRequest) -> ReplyResponse:
    row_id = None
    sources, timings = [], {}
    started = time.monotonic()
    try:
        settings = get_settings()
        if not settings.WHATSAPP_REPLY_ENABLED:
            raise error("reply_not_enabled", 503)
        require_supported_extension(identity)
        actor = live_actor(db, identity)
        if sum(len(item.text) + len(item.quoted_text) for item in request.messages) > settings.WHATSAPP_REPLY_MAX_CONTEXT_CHARS:
            raise error("reply_context_too_large", 422)
        signature = _configuration_signature(settings, preset_signature(db, settings))
        bindings = parse_bindings(settings.WHATSAPP_REPLY_SOURCE_BINDINGS)
        try:
            memory_snapshot = reply_memory.load_for_generation(db, identity, request)
        except WhatsAppTranslationError as exc:
            if exc.error_code not in {"reply_memory_conflict", "reply_memory_not_found", "reply_memory_disabled"}:
                raise
            memory_snapshot = {"entries": [], "instance_id": None}
        prior_memory = memory_snapshot["entries"]
        record, owner = reserve_request(db, identity, request, settings)
        if not owner:
            return _cached_response(db, identity, record, signature)
        row_id = record.id
        deadline = started + min(180, settings.WHATSAPP_REPLY_TIMEOUT_SECONDS)
        phase = time.monotonic()
        conversation = request.model_dump(mode="json", exclude={"request_id", "conversation_epoch", "context_version", "draft_version", "memory_conversation_id", "memory_revision"})
        conversation["saved_observations"] = prior_memory
        terms = re.findall(r"[\w-]{2,40}", " ".join(m.text for m in request.messages[-40:]).casefold())
        queries = list(dict.fromkeys(terms))[-120:]
        all_text = " ".join(m.text for m in request.messages).casefold()
        queries += [alias for binding in bindings for alias in binding.aliases if alias.casefold() in all_text]
        sources, policies_available = retrieve_reply_sources(db, actor, bindings, queries)
        from app.whatsapp_translation.reply_direct import generate_direct
        conversation["glossary"] = glossary_for(db, direction="outgoing", text="\n".join(m.text for m in request.messages[-40:]), target_language=request.target_language if request.target_language != "auto" else request.fallback_language)
        def checked_call(*args):
            _check_current(db, identity, sources, signature)
            return _call(*args)
        output, plan, processing = generate_direct(db, identity, settings, request, conversation, sources, deadline, checked_call)
        memory_error = "reply_memory_update_failed" if plan.memory_parse_error else None
        try:
            memory_update = prior_memory if memory_error else reply_memory.build_update(plan, request, prior_memory)
        except WhatsAppTranslationError:
            memory_update = prior_memory
            memory_error = "reply_memory_update_failed"
        timings["generation"] = int((time.monotonic() - phase) * 1000)
        if not policies_available:
            output.risk_flags.append("knowledge_unavailable")
        if not request.context_scope.latest_visible or request.context_scope.truncated:
            output.risk_flags = list(dict.fromkeys([*output.risk_flags, "limited_context"]))
        if request.context_scope.omitted_media:
            output.risk_flags = list(dict.fromkeys([*output.risk_flags, "media_not_read"]))
        if policies_available and not any(source["purpose"] == "public_fact" for source in sources):
            output.risk_flags = list(dict.fromkeys([*output.risk_flags, "no_public_facts"]))
        # All selected evidence, including mandatory constraints, is reauthorized
        # even if the model chose not to cite it. Cached results get the same check.
        _check_current(db, identity, sources, signature)
        _remaining(deadline)
        try:
            reply_memory.recheck_revision(db, identity, request, memory_snapshot["instance_id"])
        except WhatsAppTranslationError:
            memory_error = "reply_memory_conflict"
        response = ReplyResponse(
            **output.model_dump(), request_id=request.request_id, conversation_epoch=request.conversation_epoch,
            context_version=request.context_version, draft_version=request.draft_version,
            sources=[ReplySource(**{key: source[key] for key in ReplySource.model_fields}) for source in sources],
            memory_error=memory_error, context_processing=processing,
            action=plan.action, memory_conversation_id=request.memory_conversation_id,
            memory_instance_id=memory_snapshot["instance_id"],
            memory_revision=request.memory_revision, memory_update=memory_update,
            handoff=reply_memory.handoff_summary(memory_update, plan),
            materials=[{"document_id": source["document_id"], "revision_id": source["revision_id"],
                        "title": source["title"], "text": source["text"], "applicability": source.get("applicability", "")}
                       for source in sources if source["purpose"] == "public_fact" and source.get("shareable_text")],
        )
        timings["total"] = int((time.monotonic() - started) * 1000)
        finish_request(db, row_id, status=output.status, sources=sources, timings=timings)
        reply_cache.put(row_id, (response.model_copy(deep=True), sources, signature))
        return response
    except WhatsAppTranslationError as exc:
        if row_id is not None:
            _record_error(db, row_id, exc.error_code, timings)
        raise
    except (TimeoutError, httpx.TimeoutException):
        if row_id is not None:
            _record_error(db, row_id, "reply_timeout", timings)
        raise error("reply_timeout", 503) from None
    except Exception as exc:
        # Never log exception text, traceback, request body, query or raw output.
        logger.warning("reply failed error_type=%s", type(exc).__name__)
        print(f"[WhatsApp reply] failed error_type={type(exc).__name__}", flush=True)
        if row_id is not None:
            _record_error(db, row_id, "reply_unavailable", timings)
        raise error("reply_unavailable", 503) from None


def _record_error(db, row_id, code, timings):
    try:
        finish_request(db, row_id, status="failed", error_code=code, timings=timings)
    except Exception as exc:
        db.rollback()
        logger.warning("reply metadata update failed error_type=%s", type(exc).__name__)
        print(f"[WhatsApp reply] metadata update failed error_type={type(exc).__name__}", flush=True)
