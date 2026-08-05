"""Helpers for storing bounded AI request/response snapshots."""

import copy
import json
import re
from urllib.parse import urlsplit, urlunsplit

MAX_RESPONSE_SNAPSHOT_CHARS = 60000
_SENSITIVE_KEYS = {"authorization", "api_key", "access_token", "token"}
_BASE64_LIKE_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}\Z")


def _is_long_base64_like(value: str) -> bool:
    return (
        len(value) >= 256
        and len(value) % 4 != 1
        and _BASE64_LIKE_RE.fullmatch(value) is not None
    )


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[omitted unsafe URL]"
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _redact_snapshot_value(value):
    if isinstance(value, str):
        if value.startswith("data:image/"):
            return f"[omitted data image, {len(value)} chars]"
        if _is_long_base64_like(value):
            return f"[omitted base64-like value, {len(value)} chars]"
        return value
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _SENSITIVE_KEYS or normalized_key.endswith("_token"):
                redacted[key] = "[redacted]"
            elif key == "b64_json" and isinstance(item, str):
                redacted[key] = f"[omitted base64 image, {len(item)} chars]"
            elif isinstance(item, str) and item.lower().startswith(("http://", "https://")):
                redacted[key] = _safe_url(item)
            else:
                redacted[key] = _redact_snapshot_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_snapshot_value(item) for item in value]
    return value


def serialize_response_snapshot(result: dict) -> str:
    snapshot = json.dumps(_redact_snapshot_value(copy.deepcopy(result)), ensure_ascii=False)
    if len(snapshot) <= MAX_RESPONSE_SNAPSHOT_CHARS:
        return snapshot
    return (
        snapshot[:2000]
        + f"\n... [truncated response snapshot, {len(snapshot)} chars] ...\n"
        + snapshot[-500:]
    )
