"""Explicit preparation delegation bound to item lifecycle and fresh input generations."""

import json

from app.core.time import beijing_now
from app.customer import pcw_errors
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.pcw_workitem_service import _require_version
from app.customer.workbench_models import CustomerDelegation
from app.customer.work_item_service import TERMINAL, item_access, record_event


def readiness(db):
    from app.agent_runtime.service import profile_feature_enabled
    from app.agent_runtime.models import AgentProfile
    from app.ai.models import AiPreset
    from app.core.config import get_settings
    profile = db.query(AgentProfile).filter(AgentProfile.profile_key == "customer_order_copilot",
        AgentProfile.status == "active").order_by(AgentProfile.version.desc()).first()
    gaps = []
    if not profile_feature_enabled("customer_order_copilot"):
        gaps.append("客户副驾驶灰度开关尚未开启")
    settings = get_settings()
    if not settings.AGENT_RUNTIME_DSH_ENABLED:
        gaps.append("Agent 执行器尚未开启")
    from app.customer.delegation_guard_service import PREPARATION_TOOLS
    if (profile is None or not (profile.policy_json or {}).get("read_only")
            or not set(profile.tool_allowlist or []).issubset(PREPARATION_TOOLS)):
        gaps.append("缺少只读准备型 Agent 配置")
    if profile is not None and db.query(AiPreset.id).filter(AiPreset.preset_name == profile.model_preset,
            AiPreset.is_enabled.is_(True), AiPreset.deleted_at.is_(None)).first() is None:
        gaps.append("缺少可用模型预设")
    try:
        credentials = json.loads(settings.AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON or "{}")
        runtimes = json.loads(settings.AGENT_RUNTIME_WORKER_RUNTIMES_JSON or "{}")
        worker_configured = isinstance(credentials, dict) and isinstance(runtimes, dict) and any(
            isinstance(runtimes.get(worker), list) and "dsh" in runtimes[worker]
            and any(isinstance(value, str) and len(value) == 64
                and all(char in "0123456789abcdefABCDEF" for char in value)
                for value in (hashes if isinstance(hashes, list) else [hashes]))
            for worker, hashes in credentials.items())
    except (TypeError, ValueError):
        worker_configured = False
    if not worker_configured:
        gaps.append("缺少绑定 DSH 执行器的有效 Worker 凭证")
    return {"status": "blocked" if gaps else "ready", "gaps": gaps,
        "worker_status": "configured_not_observed" if worker_configured else "unconfigured"}


def serialize_delegation(db, row):
    from app.agent_runtime.models import AgentRun
    run = db.get(AgentRun, row.last_run_id) if row.last_run_id else None
    stopped = run is None or run.status in {"completed", "failed", "cancelled"}
    return {"id": row.id, "goal": row.goal, "state": row.status, "generation": row.generation,
        "row_version": row.row_version, "last_run_id": row.last_run_id, "run_status": run.status if run else None,
        "stop_requested": bool((row.cancel_requested or run is not None and run.cancel_requested) and not stopped),
        "stop_confirmed": stopped, "outcome_uncertain": run is not None and run.status == "ambiguous",
        "review_at": row.review_at.isoformat() if row.review_at else None,
        "resume_condition": (row.scope_json or {}).get("resume_condition"),
        "allowed_operations": ["resume", "cancel"] if row.status in {"paused", "blocked"} else
            ["pause", "cancel"] if row.status not in {"cancelled", "completed"} else [], "readiness": readiness(db)}


def _require_previous_stopped(db, row):
    from app.agent_runtime.models import AgentRun
    if row.last_run_id:
        previous = db.query(AgentRun).filter(AgentRun.id == row.last_run_id).populate_existing().one_or_none()
        if previous and previous.status not in {"completed", "failed", "cancelled"}:
            raise pcw_errors.conflict("上次运行尚未停止或结果不确定，请先查询原运行", error_code="DELEGATION_PREVIOUS_RUN_UNCERTAIN")


def _launch(db, user, item, row):
    from app.agent_runtime import service
    from app.agent_runtime.errors import AgentRuntimeError
    _require_previous_stopped(db, row)
    availability = readiness(db)
    if availability["status"] != "ready":
        row.status = "blocked"
        row.pause_reason = "；".join(availability["gaps"])
        return
    from app.customer.delegation_guard_service import live_delegation_user
    user = live_delegation_user(db, row.actor_user_id, user, lock=True)
    if "agent_runtime:invoke" not in user["permissions"] and "super_admin" not in user["roles"]:
        raise pcw_errors.forbidden("委派调用权限已撤回", error_code="DELEGATION_AUTH_REVOKED")
    access = item_access(db, user, item.id, write=True)[1]
    from app.customer.work_item_source_service import reconcile_item_inputs
    item = reconcile_item_inputs(db, item, actor_user_id=row.actor_user_id)
    if item.state in TERMINAL or item.state in {"paused", "blocked"} or not item.source_valid:
        raise pcw_errors.conflict("事项当前不允许委派执行", error_code="WORK_ITEM_NOT_EXECUTABLE")
    from app.customer.models import CustomerAccount
    account = db.query(CustomerAccount).filter(CustomerAccount.id == access.customer_id).populate_existing().with_for_update().one()
    try:
        with db.begin_nested():
            session = service.create_session(db, {"profile_key": "customer_order_copilot", "title": item.title[:255],
                "context_type": "customer", "context_id": str(access.customer_id)},
                user_id=row.actor_user_id, commit=False)
            run = service.create_run(db, session.id, {"idempotency_key": f"customer-delegation-{row.id}-{row.generation}",
                "business_ref_type": "customer", "business_ref_id": session.context_id,
                "trigger_type": "user", "input": {"customer_id": int(session.context_id), "question": row.goal,
                    "work_item_id": item.id, "delegation_id": row.id, "delegation_generation": row.generation,
                    "work_item_input_revision": item.source_revision, "customer_input_seq": account.profile_input_seq,
                    "customer_profile_version_id": account.current_profile_version_id}}, user_id=row.actor_user_id,
                permissions=list(user.get("permissions") or []), roles=list(user.get("roles") or []),
                system_initiated=True, commit=False)
    except AgentRuntimeError as exc:
        raise pcw_errors.conflict(str(exc), error_code="DELEGATION_RUN_NOT_READY") from exc
    row.last_run_id = run.id
    row.input_revision = item.source_revision
    row.status = "active"
    row.pause_reason = None
    row.pause_origin = None
    row.cancel_requested = False
    row.review_at = None


def enqueue_waiting_delegations(db, *, limit=100):
    """Durable review/input trigger; each generation receives a new immutable Run."""
    from app.customer.delegation_guard_service import live_delegation_user
    from app.customer.pcw_models import CustomerWorkItem
    from app.agent_runtime.models import AgentRun
    candidates = db.query(CustomerDelegation.id).join(CustomerWorkItem,
        CustomerWorkItem.id == CustomerDelegation.item_id).filter(
        CustomerDelegation.status == "waiting",
        ((CustomerDelegation.review_at <= beijing_now()) |
         (CustomerDelegation.input_revision != CustomerWorkItem.source_revision)),
    ).order_by(CustomerDelegation.id).limit(limit).all()
    launched = 0
    for (delegation_id,) in candidates:
        with db.begin_nested():
            candidate = db.get(CustomerDelegation, delegation_id)
            scope = candidate.scope_json or {}
            user = live_delegation_user(db, candidate.actor_user_id, {
                "permissions": scope.get("permissions_at_start") or [], "roles": scope.get("roles_at_start") or []})
            try:
                if "agent_runtime:invoke" not in user["permissions"] and "super_admin" not in user["roles"]:
                    raise pcw_errors.forbidden("委派调用权限已撤回", error_code="DELEGATION_AUTH_REVOKED")
                item, _access = item_access(db, user, candidate.item_id, write=True, lock=True)
            except pcw_errors.PcwError as exc:
                row = db.query(CustomerDelegation).filter(CustomerDelegation.id == delegation_id).populate_existing().with_for_update().one()
                if row.status != "waiting":
                    continue
                row.status = "blocked"
                row.pause_reason = exc.error_code
                row.row_version += 1
                continue
            row = db.query(CustomerDelegation).filter(CustomerDelegation.id == delegation_id).populate_existing().with_for_update().one()
            if row.status != "waiting" or (row.review_at is not None and row.review_at > beijing_now()
                    and row.input_revision == item.source_revision):
                continue
            if not (row.scope_json or {}).get("resume_condition") or row.review_at is None:
                row.status = "blocked"
                row.pause_reason = "等待缺少继续条件或复核时间"
                row.row_version += 1
                continue
            previous = db.get(AgentRun, row.last_run_id) if row.last_run_id else None
            if previous and previous.status not in {"completed", "failed", "cancelled"}:
                row.status = "blocked"
                row.pause_reason = "上次运行尚未停止或结果不确定，请查询原运行"
                row.row_version += 1
                continue
            row.generation += 1
            row.row_version += 1
            try:
                _launch(db, user, item, row)
            except pcw_errors.PcwError as exc:
                row.status = "blocked"
                row.pause_reason = exc.error_code
            if row.status == "active":
                launched += 1
                record_event(db, item, actor=row.actor_user_id, operation="delegation_recheck", previous=item.state,
                    reason="等待条件变化或复核到期，创建新的准备运行", payload={"delegation_id": row.id, "run_id": row.last_run_id})
    db.flush()
    return launched


def enqueue_waiting_delegations_job():
    from app.core.database import SessionLocal
    with SessionLocal() as db:
        count = enqueue_waiting_delegations(db)
        db.commit()
        return count


def create_delegation(db, user, item_id, payload, idempotency_key):
    from app.customer.delegation_guard_service import live_delegation_user
    user = live_delegation_user(db, int(user["sub"]), user)
    item, access = item_access(db, user, item_id, write=True, lock=True)
    if "agent_runtime:invoke" not in (user.get("permissions") or []) and "super_admin" not in (user.get("roles") or []):
        raise pcw_errors.forbidden("委派准备需要 Agent 调用权限", error_code="AGENT_INVOKE_REQUIRED")

    def execute():
        _require_version(item.row_version, payload["expected_item_version"], "WORK_ITEM_VERSION_CONFLICT", "current_item_version")
        if item.state in TERMINAL or item.state in {"paused", "blocked"}:
            raise pcw_errors.conflict("事项当前不允许委派", error_code="WORK_ITEM_NOT_EXECUTABLE")
        if payload.get("scope", "prepare") != "prepare":
            raise pcw_errors.bad_request("本次只允许准备产物", error_code="DELEGATION_SCOPE_INVALID")
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            raise pcw_errors.bad_request("委派目标不能为空", error_code="DELEGATION_GOAL_REQUIRED")
        existing = db.query(CustomerDelegation.id).filter(CustomerDelegation.item_id == item.id,
            CustomerDelegation.actor_user_id == access.actor_user_id,
            CustomerDelegation.status.notin_(("cancelled", "completed"))).first()
        if existing:
            raise pcw_errors.conflict("本事项已有持续委派，请处理或终止现有委派", error_code="DELEGATION_EXISTS")
        row = CustomerDelegation(item_id=item.id, actor_user_id=access.actor_user_id, goal=goal,
            scope_json={"mode": "prepare", "read_only": True, "customer_id": access.customer_id,
                "permissions_at_start": list(user.get("permissions") or []),
                "roles_at_start": list(user.get("roles") or [])}, input_revision=item.source_revision)
        db.add(row)
        db.flush()
        _launch(db, user, item, row)
        record_event(db, item, actor=access.actor_user_id, operation="delegated", previous=item.state,
            reason=goal, payload={"delegation_id": row.id})
        return {"delegation": serialize_delegation(db, row)}

    result, _ = run_with_receipt(db, actor_user_id=access.actor_user_id, operation_scope=f"delegation_create:{item_id}",
        idempotency_key=idempotency_key, request_payload=payload, execute=execute)
    return result


def transition_delegation(db, user, delegation_id, payload, idempotency_key):
    from app.customer.delegation_guard_service import live_delegation_user
    user = live_delegation_user(db, int(user["sub"]), user)
    candidate = db.get(CustomerDelegation, delegation_id)
    if candidate is None or candidate.actor_user_id != int(user["sub"]):
        raise pcw_errors.customer_not_found()
    item, access = item_access(db, user, candidate.item_id, write=True, lock=True)
    row = db.query(CustomerDelegation).filter(CustomerDelegation.id == delegation_id).populate_existing().with_for_update().one()

    def execute():
        _require_version(row.row_version, payload["expected_delegation_version"], "DELEGATION_VERSION_CONFLICT", "current_delegation_version")
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise pcw_errors.bad_request("需要具体原因", error_code="DELEGATION_REASON_REQUIRED")
        operation = payload["operation"]
        if operation not in serialize_delegation(db, row)["allowed_operations"]:
            raise pcw_errors.conflict("委派当前不允许该操作", error_code="DELEGATION_TRANSITION_INVALID")
        if operation == "resume":
            if "agent_runtime:invoke" not in user["permissions"] and "super_admin" not in user["roles"]:
                raise pcw_errors.forbidden("委派调用权限已撤回", error_code="DELEGATION_AUTH_REVOKED")
            _require_previous_stopped(db, row)
        row.generation += 1
        row.row_version += 1
        row.updated_at = beijing_now()
        if operation == "resume":
            _launch(db, user, item, row)
        else:
            row.status = "paused" if operation == "pause" else "cancelled"
            row.pause_origin = "manual"
            row.pause_reason = reason
            if row.last_run_id:
                from app.agent_runtime.models import AgentRun
                run = db.query(AgentRun).filter(AgentRun.id == row.last_run_id).with_for_update().one_or_none()
                if run and run.status not in {"completed", "failed", "cancelled", "ambiguous"}:
                    run.cancel_requested = True
                    row.cancel_requested = True
        record_event(db, item, actor=access.actor_user_id, operation=f"delegation_{operation}", previous=item.state,
            reason=reason, payload={"delegation_id": row.id, "generation": row.generation})
        return {"delegation": serialize_delegation(db, row)}

    result, _ = run_with_receipt(db, actor_user_id=access.actor_user_id, operation_scope=f"delegation_transition:{delegation_id}",
        idempotency_key=idempotency_key, request_payload=payload, execute=execute)
    return result
