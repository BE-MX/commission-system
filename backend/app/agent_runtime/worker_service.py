"""Lease-protected Agent worker operations."""

from datetime import datetime, timedelta
import hashlib
import secrets

from sqlalchemy.orm import Session

from app.agent_runtime import artifact_service
from app.agent_runtime.contracts import RunStatus
from app.agent_runtime.errors import ConflictError, LeaseError, NotFoundError
from app.agent_runtime.event_service import append_event, next_sequence
from app.agent_runtime.models import AgentProfile, AgentRun, AgentSession
from app.agent_runtime.schemas import ArtifactInput, WorkerEventInput
from app.agent_runtime.state_machine import require_transition
from app.agent_runtime.token_service import create_run_token
from app.core.config import get_settings
from app.ai.models import AiPreset


def _now() -> datetime:
    return datetime.utcnow()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def reconcile_expired_runs(db: Session, *, limit: int = 100) -> int:
    now = _now()
    rows = db.query(AgentRun).filter(
        AgentRun.status.in_([RunStatus.LEASED.value, RunStatus.RUNNING.value, RunStatus.WAITING_INPUT.value]),
        AgentRun.lease_expires_at.isnot(None),
        AgentRun.lease_expires_at <= now,
    ).order_by(AgentRun.lease_expires_at).with_for_update(skip_locked=True).limit(limit).all()
    for row in rows:
        previous_worker = row.claimed_by
        if row.status == RunStatus.LEASED.value and row.attempt_no < row.max_attempts:
            require_transition(row.status, RunStatus.QUEUED)
            row.status = RunStatus.QUEUED.value
            row.claimed_by = None
            row.lease_token_hash = None
            row.lease_expires_at = None
            append_event(
                db, row,
                event_id=f"run-{row.id}-requeued-{row.attempt_no}",
                event_type="run.requeued",
                actor_type="control_plane",
                payload={"expired_worker": previous_worker, "attempt_no": row.attempt_no},
                visibility="admin",
            )
        else:
            require_transition(row.status, RunStatus.AMBIGUOUS)
            row.status = RunStatus.AMBIGUOUS.value
            row.completed_at = now
            row.error_code = "WORKER_LEASE_EXPIRED"
            row.error_message = "Worker 在执行期间失联，任务结果不确定，禁止自动重试"
            row.lease_token_hash = None
            row.lease_expires_at = None
            append_event(
                db, row,
                event_id=f"run-{row.id}-ambiguous-lease-{row.attempt_no}",
                event_type="run.ambiguous",
                actor_type="control_plane",
                payload={"expired_worker": previous_worker, "attempt_no": row.attempt_no},
                visibility="admin",
            )
    if rows:
        db.flush()
    return len(rows)


def claim_run(db: Session, *, worker_id: str, runtimes: list[str]) -> dict | None:
    if not get_settings().AGENT_RUNTIME_ENABLED:
        return None
    reconcile_expired_runs(db)
    row = db.query(AgentRun).filter(
        AgentRun.status == RunStatus.QUEUED.value,
        AgentRun.source_runtime.in_(runtimes),
        AgentRun.attempt_no < AgentRun.max_attempts,
    ).order_by(AgentRun.created_at, AgentRun.id).with_for_update(skip_locked=True).first()
    if row is None:
        db.commit()
        return None
    if row.cancel_requested:
        require_transition(row.status, RunStatus.CANCELLED)
        row.status = RunStatus.CANCELLED.value
        row.completed_at = _now()
        append_event(
            db, row,
            event_id=f"run-{row.id}-cancelled-on-claim",
            event_type="run.cancelled",
            actor_type="control_plane",
            payload={"reason": "cancel_requested"},
        )
        db.commit()
        return None

    profile = db.query(AgentProfile).filter(AgentProfile.id == row.profile_id).one()
    if profile.status != "active":
        require_transition(row.status, RunStatus.FAILED)
        row.status = RunStatus.FAILED.value
        row.completed_at = _now()
        row.error_code = "PROFILE_DISABLED"
        row.error_message = "Agent Profile 已停用"
        append_event(
            db, row,
            event_id=f"run-{row.id}-profile-disabled",
            event_type="run.failed",
            actor_type="control_plane",
            payload={"error_code": row.error_code},
        )
        db.commit()
        return None

    settings = get_settings()
    if row.source_runtime == "dsh" and not settings.AGENT_RUNTIME_DSH_ENABLED:
        db.commit()
        return None
    lease_token = secrets.token_urlsafe(32)
    require_transition(row.status, RunStatus.LEASED)
    row.status = RunStatus.LEASED.value
    row.claimed_by = worker_id
    row.lease_token_hash = _hash_token(lease_token)
    row.lease_expires_at = _now() + timedelta(seconds=settings.AGENT_RUNTIME_WORKER_LEASE_SECONDS)
    row.attempt_no += 1
    append_event(
        db, row,
        event_id=f"run-{row.id}-claimed-{row.attempt_no}",
        event_type="run.claimed",
        actor_type="control_plane",
        payload={"worker_id": worker_id, "attempt_no": row.attempt_no},
        visibility="admin",
    )
    run_token_ttl = max(
        settings.AGENT_RUNTIME_RUN_TIMEOUT_SECONDS,
        int((profile.limits_json or {}).get("timeout_seconds", 0)),
    ) + settings.AGENT_RUNTIME_WORKER_LEASE_SECONDS
    delegated_token = create_run_token(row, profile, ttl_seconds=run_token_ttl)
    db.commit()
    return {
        "run_id": row.id,
        "session_id": row.session_id,
        "profile_key": profile.profile_key,
        "profile_version": profile.version,
        "runtime": row.source_runtime,
        "mode": row.mode,
        "lease_token": lease_token,
        "lease_expires_at": row.lease_expires_at.isoformat(),
        "run_token": delegated_token,
        "next_sequence_no": next_sequence(db, row.id),
    }


def _leased_run(db: Session, run_id: int, *, worker_id: str, lease_token: str) -> AgentRun:
    row = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one_or_none()
    if row is None:
        raise NotFoundError("Agent 任务不存在")
    if row.status not in {RunStatus.LEASED.value, RunStatus.RUNNING.value, RunStatus.WAITING_INPUT.value}:
        raise LeaseError("Agent 任务不处于可提交状态")
    if row.claimed_by != worker_id:
        raise LeaseError("Agent Worker 与租约不匹配")
    if not lease_token or not secrets.compare_digest(row.lease_token_hash or "", _hash_token(lease_token)):
        raise LeaseError("Agent 租约令牌无效")
    if row.lease_expires_at is None or row.lease_expires_at <= _now():
        raise LeaseError("Agent 租约已经过期")
    return row


def heartbeat(
    db: Session,
    run_id: int,
    *,
    worker_id: str,
    lease_token: str,
    runtime_run_id: str | None,
    steps_used: int | None,
) -> AgentRun:
    row = _leased_run(db, run_id, worker_id=worker_id, lease_token=lease_token)
    if runtime_run_id:
        if row.runtime_run_id and row.runtime_run_id != runtime_run_id:
            raise ConflictError("Runtime Run ID 不能变更")
        row.runtime_run_id = runtime_run_id
    if steps_used is not None:
        if steps_used < row.steps_used:
            raise ConflictError("steps_used 不能回退")
        row.steps_used = steps_used
    row.lease_expires_at = _now() + timedelta(seconds=get_settings().AGENT_RUNTIME_WORKER_LEASE_SECONDS)
    db.commit()
    db.refresh(row)
    return row


def get_context(db: Session, run_id: int, *, worker_id: str, lease_token: str) -> dict:
    row = _leased_run(db, run_id, worker_id=worker_id, lease_token=lease_token)
    profile = db.query(AgentProfile).filter(AgentProfile.id == row.profile_id).one()
    session = db.query(AgentSession).filter(AgentSession.id == row.session_id).one()
    preset = db.query(AiPreset).filter(
        AiPreset.preset_name == profile.model_preset,
        AiPreset.deleted_at.is_(None),
        AiPreset.is_enabled.is_(True),
    ).one_or_none()
    if preset is None:
        raise ConflictError(f"Agent 模型预设 {profile.model_preset} 不存在或未启用")
    return {
        "run": {
            "id": row.id,
            "input": row.input_json or {},
            "business_ref_type": row.business_ref_type,
            "business_ref_id": row.business_ref_id,
            "context_snapshot": row.context_snapshot or {},
            "cancel_requested": bool(row.cancel_requested),
        },
        "session": {
            "id": session.id,
            "title": session.title,
            "context_type": session.context_type,
            "context_id": session.context_id,
            "runtime_session_id": session.runtime_session_id,
        },
        "profile": {
            "id": profile.id,
            "profile_key": profile.profile_key,
            "version": profile.version,
            "model_preset": profile.model_preset,
            "model": preset.model,
            "system_prompt": profile.system_prompt,
            "prompt_hash": profile.prompt_hash,
            "skill_manifest": profile.skill_manifest or [],
            "tool_allowlist": profile.tool_allowlist or [],
            "limits": profile.limits_json or {},
            "policy": profile.policy_json or {},
            "output_schema": profile.output_schema or {},
        },
        "next_sequence_no": next_sequence(db, row.id),
    }


def append_worker_events(
    db: Session,
    run_id: int,
    *,
    worker_id: str,
    lease_token: str,
    events: list[WorkerEventInput],
) -> tuple[AgentRun, int]:
    row = _leased_run(db, run_id, worker_id=worker_id, lease_token=lease_token)
    if row.cancel_requested:
        raise ConflictError("任务已请求取消，Worker 应停止执行并提交失败/取消")
    first_new = next((item for item in events if item.sequence_no >= next_sequence(db, row.id)), None)
    if row.status == RunStatus.LEASED.value:
        if first_new is None or first_new.event_type != "run.started":
            raise ConflictError("租约任务的第一个新事件必须是 run.started")
        require_transition(row.status, RunStatus.RUNNING)
        row.status = RunStatus.RUNNING.value
        row.started_at = row.started_at or _now()
    forbidden = {"run.created", "run.claimed", "run.requeued", "run.completed", "run.failed", "run.cancelled", "run.ambiguous"}
    for item in events:
        if item.event_type in forbidden:
            raise ConflictError(f"{item.event_type} 只能由方舟控制面写入")
        append_event(
            db, row,
            event_id=item.event_id,
            event_type=item.event_type,
            actor_type=item.actor_type,
            payload=item.payload,
            visibility=item.visibility,
            sequence_no=item.sequence_no,
            schema_version=item.schema_version,
            raw_payload_cipher=item.raw_payload_cipher,
            source_event_ids=item.source_event_ids,
            created_at=item.created_at,
        )
    db.commit()
    db.refresh(row)
    return row, next_sequence(db, row.id)


def complete_run(
    db: Session,
    run_id: int,
    *,
    worker_id: str,
    lease_token: str,
    runtime_run_id: str | None,
    artifacts: list[ArtifactInput],
    steps_used: int,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd,
) -> tuple[AgentRun, list]:
    row = _leased_run(db, run_id, worker_id=worker_id, lease_token=lease_token)
    if row.cancel_requested:
        require_transition(row.status, RunStatus.CANCELLED)
        row.status = RunStatus.CANCELLED.value
        row.completed_at = _now()
        append_event(
            db, row,
            event_id=f"run-{row.id}-cancelled-by-worker",
            event_type="run.cancelled",
            actor_type="control_plane",
            payload={"worker_id": worker_id, "reason": "cancel_requested"},
        )
        db.commit()
        return row, []
    if row.status not in {RunStatus.RUNNING.value, RunStatus.WAITING_INPUT.value}:
        raise ConflictError("Worker 必须先提交 run.started 才能完成任务")
    profile = db.query(AgentProfile).filter(AgentProfile.id == row.profile_id).one()
    if profile.output_schema and not artifacts:
        raise ConflictError("该 Agent Profile 必须提交至少一个成果")
    created = [
        artifact_service.create_artifact(
            db, row, profile,
            artifact_type=item.artifact_type,
            schema_version=item.schema_version,
            title=item.title,
            content=item.content,
            evidence=item.evidence,
        )
        for item in artifacts
    ]
    if runtime_run_id:
        if row.runtime_run_id and row.runtime_run_id != runtime_run_id:
            raise ConflictError("Runtime Run ID 不能变更")
        row.runtime_run_id = runtime_run_id
    limits = profile.limits_json or {}
    max_steps = min(
        int(limits.get("max_steps", get_settings().AGENT_RUNTIME_MAX_STEPS_PER_RUN)),
        get_settings().AGENT_RUNTIME_MAX_STEPS_PER_RUN,
    )
    if steps_used > max_steps:
        raise ConflictError("Agent 步骤数超过 Profile 限制")
    require_transition(row.status, RunStatus.COMPLETED)
    row.status = RunStatus.COMPLETED.value
    row.steps_used = steps_used
    # DSH uses Ark's model gateway, whose counters are authoritative.  max()
    # also keeps native/OpenClaw workers compatible when they report usage at
    # completion without going through that gateway.
    row.prompt_tokens = max(row.prompt_tokens, prompt_tokens)
    row.completion_tokens = max(row.completion_tokens, completion_tokens)
    row.cost_usd = cost_usd
    row.completed_at = _now()
    row.lease_token_hash = None
    row.lease_expires_at = None
    append_event(
        db, row,
        event_id=f"run-{row.id}-completed",
        event_type="run.completed",
        actor_type="control_plane",
        payload={
            "artifact_ids": [item.id for item in created],
            "steps_used": steps_used,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": str(cost_usd),
        },
    )
    db.commit()
    for item in created:
        db.refresh(item)
    db.refresh(row)
    return row, created


def fail_run(
    db: Session,
    run_id: int,
    *,
    worker_id: str,
    lease_token: str,
    error_code: str,
    error_message: str,
    ambiguous: bool,
) -> AgentRun:
    row = _leased_run(db, run_id, worker_id=worker_id, lease_token=lease_token)
    if row.cancel_requested:
        target = RunStatus.CANCELLED
        event_type = "run.cancelled"
    elif ambiguous:
        target = RunStatus.AMBIGUOUS
        event_type = "run.ambiguous"
    else:
        target = RunStatus.FAILED
        event_type = "run.failed"
    require_transition(row.status, target)
    row.status = target.value
    row.error_code = error_code
    row.error_message = error_message
    row.completed_at = _now()
    row.lease_token_hash = None
    row.lease_expires_at = None
    append_event(
        db, row,
        event_id=f"run-{row.id}-{target.value}-{row.attempt_no}",
        event_type=event_type,
        actor_type="control_plane",
        payload={"error_code": error_code, "error_message": error_message, "worker_id": worker_id},
        visibility="admin",
    )
    db.commit()
    db.refresh(row)
    return row
