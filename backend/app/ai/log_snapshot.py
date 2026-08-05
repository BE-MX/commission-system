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
_HTTP_SCHEME_RE = re.compile(r"https?://", re.IGNORECASE)
_URL_STOP_CHARS = frozenset("<>{}\"'`")
_URL_TRAILING_PUNCTUATION = frozenset(".,;!?，。；！？")


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
    return _sanitize_embedded_urls(value)


def _split_url_boundary(candidate: str) -> tuple[str, str]:
    end = len(candidate)
    while end and candidate[end - 1] in _URL_TRAILING_PUNCTUATION:
        end -= 1
    excess_closers = {
        ")": candidate.count(")", 0, end) - candidate.count("(", 0, end),
        "]": candidate.count("]", 0, end) - candidate.count("[", 0, end),
    }
    while end and excess_closers.get(candidate[end - 1], 0) > 0:
        excess_closers[candidate[end - 1]] -= 1
        end -= 1
    return candidate[:end], candidate[end:]


def _sanitize_embedded_urls(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _HTTP_SCHEME_RE.finditer(value):
        start = match.start()
        if start < cursor:
            continue
        end = match.end()
        while end < len(value) and not value[end].isspace() and value[end] not in _URL_STOP_CHARS:
            end += 1
        candidate, suffix = _split_url_boundary(value[start:end])
        parts.append(value[cursor:start])
        parts.append(_safe_url(candidate))
        parts.append(suffix)
        cursor = end
    parts.append(value[cursor:])
    return "".join(parts)


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
