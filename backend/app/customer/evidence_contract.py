"""Canonical hashes for evidence returned by customer Agent tools."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def fact_evidence_content_hash(*, fact_id: int, value: Any, fingerprint: str) -> str:
    payload = {"fact_id": fact_id, "value": value, "fingerprint": fingerprint}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


__all__ = ["fact_evidence_content_hash"]
