"""User-facing Agent session, run and task services."""

from datetime import datetime
from app.core.time import beijing_now

from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_runtime.contracts import ACTIVE_RUN_STATUSES, RunStatus
from app.agent_runtime.errors import ConflictError, ForbiddenError, NotFoundError
from app.agent_runtime.event_service import append_event, content_hash
from app.agent_runtime.models import AgentArtifact, AgentEvent, AgentProfile, AgentRun, AgentSession
from app.agent_runtime.state_machine import require_transition
from app.auth.models import ArkUser
from app.core.config import get_settings
from app.customer.models import CustomerAccount, CustomerAgentRunScope


def get_active_profile(db: Session, profile_key: str) -> AgentProfile:
    row = db.query(AgentProfile).filter(
        AgentProfile.profile_key == profile_key,
        AgentProfile.status == "active",
    ).order_by(desc(AgentProfile.version)).first()
    if row is None:
        raise NotFoundError("Agent Profile 不存在或未启用")
    return row


def list_profiles(db: Session) -> list[AgentProfile]:
    rows = db.query(AgentProfile).filter(AgentProfile.status == "active").order_by(
        AgentProfile.profile_key, desc(AgentProfile.version),
    ).all()
    latest: dict[str, AgentProfile] = {}
    for row in rows:
        latest.setdefault(row.profile_key, row)
    return list(latest.values())


def profile_feature_enabled(profile_key: str) -> bool:
    settings = get_settings()
    gates = {
        "customer_order_copilot": settings.AGENT_RUNTIME_COPILOT_ENABLED,
        "repurchase_risk_analyst": settings.AGENT_RUNTIME_REPURCHASE_ENABLED,
        "sales_discovery_shadow": (
            settings.AGENT_RUNTIME_SALES_SHADOW_ENABLED
            and settings.AGENT_RUNTIME_WEB_SEARCH_ENABLED
        ),
    }
    return bool(settings.AGENT_RUNTIME_ENABLED and gates.get(profile_key, False))


def create_session(
    db: Session, data: dict, *, user_id: int, system_initiated: bool = False,
    commit: bool = True,
) -> AgentSession:
    profile = get_active_profile(db, data["profile_key"])
    if not system_initiated and profile.mode != "interactive":
        raise ForbiddenError("定时与影子 Agent 只能由方舟服务端编排启动")
    if not profile_feature_enabled(profile.profile_key):
        raise ConflictError("该 Agent 业务场景尚未开启灰度")
    row = AgentSession(
        owner_user_id=user_id,
        profile_id=profile.id,
        title=data["title"].strip(),
        context_type=data.get("context_type"),
        context_id=data.get("context_id"),
        status="active",
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def _session_for_user(db: Session, session_id: int, user_id: int, can_read_all: bool) -> AgentSession:
    query = db.query(AgentSession).filter(AgentSession.id == session_id)
    if not can_read_all:
        query = query.filter(AgentSession.owner_user_id == user_id)
    row = query.one_or_none()
    if row is None:
        raise NotFoundError("Agent 会话不存在")
    return row


def get_session(db: Session, session_id: int, *, user_id: int, can_read_all: bool) -> AgentSession:
    return _session_for_user(db, session_id, user_id, can_read_all)


def list_sessions(
    db: Session, *, user_id: int, can_read_all: bool, page: int, page_size: int,
) -> tuple[list[AgentSession], int]:
    query = db.query(AgentSession)
    if not can_read_all:
        query = query.filter(AgentSession.owner_user_id == user_id)
    total = query.count()
    rows = query.order_by(desc(AgentSession.updated_at), desc(AgentSession.id)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return rows, total


def create_run(
    db: Session,
    session_id: int,
    data: dict,
    *,
    user_id: int,
    permissions: list[str],
    roles: list[str],
    system_initiated: bool = False,
    evaluation_initiated: bool = False,
) -> AgentRun:
    effective_permissions = set(permissions)
    if "super_admin" in set(roles):
        # Auth treats super_admin as a permission bypass. Materialize the one
        # delegated capability the Run Token must carry so downstream checks
        # stay explicit and the immutable snapshot remains self-contained.
        effective_permissions.add("agent_runtime:invoke")
    if "agent_runtime:invoke" not in effective_permissions:
        raise ForbiddenError("创建 Agent 任务需要 Agent 调用权限")
    run_input = data.get("input") or {}
    reserved_evaluation_fields = {"evaluation_suite", "evaluation_case_id"}
    if reserved_evaluation_fields & set(run_input) and not evaluation_initiated:
        raise ForbiddenError("标准评测标记只能由方舟评测流程生成")
    # Serialize all create decisions for this owner, then lock the session.
    # This closes both the per-user and per-session count-then-insert races on MySQL.
    if db.query(ArkUser).filter(ArkUser.id == user_id).with_for_update().one_or_none() is None:
        raise NotFoundError("Agent 任务所有者不存在")
    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.owner_user_id == user_id,
    ).with_for_update().one_or_none()
    if session is None:
        raise NotFoundError("Agent 会话不存在")
    if session.status != "active":
        raise ConflictError("归档会话不能创建新任务")
    profile = db.query(AgentProfile).filter(AgentProfile.id == session.profile_id).one()
    if profile.status != "active":
        raise ConflictError("该 Agent Profile 已停用")
    if not profile_feature_enabled(profile.profile_key):
        raise ConflictError("该 Agent 业务场景尚未开启灰度")
    if not system_initiated:
        if profile.mode != "interactive" or data.get("trigger_type", "user") != "user":
            raise ForbiddenError("用户入口只能启动交互式 Agent 任务")
        if profile.profile_key == "customer_order_copilot":
            ref_id = str(data.get("business_ref_id") or "")
            input_customer_id = str(run_input.get("customer_id") or "")
            if (
                session.context_type != "customer"
                or data.get("business_ref_type") != "customer"
                or not ref_id
                or ref_id != str(session.context_id)
                or input_customer_id != ref_id
            ):
                raise ForbiddenError("客户经营副驾驶必须绑定会话中的同一统一客户")
    existing = db.query(AgentRun).filter(
        AgentRun.owner_user_id == user_id,
        AgentRun.idempotency_key == data["idempotency_key"],
    ).one_or_none()
    if existing is not None:
        if existing.session_id != session_id or existing.input_json != data.get("input", {}):
            raise ConflictError("相同幂等键对应不同 Agent 任务")
        return existing

    active_values = [item.value for item in ACTIVE_RUN_STATUSES]
    session_active = db.query(AgentRun).filter(
        AgentRun.session_id == session_id,
        AgentRun.status.in_(active_values),
    ).count()
    if session_active:
        raise ConflictError("同一会话已有执行中的任务")
    user_active = db.query(AgentRun).filter(
        AgentRun.owner_user_id == user_id,
        AgentRun.status.in_(active_values),
    ).count()
    if user_active >= get_settings().AGENT_RUNTIME_MAX_ACTIVE_PER_USER:
        raise ConflictError("已达到个人 Agent 并发上限")

    context_snapshot = {
        "owner_user_id": user_id,
        "permissions": sorted(effective_permissions),
        "roles": sorted(set(roles)),
        "profile_key": profile.profile_key,
        "profile_version": profile.version,
        "session_context": {"type": session.context_type, "id": session.context_id},
    }
    row = AgentRun(
        session_id=session.id,
        profile_id=profile.id,
        owner_user_id=user_id,
        idempotency_key=data["idempotency_key"],
        trigger_type=data.get("trigger_type", "user"),
        source_runtime=profile.runtime,
        mode=profile.mode,
        business_ref_type=data.get("business_ref_type") or session.context_type,
        business_ref_id=data.get("business_ref_id") or session.context_id,
        input_json=data.get("input", {}),
        context_snapshot=context_snapshot,
        status=RunStatus.QUEUED.value,
        max_attempts=int((profile.limits_json or {}).get("max_attempts", 3)),
    )
    db.add(row)
    try:
        db.flush()
        raw_customer_id = run_input.get("customer_id")
        try:
            customer_id = int(raw_customer_id) if raw_customer_id is not None else None
        except (TypeError, ValueError):
            customer_id = None
        if (
            customer_id is not None
            and db.query(CustomerAccount.id).filter(
                CustomerAccount.id == customer_id,
                CustomerAccount.record_status == "active",
            ).first() is not None
        ):
            scope_snapshot_hash = content_hash({
                "run_id": row.id,
                "customer_ids": [customer_id],
                "permissions": context_snapshot["permissions"],
                "created_at": row.created_at,
            })
            db.add(CustomerAgentRunScope(
                run_id=row.id,
                customer_id=customer_id,
                scope_type="single",
                source_ref_type=row.business_ref_type,
                source_ref_id=row.business_ref_id,
                scope_snapshot_hash=scope_snapshot_hash,
                membership_fingerprint=content_hash({
                    "run_id": row.id,
                    "customer_id": customer_id,
                    "scope_snapshot_hash": scope_snapshot_hash,
                }),
                created_at=row.created_at,
            ))
            db.flush()
        append_event(
            db, row,
            event_id=f"run-{row.id}-created",
            event_type="run.created",
            actor_type="user",
            payload={
                "trigger_type": row.trigger_type,
                "business_ref_type": row.business_ref_type,
                "business_ref_id": row.business_ref_id,
                "profile_key": profile.profile_key,
                "profile_version": profile.version,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = db.query(AgentRun).filter(
            AgentRun.owner_user_id == user_id,
            AgentRun.idempotency_key == data["idempotency_key"],
        ).one_or_none()
        if raced is not None and raced.session_id == session_id and raced.input_json == data.get("input", {}):
            return raced
        raise ConflictError("Agent 任务幂等键冲突") from None
    db.refresh(row)
    return row


def _run_for_user(db: Session, run_id: int, user_id: int, can_read_all: bool, *, lock: bool = False) -> AgentRun:
    query = db.query(AgentRun).filter(AgentRun.id == run_id)
    if not can_read_all:
        query = query.filter(AgentRun.owner_user_id == user_id)
    if lock:
        query = query.with_for_update()
    row = query.one_or_none()
    if row is None:
        raise NotFoundError("Agent 任务不存在")
    return row


def get_run(db: Session, run_id: int, *, user_id: int, can_read_all: bool) -> AgentRun:
    return _run_for_user(db, run_id, user_id, can_read_all)


def list_runs(
    db: Session,
    *,
    user_id: int,
    can_read_all: bool,
    status: str | None,
    runtime: str | None,
    page: int,
    page_size: int,
) -> tuple[list[AgentRun], int]:
    query = db.query(AgentRun)
    if not can_read_all:
        query = query.filter(AgentRun.owner_user_id == user_id)
    if status:
        query = query.filter(AgentRun.status == status)
    if runtime:
        query = query.filter(AgentRun.source_runtime == runtime)
    total = query.count()
    rows = query.order_by(desc(AgentRun.created_at), desc(AgentRun.id)).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    return rows, total


def cancel_run(db: Session, run_id: int, *, user_id: int, can_read_all: bool) -> AgentRun:
    row = _run_for_user(db, run_id, user_id, can_read_all, lock=True)
    if row.status in {RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value, RunStatus.AMBIGUOUS.value}:
        return row
    if row.status == RunStatus.QUEUED.value:
        require_transition(row.status, RunStatus.CANCELLED)
        row.status = RunStatus.CANCELLED.value
        row.cancel_requested = True
        row.completed_at = beijing_now()
        append_event(
            db, row,
            event_id=f"run-{row.id}-cancelled",
            event_type="run.cancelled",
            actor_type="user",
            payload={"reason": "cancelled_before_claim"},
        )
    else:
        row.cancel_requested = True
    db.commit()
    db.refresh(row)
    return row


def list_events(
    db: Session,
    run_id: int,
    *,
    user_id: int,
    can_read_all: bool,
    include_admin: bool,
    after_sequence: int = 0,
    limit: int = 200,
) -> list[AgentEvent]:
    _run_for_user(db, run_id, user_id, can_read_all)
    visibility = ["user", "admin"] if include_admin else ["user"]
    return db.query(AgentEvent).filter(
        AgentEvent.run_id == run_id,
        AgentEvent.sequence_no > after_sequence,
        AgentEvent.visibility.in_(visibility),
    ).order_by(AgentEvent.sequence_no).limit(limit).all()


def list_artifacts(db: Session, run_id: int, *, user_id: int, can_read_all: bool) -> list[AgentArtifact]:
    _run_for_user(db, run_id, user_id, can_read_all)
    return db.query(AgentArtifact).filter(AgentArtifact.run_id == run_id).order_by(AgentArtifact.id).all()


def add_feedback(
    db: Session, run_id: int, *, user_id: int, can_read_all: bool, rating: str, note: str | None,
) -> AgentRun:
    row = _run_for_user(db, run_id, user_id, can_read_all, lock=True)
    event_key = content_hash({"rating": rating, "note": note})
    append_event(
        db, row,
        event_id=f"run-{row.id}-feedback-{event_key[:20]}",
        event_type="user.feedback",
        actor_type="user",
        payload={"rating": rating, "note": note},
    )
    db.commit()
    return row
