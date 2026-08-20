"""Append-only Agent event ledger with server-side redaction and idempotency."""

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import EVENT_SCHEMA_VERSION, STANDARD_EVENT_TYPES
from app.agent_runtime.errors import ConflictError
from app.agent_runtime.models import AgentEvent, AgentRun, AgentSession


_SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "lease_token",
    "run_token",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SECRET_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def next_sequence(db: Session, run_id: int) -> int:
    latest = db.query(func.max(AgentEvent.sequence_no)).filter(AgentEvent.run_id == run_id).scalar()
    return int(latest or 0) + 1


def append_event(
    db: Session,
    run: AgentRun,
    *,
    event_id: str,
    event_type: str,
    actor_type: str,
    payload: dict,
    visibility: str = "user",
    sequence_no: int | None = None,
    schema_version: int = EVENT_SCHEMA_VERSION,
    raw_payload_cipher: str | None = None,
    source_event_ids: list[str] | None = None,
    created_at: datetime | None = None,
) -> AgentEvent:
    if event_type not in STANDARD_EVENT_TYPES:
        raise ValueError(f"未知 Agent 事件类型: {event_type}")
    clean_payload = redact(payload)
    digest = content_hash(clean_payload)
    existing = db.query(AgentEvent).filter(
        AgentEvent.run_id == run.id,
        AgentEvent.event_id == event_id,
    ).one_or_none()
    if existing is not None:
        if (
            existing.event_type != event_type
            or existing.payload_sha256 != digest
            or (sequence_no is not None and existing.sequence_no != sequence_no)
        ):
            raise ConflictError("相同 event_id 的事件内容不一致")
        return existing

    expected = next_sequence(db, run.id)
    actual = expected if sequence_no is None else sequence_no
    if actual != expected:
        raise ConflictError(f"事件序号不连续，期望 {expected}，收到 {actual}")

    event = AgentEvent(
        run_id=run.id,
        session_id=run.session_id,
        sequence_no=actual,
        event_id=event_id,
        event_type=event_type,
        schema_version=schema_version,
        actor_type=actor_type,
        visibility=visibility,
        payload_json=clean_payload,
        raw_payload_cipher=raw_payload_cipher,
        source_event_ids=source_event_ids or [],
        payload_sha256=digest,
        created_at=created_at or datetime.utcnow(),
    )
    db.add(event)
    session = db.query(AgentSession).filter(AgentSession.id == run.session_id).one()
    session.last_event_seq = int(session.last_event_seq or 0) + 1
    # SessionLocal 使用 autoflush=False；立即 flush 才能保证同一事务内下一条事件
    # 看到刚分配的序号，避免批量追加时重复占用 sequence_no。
    db.flush()
    return event
