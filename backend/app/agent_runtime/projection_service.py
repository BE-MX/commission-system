"""Human-confirmed Agent artifact projections into existing business records."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.agent_runtime.errors import ConflictError
from app.agent_runtime.models import AgentArtifact, AgentProfile, AgentRun
from app.insight.models import CustomerAction


def project_accepted_artifact(
    db: Session,
    artifact: AgentArtifact,
    run: AgentRun,
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
    action = db.query(CustomerAction).filter(CustomerAction.id == action_id).with_for_update().one_or_none()
    if action is None or action.owner_user_id != run.owner_user_id:
        raise ConflictError("复购行动卡原始行动不存在或归属不匹配")
    # A user decision is a business fact. Late Agent output may be accepted for
    # audit, but must not rewrite done/dismissed/snoozed actions.
    if action.action_status != "pending":
        return
    content = artifact.content_json or {}
    required = ("action_reason", "suggested_next_action", "suggested_message")
    if any(not isinstance(content.get(key), str) for key in required):
        raise ConflictError("复购行动卡缺少可投影字段")
    profile = db.query(AgentProfile).filter(AgentProfile.id == run.profile_id).one()
    action.action_reason = content["action_reason"]
    action.suggested_next_action = content["suggested_next_action"]
    action.suggested_message = content["suggested_message"]
    action.source_evidence = artifact.evidence_json or []
    action.source_type = "dsh"
    action.source_run_id = run.id
    action.source_fingerprint = f"dsh:{run.id}:{artifact.content_sha256}"[:64]
    action.policy_version = f"{profile.profile_key}-v{profile.version}"
    action.evidence_status = "valid"
    action.generated_at = datetime.utcnow()

