"""Helpers for storing bounded AI request/response snapshots."""

import copy
import json
import re
from urllib.parse import urlsplit, urlunsplit

MAX_RESPONSE_SNAPSHOT_CHARS = 60000
_SENSITIVE_KEYS = {
    "authorization", "apikey", "accesstoken", "token", "clientsecret", "password",
}
_BASE64_LIKE_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}\Z")
_DATA_IMAGE_RE = re.compile(
    r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9_+/=-]+",
    re.IGNORECASE,
)
_HTTP_URL_RE = re.compile(r"https?://[^\s<>{}\[\]()\"']+", re.IGNORECASE)


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
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return value
    hostname = parsed.hostname
    safe_host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        return "[omitted unsafe URL]"
    if port is not None:
        safe_host = f"{safe_host}:{port}"
    return urlunsplit((parsed.scheme, safe_host, parsed.path, "", ""))


def _redact_string(value: str) -> str:
    if _is_long_base64_like(value):
        return f"[omitted base64-like value, {len(value)} chars]"

    def omit_data_image(match: re.Match) -> str:
        return f"[omitted data image, {len(match.group(0))} chars]"

    value = _DATA_IMAGE_RE.sub(omit_data_image, value)
    return _HTTP_URL_RE.sub(lambda match: _safe_url(match.group(0)), value)


def _redact_snapshot_value(value):
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized_key = re.sub(r"[_-]", "", str(key).lower())
            if normalized_key in _SENSITIVE_KEYS or normalized_key.endswith(
                ("authorization", "apikey", "token", "clientsecret", "password")
            ):
                redacted[key] = "[redacted]"
            elif key == "b64_json" and isinstance(item, str):
                redacted[key] = f"[omitted base64 image, {len(item)} chars]"
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
