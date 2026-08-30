"""Human-confirmed Agent artifact projections into existing business records."""

from datetime import datetime
from app.core.time import beijing_now

from sqlalchemy.orm import Session

from app.agent_runtime.errors import ConflictError
from app.agent_runtime.models import AgentArtifact, AgentProfile, AgentRun
from app.auth.models import ArkUser
from app.auth.service import get_user_permissions, get_user_roles
from app.customer.access_service import CustomerAccessDenied, require_customer_access
from app.customer.models import (
    CustomerAccount,
    CustomerAction,
    CustomerAssignment,
    CustomerOpportunity,
)


def project_accepted_artifact(
    db: Session,
    artifact: AgentArtifact,
    run: AgentRun,
    *,
    actor_user_id: int,
) -> None:
    """Project supported artifacts; unsupported types intentionally remain audit-only."""
    if artifact.artifact_type != "repurchase_action_card":
        return
    if run.business_ref_type != "customer_action" or not run.business_ref_id:
        raise ConflictError("复购行动卡没有绑定原始行动")
    try:
        action_id = int(run.business_ref_id)
    except (TypeError, ValueError) as exc:
        raise ConflictError("复购行动卡业务引用无效") from exc
    candidate = db.get(CustomerAction, action_id)
    if candidate is None:
        raise ConflictError("复购行动卡原始行动不存在或归属不匹配")
    account = db.query(CustomerAccount).filter(
        CustomerAccount.id == candidate.customer_id,
        CustomerAccount.record_status == "active",
    ).with_for_update().one_or_none()
    if account is None:
        raise ConflictError("复购行动卡原始行动不存在或归属不匹配")
    opportunity = None
    if candidate.opportunity_id is not None:
        opportunity = db.query(CustomerOpportunity).filter(
            CustomerOpportunity.id == candidate.opportunity_id,
            CustomerOpportunity.customer_id == account.id,
        ).with_for_update().one_or_none()
    action = db.query(CustomerAction).filter(
        CustomerAction.id == action_id,
        CustomerAction.customer_id == account.id,
    ).with_for_update().one_or_none()
    live_assignment = db.query(CustomerAssignment.id).filter(
        CustomerAssignment.customer_id == account.id,
        CustomerAssignment.user_id == run.owner_user_id,
        CustomerAssignment.assignment_role.in_(("primary", "collaborator")),
        CustomerAssignment.assignment_status == "active",
        CustomerAssignment.effective_to.is_(None),
    ).first()
    owner = db.query(ArkUser).filter(
        ArkUser.id == run.owner_user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).one_or_none()
    actor = db.query(ArkUser).filter(
        ArkUser.id == actor_user_id,
        ArkUser.is_active.is_(True),
        ArkUser.deleted_at.is_(None),
    ).one_or_none()
    owner_access = None
    actor_access = None
    if owner is not None:
        current_permissions = set(get_user_permissions(owner))
        current_roles = set(get_user_roles(owner))
        snapshot = run.context_snapshot or {}
        delegated_permissions = current_permissions & set(
            snapshot.get("permissions") or []
        )
        delegated_roles = current_roles & set(snapshot.get("roles") or [])
        profile = db.query(AgentProfile).filter(AgentProfile.id == run.profile_id).one()
        policy = profile.policy_json or {}
        try:
            owner_access = require_customer_access(
                db,
                customer_id=account.id,
                user={
                    "sub": str(owner.id),
                    "permissions": sorted(delegated_permissions),
                    "roles": sorted(delegated_roles),
                    "_agent_run": {
                        "run_id": run.id,
                        "customer_id": account.id,
                        "max_data_classification": policy.get(
                            "max_data_classification",
                            "internal_business",
                        ),
                        "max_visibility_scope": policy.get(
                            "max_visibility_scope",
                            "customer_team",
                        ),
                    },
                },
                action_permissions={"customer_radar:write", "customer_radar:manage"},
                manage_permissions={"customer_radar:manage"},
            )
        except CustomerAccessDenied:
            owner_access = None
    if actor is not None:
        try:
            actor_access = require_customer_access(
                db,
                customer_id=account.id,
                user={
                    "sub": str(actor.id),
                    "permissions": get_user_permissions(actor),
                    "roles": get_user_roles(actor),
                },
                action_permissions={"customer_radar:write", "customer_radar:manage"},
                manage_permissions={"customer_radar:manage"},
            )
        except CustomerAccessDenied:
            actor_access = None
    if (
        action is None
        or action.owner_user_id != run.owner_user_id
        or live_assignment is None
        or owner_access is None
        or actor_access is None
        or not owner_access.allows_classification("internal_business")
        or not owner_access.allows_visibility("customer_team")
        or (
            action.opportunity_id is not None
            and (
                opportunity is None
                or opportunity.owner_user_id != run.owner_user_id
            )
        )
    ):
        raise ConflictError("复购行动卡原始行动不存在或归属不匹配")
    # A user decision is a business fact. Late Agent output may be accepted for
    # audit, but must not rewrite done/dismissed/snoozed actions.
    if action.status != "pending":
        return
    content = artifact.content_json or {}
    required = ("action_reason", "suggested_next_action", "suggested_message")
    if any(not isinstance(content.get(key), str) for key in required):
        raise ConflictError("复购行动卡缺少可投影字段")
    profile = db.query(AgentProfile).filter(AgentProfile.id == run.profile_id).one()
    action.reason = content["action_reason"]
    action.next_action = content["suggested_next_action"]
    action.suggested_message = content["suggested_message"]
    action.feedback_json = {
        **dict(action.feedback_json or {}),
        "agent_projection_evidence": artifact.evidence_json or [],
        "artifact_id": artifact.id,
    }
    action.source_type = "agent"
    action.agent_run_id = run.id
    action.policy_version = f"{profile.profile_key}-v{profile.version}"
    action.evidence_status = "valid"
    now = beijing_now()
    action.generated_at = now
    action.updated_at = now
    account.profile_input_seq = int(account.profile_input_seq) + 1
    account.updated_at = now
