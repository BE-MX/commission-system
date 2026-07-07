"""Helpers for storing bounded AI request/response snapshots."""

import copy
import json

MAX_RESPONSE_SNAPSHOT_CHARS = 60000


def _redact_snapshot_value(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key == "b64_json" and isinstance(item, str):
                redacted[key] = f"[omitted base64 image, {len(item)} chars]"
            elif isinstance(item, str) and item.startswith("data:image/"):
                redacted[key] = f"[omitted data image, {len(item)} chars]"
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
