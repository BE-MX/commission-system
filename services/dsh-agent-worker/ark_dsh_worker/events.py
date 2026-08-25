"""Loss-minimized DSH-to-Ark event normalization without prompt/result bodies."""

from __future__ import annotations

import hashlib
import json


def _walk_result(value, *, depth: int = 0):
    if depth > 8:
        return
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_result(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_result(child, depth=depth + 1)


def _ark_tool_envelope(content) -> dict | None:
    """Extract Ark's ``{ok, data|error}`` envelope without retaining content."""
    for candidate in _walk_result(content):
        parsed = candidate
        if isinstance(candidate, str):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict) and "ok" in parsed:
            return parsed
    return None


def _tool_call_id(message: dict):
    source = message.get("source") if isinstance(message.get("source"), dict) else {}
    if source.get("kind") == "tool" and source.get("callId"):
        return source["callId"]
    for item in _walk_result(message):
        if isinstance(item, dict) and item.get("toolCallId"):
            return item["toolCallId"]
    return None


class EventNormalizer:
    def __init__(self, run_id: int, next_sequence: int):
        self.run_id = run_id
        self.next_sequence = next_sequence
        self.steps = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._fallback_id = 0

    @staticmethod
    def _hash(value) -> str:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def normalize(self, notification) -> dict | None:
        method = getattr(notification, "method", None)
        payload = getattr(notification, "payload", None)
        if method != "session.event" or not isinstance(payload, dict):
            return None
        event = payload.get("event")
        if not isinstance(event, dict):
            return None
        event_type = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        dsh_seq = event.get("seq")
        self._fallback_id += 1
        source_id = f"dsh:{payload.get('sessionId')}:{dsh_seq if dsh_seq is not None else self._fallback_id}"

        actor = "runtime"
        visibility = "user"
        normalized_type = None
        normalized_payload: dict = {"dsh_event_type": event_type}
        if event_type == "step/start":
            self.steps += 1
            normalized_type = "model.requested"
            actor = "model"
            normalized_payload.update({"turn": data.get("turn"), "step": data.get("step")})
        elif event_type == "assistant/message":
            normalized_type = "model.responded"
            actor = "model"
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            prompt = int(usage.get("inputTokens") or usage.get("prompt_tokens") or 0)
            completion = int(usage.get("outputTokens") or usage.get("completion_tokens") or 0)
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            normalized_payload.update({
                "turn": data.get("turn"), "step": data.get("step"),
                "prompt_tokens": prompt, "completion_tokens": completion,
                "interrupted": bool(data.get("interrupted")),
            })
        elif event_type == "tool/call":
            normalized_type = "tool.requested"
            actor = "tool"
            arguments = data.get("arguments") or ""
            normalized_payload.update({
                "turn": data.get("turn"), "step": data.get("step"),
                "call_id": data.get("callId"), "tool_name": data.get("name"),
                "arguments_length": len(arguments), "arguments_sha256": self._hash(arguments),
            })
        elif event_type == "tool/result":
            error = data.get("error") if isinstance(data.get("error"), dict) else None
            result_message = data.get("message") if isinstance(data.get("message"), dict) else {}
            result_serialized = json.dumps(result_message, ensure_ascii=False, sort_keys=True, default=str)
            envelope = _ark_tool_envelope(result_message.get("content"))
            business_success = envelope is not None and envelope.get("ok") is True
            nested_error = any(
                isinstance(item, dict) and item.get("isError") is True
                for item in _walk_result(result_message)
            )
            normalized_type = "tool.succeeded" if not error and not nested_error and business_success else "tool.failed"
            error_code = error.get("code") if error else None
            if error_code is None and nested_error:
                error_code = "DSH_TOOL_ERROR"
            elif error_code is None and not business_success:
                error_code = "ARK_TOOL_ERROR" if envelope is not None else "INVALID_TOOL_RESULT"
            actor = "tool"
            normalized_payload.update({
                "turn": data.get("turn"), "step": data.get("step"),
                "call_id": _tool_call_id(result_message),
                "result_length": len(result_serialized),
                "result_sha256": self._hash(result_message),
                "error_code": error_code,
            })
        elif event_type == "turn/end":
            normalized_type = "plan.updated"
            reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
            normalized_payload.update({"turn": data.get("turn"), "phase": "turn_ended", "reason": reason.get("kind")})
        if normalized_type is None:
            return None
        result = {
            "sequence_no": self.next_sequence,
            "event_id": f"dsh-{self.run_id}-{self.next_sequence}",
            "event_type": normalized_type,
            "schema_version": 1,
            "actor_type": actor,
            "visibility": visibility,
            "payload": normalized_payload,
            "source_event_ids": [source_id[:128]],
        }
        self.next_sequence += 1
        return result
