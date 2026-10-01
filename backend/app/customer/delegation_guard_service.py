"""Shared claim/tool/result guard for delegated preparation Runs."""

from datetime import datetime, timedelta

from app.core.time import beijing_now, to_beijing_naive
from app.customer import pcw_errors
from app.customer.models import CustomerAccount
from app.customer.pcw_models import CustomerWorkItem
from app.customer.workbench_models import CustomerDelegation
from app.customer.work_item_service import item_access


PREPARATION_TOOLS = frozenset({"get_customer_profile", "get_customer_facts", "get_customer_orders",
    "search_customer_messages", "get_customer_actions", "get_customer_evidence", "get_customer_source_chunks"})


def live_delegation_user(db, user_id, snapshot=None, *, lock=False):
    from app.auth.service import get_live_user_authorization
    if lock:
        # Locking reads see current authorization under MySQL REPEATABLE READ,
        # rather than reusing an earlier transaction's consistent snapshot.
        from app.auth.models import ArkUser, ArkRole, ArkPermission, ArkUserRole, ArkRolePermission
        active = db.query(ArkUser.id).filter(ArkUser.id == user_id, ArkUser.is_active.is_(True),
            ArkUser.deleted_at.is_(None)).with_for_update().one_or_none()
        if active is None:
            roles, permissions = [], []
        else:
            roles = [row[0] for row in db.query(ArkRole.name).join(ArkUserRole,
                ArkUserRole.role_id == ArkRole.id).filter(ArkUserRole.user_id == user_id).with_for_update().all()]
            permissions = [row[0] for row in db.query(ArkPermission.code).join(ArkRolePermission,
                ArkRolePermission.permission_id == ArkPermission.id).join(ArkUserRole,
                ArkUserRole.role_id == ArkRolePermission.role_id).filter(
                ArkUserRole.user_id == user_id).with_for_update().all()]
    else:
        roles, permissions = get_live_user_authorization(db, user_id)
    if snapshot is not None:
        roles = set(roles) & set(snapshot.get("roles") or [])
        permissions = set(permissions) & set(snapshot.get("permissions") or [])
    return {"sub": str(user_id), "roles": sorted(roles), "permissions": sorted(permissions)}


def guard_run(db, run, *, lock=False, adoption=False, actor_user_id=None):
    data = run.input_json or {}
    delegation_id = data.get("delegation_id")
    if delegation_id is None:
        return None
    user = live_delegation_user(db, run.owner_user_id, run.context_snapshot or {})
    if "agent_runtime:invoke" not in user["permissions"] and "super_admin" not in user["roles"]:
        raise pcw_errors.forbidden("委派调用权限已撤回", error_code="DELEGATION_AUTH_REVOKED")
    item, access = item_access(db, user, int(data.get("work_item_id") or 0), write=True, lock=lock)
    if not lock:
        item = db.query(CustomerWorkItem).filter(CustomerWorkItem.id == item.id).populate_existing().one()
    if lock:
        user = live_delegation_user(db, run.owner_user_id, run.context_snapshot or {}, lock=True)
        if "agent_runtime:invoke" not in user["permissions"] and "super_admin" not in user["roles"]:
            raise pcw_errors.forbidden("委派调用权限已撤回", error_code="DELEGATION_AUTH_REVOKED")
        item_access(db, user, item.id, write=True)
    from app.customer.work_item_source_service import reconcile_item_inputs
    item = reconcile_item_inputs(db, item, actor_user_id=run.owner_user_id) if lock else reconcile_item_inputs(
        db, item, read_only=True, actor_user_id=run.owner_user_id)
    query = db.query(CustomerDelegation).filter(CustomerDelegation.id == delegation_id,
        CustomerDelegation.item_id == item.id, CustomerDelegation.actor_user_id == run.owner_user_id)
    query = query.populate_existing()
    delegation = query.with_for_update().one_or_none() if lock else query.one_or_none()
    from app.agent_runtime.models import AgentProfile
    from app.agent_runtime.service import profile_feature_enabled
    profile_query = db.query(AgentProfile).filter(AgentProfile.id == run.profile_id).populate_existing()
    profile = profile_query.with_for_update().one_or_none() if lock else profile_query.one_or_none()
    if (profile is None or profile.status != "active" or not profile_feature_enabled(profile.profile_key)
            or not (profile.policy_json or {}).get("read_only")
            or not set(profile.tool_allowlist or []).issubset(PREPARATION_TOOLS)
            or delegation is not None and (delegation.scope_json or {}).get("mode") != "prepare"):
        raise pcw_errors.conflict("委派只允许读取与准备产物", error_code="DELEGATION_SCOPE_INVALID")
    allowed_states = {"needs_decision"} if adoption else {"active"}
    if (delegation is None or delegation.status not in allowed_states or item.state in {"paused", "blocked", "resolved", "cancelled"}
            or delegation.last_run_id != run.id
            or delegation.generation != data.get("delegation_generation")
            or delegation.input_revision != item.source_revision or item.source_revision != data.get("work_item_input_revision")
            or not item.source_valid or run.cancel_requested):
        raise pcw_errors.conflict("委派已停止、来源变化或代次失效", error_code="DELEGATION_STALE")
    if access.customer_id != data.get("customer_id"):
        raise pcw_errors.conflict("客户归属已变化，请重新核验委派", error_code="DELEGATION_CUSTOMER_CHANGED")
    account_query = db.query(CustomerAccount).filter(CustomerAccount.id == access.customer_id).populate_existing()
    account = account_query.with_for_update().one() if lock else account_query.one()
    if (account.profile_input_seq != data.get("customer_input_seq")
            or account.current_profile_version_id != data.get("customer_profile_version_id")):
        raise pcw_errors.conflict("客户事实或档案已变化，请重新准备", error_code="DELEGATION_INPUT_CHANGED")
    if adoption:
        if run.status != "completed":
            raise pcw_errors.conflict("运行尚未确认交付", error_code="DELEGATION_RUN_NOT_COMPLETED")
        actor = live_delegation_user(db, actor_user_id, lock=lock)
        item_access(db, actor, item.id, write=True, lock=False)
    return delegation


def guard_runtime_run(db, run, *, lock=False, adoption=False, actor_user_id=None):
    from app.agent_runtime.errors import ConflictError
    try:
        return guard_run(db, run, lock=lock, adoption=adoption, actor_user_id=actor_user_id)
    except pcw_errors.PcwError as exc:
        raise ConflictError(exc.error_code) from exc


def lock_delegation_for_stop(db, run):
    """Control-plane stop bookkeeping requires locks, never restored authority."""
    data = run.input_json or {}
    if data.get("delegation_id") is None:
        return None
    from app.customer.logical_customer_service import logical_owner_expression
    from app.customer.workflow_service import _account_for_update
    logical_id = db.query(logical_owner_expression(CustomerWorkItem, "work_item")).filter(
        CustomerWorkItem.id == data.get("work_item_id")).scalar()
    if logical_id is None:
        return None
    _account_for_update(db, logical_id)
    db.query(CustomerWorkItem).filter(CustomerWorkItem.id == data["work_item_id"]).populate_existing().with_for_update().one()
    return db.query(CustomerDelegation).filter(CustomerDelegation.id == data["delegation_id"],
        CustomerDelegation.item_id == data["work_item_id"]).populate_existing().with_for_update().one_or_none()


def record_run_stop(db, run):
    # Caller acquired the customer/item/delegation locks before the Run lock.
    data = run.input_json or {}
    delegation = db.get(CustomerDelegation, data.get("delegation_id")) if data.get("delegation_id") else None
    if (delegation is not None and delegation.last_run_id == run.id
            and delegation.generation == data.get("delegation_generation") and delegation.status == "active"):
        delegation.status = "blocked"
        delegation.pause_reason = run.error_code or "运行已停止，继续前需要人工核验"
        delegation.row_version += 1


def finish_delegation(db, run, artifacts, *, waiting_payload=None):
    delegation = guard_runtime_run(db, run, lock=True)
    if delegation is None:
        return
    from app.customer.work_item_service import record_event
    item = db.get(CustomerWorkItem, delegation.item_id)
    previous = item.state
    delegation.status = "needs_decision" if artifacts else "waiting"
    delegation.row_version += 1
    if not artifacts:
        waiting_payload = waiting_payload or {}
        condition = str(waiting_payload.get("resume_condition") or "等待新输入或到期重新核验").strip()
        try:
            raw_review = waiting_payload.get("review_at")
            parsed_review = datetime.fromisoformat(raw_review.replace("Z", "+00:00")) if isinstance(raw_review, str) else raw_review
            review_at = to_beijing_naive(parsed_review) if parsed_review else beijing_now() + timedelta(days=1)
        except (TypeError, ValueError, AttributeError) as exc:
            from app.agent_runtime.errors import ConflictError
            raise ConflictError("复核时间格式无效") from exc
        if not condition or review_at <= beijing_now():
            from app.agent_runtime.errors import ConflictError
            raise ConflictError("委派等待需要继续条件和未来复核时间")
        delegation.review_at = review_at
        delegation.scope_json = {**(delegation.scope_json or {}), "resume_condition": condition}
        item.review_at = review_at
        item.resume_condition = condition
        item.waiting_kind = "internal"
    else:
        delegation.review_at = None
    item.state = "decision_required" if artifacts else "waiting"
    record_event(db, item, actor=run.owner_user_id, operation="delegation_result", previous=previous,
        reason="准备产物已交付，等待人工核验" if artifacts else "等待新输入", payload={"run_id": run.id, "delegation_id": delegation.id})
