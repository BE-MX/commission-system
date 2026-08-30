"""Pure response, budget and signed-cursor contract for customer Agent tools."""

from __future__ import annotations

from datetime import date, datetime
import base64
import hashlib
import hmac
import json
from typing import Any

from app.core.config import get_settings


SCHEMA_VERSION = "customer_agent_tool_v1"
MAX_LIST_ITEMS = 50
MAX_NESTED_ITEMS = 100
MAX_STRING_CHARS = 2_000
MAX_PROFILE_BYTES = 32 * 1024
MAX_SECTION_BYTES = 8 * 1024
MAX_LIST_BYTES = 64 * 1024
MAX_SOURCE_BYTES = 16 * 1024
MAX_SOURCE_CHARS = 12_000
MAX_CURSOR_ROWS = 10_000
PROFILE_SECTIONS = (
    "identity", "business_profile", "ownership", "key_contacts", "current_needs",
    "commercial_summary", "preferences", "behavior_patterns", "open_opportunities",
    "risks", "recommended_actions", "recent_changes", "data_quality", "open_questions",
)


class CustomerAgentAccessError(ValueError):
    """Stable, non-disclosing consumer-tool rejection."""


def deny() -> None:
    raise CustomerAgentAccessError("CUSTOMER_NOT_FOUND_OR_FORBIDDEN")


def effective_permissions(user: dict) -> list[str]:
    permissions = set(user.get("permissions") or [])
    run_scope = user.get("_agent_run") or {}
    if "permissions_at_start" in run_scope:
        permissions &= set(run_scope.get("permissions_at_start") or [])
    return sorted(permissions)


def _cursor_key() -> bytes:
    settings = get_settings()
    value = settings.AGENT_RUNTIME_RUN_TOKEN_SECRET or settings.JWT_SECRET_KEY
    return str(value).encode("utf-8")


def _cursor_scope(
    *, user: dict, customer_id: int | None, filters: dict, profile_version: int | None,
) -> dict:
    run = user.get("_agent_run") or {}
    return {
        "run_id": run.get("run_id"), "customer_id": customer_id,
        "filters": filters, "profile_version": profile_version,
        "permissions": effective_permissions(user),
    }


def encode_cursor(
    *, user: dict, customer_id: int | None, filters: dict,
    profile_version: int | None, position: int,
) -> str:
    payload = {
        **_cursor_scope(
            user=user, customer_id=customer_id, filters=filters,
            profile_version=profile_version,
        ),
        "position": position,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    signature = hmac.new(_cursor_key(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + signature).decode().rstrip("=")


def decode_cursor(
    cursor: str, *, user: dict, customer_id: int | None,
    filters: dict, profile_version: int | None,
) -> int:
    try:
        packed = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        raw, supplied = packed[:-32], packed[-32:]
        expected_signature = hmac.new(_cursor_key(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected_signature):
            deny()
        payload = json.loads(raw)
    except CustomerAgentAccessError:
        raise
    except (ValueError, TypeError, json.JSONDecodeError):
        deny()
    expected = _cursor_scope(
        user=user, customer_id=customer_id, filters=filters,
        profile_version=profile_version,
    )
    if any(payload.get(key) != value for key, value in expected.items()):
        deny()
    position = payload.get("position")
    if not isinstance(position, int) or position < 0 or position > MAX_CURSOR_ROWS:
        deny()
    return position


def serialize_envelope(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def clip(value: Any, max_chars: int = MAX_STRING_CHARS) -> tuple[Any, bool]:
    if isinstance(value, str):
        return value[:max_chars], len(value) > max_chars
    if isinstance(value, list):
        result, cut = [], False
        for item in value[:MAX_NESTED_ITEMS]:
            clipped, changed = clip(item, max_chars)
            result.append(clipped)
            cut |= changed
        return result, cut or len(value) > MAX_NESTED_ITEMS
    if isinstance(value, dict):
        result, cut = {}, False
        for key in sorted(value):
            clipped, changed = clip(value[key], max_chars)
            result[str(key)] = clipped
            cut |= changed
        return result, cut
    return value, False


def fit(value: dict, *, max_bytes: int) -> dict:
    if len(serialize_envelope(value)) <= max_bytes:
        return value
    value["truncated"] = True
    value["truncation_reason"] = "output_budget"
    items = value.get("items")
    if isinstance(items, list):
        while items and len(serialize_envelope(value)) > max_bytes:
            items.pop()
        value["has_more"] = True
    sections = value.get("sections")
    if isinstance(sections, dict):
        for key in reversed(list(sections)):
            if len(serialize_envelope(value)) <= max_bytes:
                break
            sections.pop(key)
    refs = value.get("evidence_refs")
    if isinstance(refs, list):
        while refs and len(serialize_envelope(value)) > max_bytes:
            refs.pop()
    return value


def envelope(
    *, profile_version: int | None, data_as_of: datetime | date | None,
    items: list | None = None, evidence_refs: list | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "profile_version": profile_version,
        "data_as_of": data_as_of, "items": items or [], "has_more": False,
        "cursor": None, "truncated": False, "truncation_reason": None,
        "redactions": [], "evidence_refs": evidence_refs or [],
    }


def page(
    rows: list, *, user: dict, customer_id: int | None, filters: dict,
    profile_version: int | None, cursor: str | None, limit: int,
) -> tuple[list, bool, str | None]:
    capped = min(max(int(limit), 1), MAX_LIST_ITEMS)
    position = decode_cursor(
        cursor, user=user, customer_id=customer_id, filters=filters,
        profile_version=profile_version,
    ) if cursor else 0
    selected = rows[position: position + capped]
    has_more = position + len(selected) < len(rows)
    next_cursor = encode_cursor(
        user=user, customer_id=customer_id, filters=filters,
        profile_version=profile_version, position=position + len(selected),
    ) if has_more else None
    return selected, has_more, next_cursor
