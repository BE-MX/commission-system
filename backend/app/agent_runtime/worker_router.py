"""Machine-only APIs used by DSH and other Agent workers."""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.agent_runtime import presenters, worker_service
from app.agent_runtime.dependencies import require_agent_worker
from app.agent_runtime.errors import AgentRuntimeError
from app.agent_runtime.schemas import (
    WorkerClaimInput,
    WorkerCompleteInput,
    WorkerEventBatch,
    WorkerFailInput,
    WorkerHeartbeatInput,
)
from app.core.database import get_db
from app.core.response import ok


router = APIRouter()


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AgentRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_matching_worker(authenticated_worker: str, payload_worker: str) -> None:
    if authenticated_worker != payload_worker:
        raise HTTPException(status_code=403, detail="请求 Worker 与机器凭证不匹配")


@router.post("/runs/claim")
def claim_agent_run(
    payload: WorkerClaimInput,
    db: Session = Depends(get_db),
    worker_id: str = Depends(require_agent_worker),
):
    """Machine-only: atomically claim one compatible Run with a short lease."""
    _require_matching_worker(worker_id, payload.worker_id)
    data = _call(worker_service.claim_run, db, worker_id=worker_id, runtimes=payload.runtimes)
    return ok(data, "暂无可领取任务" if data is None else "任务已领取")


@router.post("/runs/{run_id}/heartbeat")
def heartbeat_agent_run(
    run_id: int,
    payload: WorkerHeartbeatInput,
    db: Session = Depends(get_db),
    worker_id: str = Depends(require_agent_worker),
):
    """Machine-only: extend the lease after verifying both machine and lease credentials."""
    _require_matching_worker(worker_id, payload.worker_id)
    row = _call(
        worker_service.heartbeat,
        db,
        run_id,
        worker_id=worker_id,
        lease_token=payload.lease_token,
        runtime_run_id=payload.runtime_run_id,
        steps_used=payload.steps_used,
    )
    return ok({
        "run_id": row.id,
        "lease_expires_at": row.lease_expires_at.isoformat(),
        "cancel_requested": bool(row.cancel_requested),
    })


@router.get("/runs/{run_id}/context")
def get_agent_run_context(
    run_id: int,
    x_agent_lease_token: str = Header(..., min_length=32, max_length=128),
    db: Session = Depends(get_db),
    worker_id: str = Depends(require_agent_worker),
):
    """Machine-only: return the frozen input and immutable Profile for the leased Run."""
    data = _call(
        worker_service.get_context,
        db,
        run_id,
        worker_id=worker_id,
        lease_token=x_agent_lease_token,
    )
    return ok(data)


@router.post("/runs/{run_id}/events")
def append_agent_events(
    run_id: int,
    payload: WorkerEventBatch,
    db: Session = Depends(get_db),
    worker_id: str = Depends(require_agent_worker),
):
    """Machine-only: append a contiguous, idempotent batch of normalized runtime events."""
    _require_matching_worker(worker_id, payload.worker_id)
    row, next_seq = _call(
        worker_service.append_worker_events,
        db,
        run_id,
        worker_id=worker_id,
        lease_token=payload.lease_token,
        events=payload.events,
    )
    return ok({"run": presenters.run_view(row), "next_sequence_no": next_seq})


@router.post("/runs/{run_id}/complete")
def complete_agent_run(
    run_id: int,
    payload: WorkerCompleteInput,
    db: Session = Depends(get_db),
    worker_id: str = Depends(require_agent_worker),
):
    """Machine-only: validate artifacts and commit the terminal completed state."""
    _require_matching_worker(worker_id, payload.worker_id)
    row, artifacts = _call(
        worker_service.complete_run,
        db,
        run_id,
        worker_id=worker_id,
        lease_token=payload.lease_token,
        runtime_run_id=payload.runtime_run_id,
        artifacts=payload.artifacts,
        steps_used=payload.steps_used,
        prompt_tokens=payload.prompt_tokens,
        completion_tokens=payload.completion_tokens,
        cost_usd=payload.cost_usd,
    )
    return ok({
        "run": presenters.run_view(row),
        "artifacts": [presenters.artifact_view(item) for item in artifacts],
    })


@router.post("/runs/{run_id}/fail")
def fail_agent_run(
    run_id: int,
    payload: WorkerFailInput,
    db: Session = Depends(get_db),
    worker_id: str = Depends(require_agent_worker),
):
    """Machine-only: submit a sanitized failure or ambiguous execution result."""
    _require_matching_worker(worker_id, payload.worker_id)
    row = _call(
        worker_service.fail_run,
        db,
        run_id,
        worker_id=worker_id,
        lease_token=payload.lease_token,
        error_code=payload.error_code,
        error_message=payload.error_message,
        ambiguous=payload.ambiguous,
    )
    return ok(presenters.run_view(row))
