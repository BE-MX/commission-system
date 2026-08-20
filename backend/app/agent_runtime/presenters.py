"""Stable public views for Agent Runtime ORM records."""

from app.agent_runtime.models import AgentArtifact, AgentEvent, AgentProfile, AgentRun, AgentSession


def _iso(value):
    return value.isoformat() if value is not None else None


def profile_view(row: AgentProfile) -> dict:
    return {
        "id": row.id,
        "profile_key": row.profile_key,
        "version": row.version,
        "name": row.name,
        "description": row.description,
        "runtime": row.runtime,
        "mode": row.mode,
        "tool_allowlist": row.tool_allowlist or [],
        "limits": row.limits_json or {},
        "status": row.status,
    }


def session_view(row: AgentSession) -> dict:
    return {
        "id": row.id,
        "owner_user_id": row.owner_user_id,
        "profile_id": row.profile_id,
        "title": row.title,
        "context_type": row.context_type,
        "context_id": row.context_id,
        "status": row.status,
        "summary": row.summary_json,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def run_view(row: AgentRun) -> dict:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "profile_id": row.profile_id,
        "owner_user_id": row.owner_user_id,
        "trigger_type": row.trigger_type,
        "source_runtime": row.source_runtime,
        "mode": row.mode,
        "business_ref_type": row.business_ref_type,
        "business_ref_id": row.business_ref_id,
        "input": row.input_json or {},
        "status": row.status,
        "cancel_requested": bool(row.cancel_requested),
        "attempt_no": row.attempt_no,
        "steps_used": row.steps_used,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": str(row.cost_usd or 0),
        "error_code": row.error_code,
        "error_message": row.error_message,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def event_view(row: AgentEvent, *, include_admin: bool = False) -> dict:
    data = {
        "id": row.id,
        "run_id": row.run_id,
        "sequence_no": row.sequence_no,
        "event_id": row.event_id,
        "event_type": row.event_type,
        "schema_version": row.schema_version,
        "actor_type": row.actor_type,
        "visibility": row.visibility,
        "payload": row.payload_json or {},
        "source_event_ids": row.source_event_ids or [],
        "created_at": _iso(row.created_at),
    }
    if include_admin:
        data["payload_sha256"] = row.payload_sha256
    return data


def artifact_view(row: AgentArtifact) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "artifact_type": row.artifact_type,
        "schema_version": row.schema_version,
        "title": row.title,
        "content": row.content_json or {},
        "evidence": row.evidence_json or [],
        "validation_status": row.validation_status,
        "validation_errors": row.validation_errors or [],
        "decision_status": row.decision_status,
        "decided_by": row.decided_by,
        "decided_at": _iso(row.decided_at),
        "feedback_note": row.feedback_note,
        "business_ref_type": row.business_ref_type,
        "business_ref_id": row.business_ref_id,
        "created_at": _iso(row.created_at),
    }

