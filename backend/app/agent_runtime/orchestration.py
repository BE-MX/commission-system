"""Business-event and scheduled entry points for first-party Agent Profiles."""

from __future__ import annotations

from datetime import date
from app.core.time import beijing_today
import hashlib
import logging

from sqlalchemy.orm import Session

from app.agent_runtime import service
from app.agent_runtime.errors import ConflictError
from app.agent_runtime.models import AgentRun, AgentSession
from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.logical_customer_service import logical_owner_expression
from app.insight.models import CustomerAction
from app.sales_automation.models import SearchJob


logger = logging.getLogger("commission.agent_runtime.orchestration")


def _identity(user: ArkUser) -> tuple[list[str], list[str]]:
    return get_user_permissions(user), get_user_roles(user)


def _has_permissions(permissions: list[str], *required: str) -> bool:
    values = set(permissions)
    return all(item in values for item in required)


def _cleanup_empty_session(db: Session, session: AgentSession | None) -> None:
    if session is not None and db.query(AgentRun).filter(AgentRun.session_id == session.id).count() == 0:
        db.delete(session)
        db.commit()


def enqueue_repurchase_runs(db: Session, *, action_date: date | None = None, limit: int | None = None) -> int:
    settings = get_settings()
    if not settings.AGENT_RUNTIME_REPURCHASE_ENABLED or not settings.AGENT_RUNTIME_DSH_ENABLED:
        return 0
    target_date = action_date or beijing_today()
    batch_size = min(limit or settings.AGENT_RUNTIME_REPURCHASE_BATCH_SIZE, 100)
    owner_id = logical_owner_expression(CustomerAction, "action")
    actions = db.query(
        CustomerAction, owner_id.label("logical_customer_id"),
    ).filter(
        CustomerAction.action_date == target_date,
        CustomerAction.thread_group == "reorder",
        CustomerAction.status == "pending",
        CustomerAction.agent_run_id.is_(None),
    ).order_by(
        CustomerAction.due_at.is_(None).asc(),
        CustomerAction.due_at.asc(),
        CustomerAction.id,
    ).limit(batch_size).all()
    created = 0
    for action, logical_customer_id in actions:
        logical_customer_id = int(logical_customer_id)
        if db.query(AgentRun).filter(
            AgentRun.business_ref_type == "customer_action",
            AgentRun.business_ref_id == str(action.id),
        ).count():
            continue
        user = db.query(ArkUser).filter(
            ArkUser.id == action.owner_user_id,
            ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None),
        ).one_or_none()
        if user is None:
            continue
        permissions, roles = _identity(user)
        if "super_admin" not in roles and not _has_permissions(
            permissions, "agent_runtime:invoke", "customer_radar:write", "order_intelligence:read",
        ):
            continue
        try:
            require_customer_access(
                db,
                customer_id=logical_customer_id,
                user={
                    "sub": str(user.id),
                    "permissions": permissions,
                    "roles": roles,
                },
                action_permissions={"customer_radar:write", "customer_radar:manage"},
                manage_permissions={"customer_radar:manage"},
            )
        except CustomerAccessDenied:
            continue
        session = None
        try:
            session = service.create_session(db, {
                "profile_key": "repurchase_risk_analyst",
                "title": f"复购行动分析 #{action.id}",
                "context_type": "customer",
                "context_id": str(logical_customer_id),
            }, user_id=action.owner_user_id, system_initiated=True)
            service.create_run(db, session.id, {
                "idempotency_key": f"repurchase-action-{action.id}-{action.action_fingerprint[:32]}",
                "input": {
                    "customer_id": logical_customer_id,
                    "action_id": action.id,
                    "rule_reason": action.reason,
                },
                "trigger_type": "schedule",
                "business_ref_type": "customer_action",
                "business_ref_id": str(action.id),
            }, user_id=action.owner_user_id, permissions=permissions, roles=roles,
                system_initiated=True)
            created += 1
        except ConflictError:
            db.rollback()
            _cleanup_empty_session(db, session)
    return created


def enqueue_repurchase_job() -> int:
    with SessionLocal() as db:
        return enqueue_repurchase_runs(db)


def maybe_enqueue_sales_shadow(db: Session, job: SearchJob, current_user: dict) -> AgentRun | None:
    settings = get_settings()
    if not (
        settings.AGENT_RUNTIME_SALES_SHADOW_ENABLED
        and settings.AGENT_RUNTIME_WEB_SEARCH_ENABLED
        and settings.AGENT_RUNTIME_DSH_ENABLED
        and settings.AGENT_RUNTIME_SHADOW_SAMPLE_RATE > 0
    ):
        return None
    threshold = int(hashlib.sha256(f"search-job:{job.id}".encode()).hexdigest()[:8], 16) / (2 ** 32)
    if threshold >= settings.AGENT_RUNTIME_SHADOW_SAMPLE_RATE:
        return None
    permissions = list(current_user.get("permissions") or [])
    roles = list(current_user.get("roles") or [])
    if "super_admin" not in roles and not _has_permissions(
        permissions, "agent_runtime:invoke", "sales_automation:read",
    ):
        return None
    user_id = int(current_user["sub"])
    session = None
    try:
        session = service.create_session(db, {
            "profile_key": "sales_discovery_shadow",
            "title": f"DSH 影子评测：{job.name}",
            "context_type": "search_job",
            "context_id": str(job.id),
        }, user_id=user_id, system_initiated=True)
        return service.create_run(db, session.id, {
            "idempotency_key": f"sales-shadow-search-job-{job.id}",
            "input": {"search_job_id": job.id},
            "trigger_type": "shadow",
            "business_ref_type": "search_job",
            "business_ref_id": str(job.id),
        }, user_id=user_id, permissions=permissions, roles=roles, system_initiated=True)
    except ConflictError:
        db.rollback()
        _cleanup_empty_session(db, session)
        return None
    except Exception as exc:  # noqa: BLE001
        # Shadow evaluation is optional and must never change the success
        # semantics of the already-committed core SearchJob operation.
        db.rollback()
        try:
            _cleanup_empty_session(db, session)
        except Exception:  # noqa: BLE001
            db.rollback()
        logger.warning("DSH sales shadow enqueue skipped: %s", type(exc).__name__)
        return None
