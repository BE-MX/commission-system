"""Authenticated user APIs for governed Agent tasks."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent_runtime import artifact_service, evaluation_service, presenters, service
from app.agent_runtime.contracts import RunStatus, TERMINAL_RUN_STATUSES
from app.agent_runtime.errors import AgentRuntimeError, RuntimeDisabledError
from app.agent_runtime.schemas import ArtifactDecisionInput, FeedbackInput, RunCreate, SessionCreate
from app.auth.dependencies import require_any_permission
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.response import ok, page_result


router = APIRouter()
READ_PERMISSIONS = ("agent_runtime:read", "agent_runtime:write", "agent_runtime:admin")
WRITE_PERMISSIONS = ("agent_runtime:write", "agent_runtime:admin")
ADMIN_PERMISSIONS = ("agent_runtime:admin",)


def _user_id(payload: dict) -> int:
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Token格式错误") from None
    if user_id <= 0:
        raise HTTPException(status_code=401, detail="Token格式错误")
    return user_id


def _permissions(payload: dict) -> set[str]:
    return {str(item) for item in payload.get("permissions", [])}


def _can_read_all(payload: dict) -> bool:
    return "super_admin" in payload.get("roles", []) or "agent_runtime:read_all" in _permissions(payload)


def _is_admin(payload: dict) -> bool:
    return "super_admin" in payload.get("roles", []) or "agent_runtime:admin" in _permissions(payload)


def _can_manage_all(payload: dict) -> bool:
    return _is_admin(payload)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AgentRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_enabled() -> None:
    if not get_settings().AGENT_RUNTIME_ENABLED:
        raise RuntimeDisabledError("Agent Runtime 尚未启用")


@router.get("/config")
def get_agent_runtime_config(
    _current_user: dict = Depends(require_any_permission(*READ_PERMISSIONS)),
):
    settings = get_settings()
    return ok({
        "enabled": settings.AGENT_RUNTIME_ENABLED,
        "dsh_enabled": settings.AGENT_RUNTIME_DSH_ENABLED,
        "max_active_per_user": settings.AGENT_RUNTIME_MAX_ACTIVE_PER_USER,
        "profiles": {
            "customer_order_copilot": settings.AGENT_RUNTIME_COPILOT_ENABLED,
            "repurchase_risk_analyst": settings.AGENT_RUNTIME_REPURCHASE_ENABLED,
            "sales_discovery_shadow": settings.AGENT_RUNTIME_SALES_SHADOW_ENABLED,
        },
        "web_search_enabled": settings.AGENT_RUNTIME_WEB_SEARCH_ENABLED,
    })


@router.get("/profiles")
def get_profiles(
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_any_permission(*READ_PERMISSIONS)),
):
    return ok([presenters.profile_view(row) for row in service.list_profiles(db)])


@router.post("/sessions")
def create_agent_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    _call(_require_enabled)
    row = _call(service.create_session, db, payload.model_dump(), user_id=_user_id(current_user))
    return ok(presenters.session_view(row), "Agent 会话已创建")


@router.get("/sessions")
def get_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = _call(
        service.list_sessions,
        db,
        user_id=_user_id(current_user),
        can_read_all=_can_read_all(current_user),
        page=page,
        page_size=page_size,
    )
    return ok(page_result([presenters.session_view(row) for row in rows], total, page, page_size))


@router.get("/sessions/{session_id}")
def get_agent_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*READ_PERMISSIONS)),
):
    row = _call(
        service.get_session,
        db,
        session_id,
        user_id=_user_id(current_user),
        can_read_all=_can_read_all(current_user),
    )
    return ok(presenters.session_view(row))


@router.post("/sessions/{session_id}/runs", status_code=202)
def create_agent_run(
    session_id: int,
    payload: RunCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    _call(_require_enabled)
    row = _call(
        service.create_run,
        db,
        session_id,
        payload.model_dump(),
        user_id=_user_id(current_user),
        permissions=list(_permissions(current_user)),
        roles=list(current_user.get("roles", [])),
    )
    return ok(presenters.run_view(row), "Agent 任务已创建", 202)


@router.get("/runs/{run_id}")
def get_agent_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*READ_PERMISSIONS)),
):
    user_id = _user_id(current_user)
    can_read_all = _can_read_all(current_user)
    row = _call(service.get_run, db, run_id, user_id=user_id, can_read_all=can_read_all)
    artifacts = _call(service.list_artifacts, db, run_id, user_id=user_id, can_read_all=can_read_all)
    return ok({
        "run": presenters.run_view(row),
        "artifacts": [presenters.artifact_view(item) for item in artifacts],
    })


@router.post("/runs/{run_id}/cancel")
def cancel_agent_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    row = _call(
        service.cancel_run,
        db,
        run_id,
        user_id=_user_id(current_user),
        can_read_all=_can_manage_all(current_user),
    )
    return ok(presenters.run_view(row), "取消请求已记录")


@router.get("/runs/{run_id}/events")
def get_agent_events(
    run_id: int,
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*READ_PERMISSIONS)),
):
    include_admin = _is_admin(current_user)
    rows = _call(
        service.list_events,
        db,
        run_id,
        user_id=_user_id(current_user),
        can_read_all=_can_read_all(current_user),
        include_admin=include_admin,
        after_sequence=after_sequence,
        limit=limit,
    )
    return ok([presenters.event_view(row, include_admin=include_admin) for row in rows])


@router.get("/runs/{run_id}/stream")
def stream_agent_events(
    run_id: int,
    after_sequence: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*READ_PERMISSIONS)),
):
    user_id = _user_id(current_user)
    can_read_all = _can_read_all(current_user)
    include_admin = _is_admin(current_user)
    _call(service.get_run, db, run_id, user_id=user_id, can_read_all=can_read_all)

    async def generate():
        cursor = after_sequence
        idle_cycles = 0
        while idle_cycles < 150:
            with SessionLocal() as stream_db:
                rows = service.list_events(
                    stream_db,
                    run_id,
                    user_id=user_id,
                    can_read_all=can_read_all,
                    include_admin=include_admin,
                    after_sequence=cursor,
                    limit=200,
                )
                run = service.get_run(stream_db, run_id, user_id=user_id, can_read_all=can_read_all)
                for row in rows:
                    cursor = row.sequence_no
                    body = json.dumps(presenters.event_view(row, include_admin=include_admin), ensure_ascii=False)
                    yield f"id: {cursor}\nevent: {row.event_type}\ndata: {body}\n\n"
                terminal = RunStatus(run.status) in TERMINAL_RUN_STATUSES
            if rows:
                idle_cycles = 0
            else:
                idle_cycles += 1
                yield ": keep-alive\n\n"
            if terminal and not rows:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks")
def get_agent_tasks(
    status: str | None = Query(None, max_length=24),
    runtime: str | None = Query(None, max_length=32),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*READ_PERMISSIONS)),
):
    rows, total = _call(
        service.list_runs,
        db,
        user_id=_user_id(current_user),
        can_read_all=_can_read_all(current_user),
        status=status,
        runtime=runtime,
        page=page,
        page_size=page_size,
    )
    return ok(page_result([presenters.run_view(row) for row in rows], total, page, page_size))


@router.get("/evaluations/readiness")
def get_agent_evaluation_readiness(
    db: Session = Depends(get_db),
    _current_user: dict = Depends(require_any_permission(*ADMIN_PERMISSIONS)),
):
    """Return conservative 30/200/50 business-validation gates for gray release."""
    return ok(evaluation_service.readiness_report(db))


@router.post("/artifacts/{artifact_id}/accept")
def accept_agent_artifact(
    artifact_id: int,
    payload: ArtifactDecisionInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    row = _call(
        artifact_service.decide_artifact,
        db,
        artifact_id,
        user_id=_user_id(current_user),
        decision="accepted",
        note=payload.note,
        can_read_all=_can_manage_all(current_user),
    )
    return ok(presenters.artifact_view(row), "成果已接受")


@router.post("/artifacts/{artifact_id}/reject")
def reject_agent_artifact(
    artifact_id: int,
    payload: ArtifactDecisionInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    row = _call(
        artifact_service.decide_artifact,
        db,
        artifact_id,
        user_id=_user_id(current_user),
        decision="rejected",
        note=payload.note,
        can_read_all=_can_manage_all(current_user),
    )
    return ok(presenters.artifact_view(row), "成果已拒绝")


@router.post("/runs/{run_id}/feedback")
def submit_agent_feedback(
    run_id: int,
    payload: FeedbackInput,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_any_permission(*WRITE_PERMISSIONS)),
):
    row = _call(
        service.add_feedback,
        db,
        run_id,
        user_id=_user_id(current_user),
        can_read_all=_can_manage_all(current_user),
        rating=payload.rating,
        note=payload.note,
    )
    return ok(presenters.run_view(row), "反馈已记录")
