"""Independent accuracy, applicability and real adoption evidence."""

from app.customer import pcw_errors
from app.customer.pcw_idempotency import run_with_receipt
from app.customer.work_item_service import item_access
from app.customer.work_item_evidence_service import validate_evidence
from app.customer.workbench_models import CustomerDelegation, WorkItemFeedback


def artifact_revision(artifact):
    return int(artifact.content_sha256[:8], 16) or 1


def item_artifacts(db, user, item, access):
    from app.agent_runtime.models import AgentArtifact, AgentRun
    from app.customer.models import CustomerAccount
    account = db.get(CustomerAccount, access.customer_id)
    rows = db.query(AgentArtifact, AgentRun).join(AgentRun, AgentRun.id == AgentArtifact.run_id).filter(
        AgentRun.owner_user_id == access.actor_user_id,
        AgentRun.input_json["work_item_id"].as_integer() == item.id).order_by(AgentArtifact.id.desc()).all()
    results = []
    for artifact, run in rows:
        snapshot = run.input_json or {}
        delegation = db.get(CustomerDelegation, snapshot.get("delegation_id"))
        fresh = bool(item.source_valid and snapshot.get("work_item_input_revision") == item.source_revision
            and delegation and delegation.generation == snapshot.get("delegation_generation")
            and delegation.status in {"active", "needs_decision", "completed"}
            and item.state not in {"paused", "cancelled", "resolved"}
            and snapshot.get("customer_input_seq") == account.profile_input_seq
            and snapshot.get("customer_profile_version_id") == account.current_profile_version_id)
        # Artifacts retain citations; full content is returned only after live customer and source checks.
        from app.agent_runtime.evidence_validation import validate_ark_claim_evidence
        errors = validate_ark_claim_evidence(db, citations=artifact.evidence_json or [], customer_id=access.customer_id,
            profile_version=(artifact.evidence_json[0].get("profile_version") if artifact.evidence_json else None), max_classification=access.max_data_classification,
            max_visibility=access.max_visibility_scope)
        visible = not errors
        results.append({"target_id": f"artifact:{artifact.id}", "target_revision": artifact_revision(artifact),
            "title": artifact.title, "content": artifact.content_json if visible else {"unavailable": "证据不可见或来源变化"},
            "evidence_refs": artifact.evidence_json if visible else [], "source_revision": snapshot.get("work_item_input_revision"),
            "status": "current" if fresh and visible else "stale", "review_status": artifact.validation_status,
            "can_adopt": fresh and visible and artifact.validation_status == "valid" and artifact.decision_status == "accepted"})
    return results


def record_feedback(db, user, item_id, payload, idempotency_key):
    item, access = item_access(db, user, item_id, write=True, lock=True)

    def execute():
        dimension, decision = payload["dimension"], payload["decision"]
        if dimension not in {"accuracy", "applicability", "adoption"} or decision not in {"yes", "no"}:
            raise pcw_errors.bad_request("反馈维度或判断不合法", error_code="FEEDBACK_INVALID")
        target = next((artifact for artifact in item_artifacts(db, user, item, access)
                       if artifact["target_id"] == payload["target_id"]), None)
        if target is None or target["target_revision"] != payload["target_revision"]:
            raise pcw_errors.conflict("目标产物或版本已变化", error_code="FEEDBACK_TARGET_STALE")
        evidence = []
        if payload.get("evidence_refs"):
            evidence = validate_evidence(db, access, payload["evidence_refs"])
        if dimension == "adoption" and decision == "yes":
            if not target["can_adopt"] or not evidence:
                raise pcw_errors.conflict("实际采纳需质量通过且有真实使用依据", error_code="ADOPTION_EVIDENCE_REQUIRED")
        row = db.query(WorkItemFeedback).filter_by(item_id=item.id, actor_user_id=access.actor_user_id,
            target_id=payload["target_id"], target_revision=payload["target_revision"], dimension=dimension).with_for_update().one_or_none()
        if row is None:
            row = WorkItemFeedback(item_id=item.id, actor_user_id=access.actor_user_id,
                target_id=payload["target_id"], target_revision=payload["target_revision"], dimension=dimension)
            db.add(row)
        row.decision = decision
        row.reason = payload.get("reason")
        row.evidence_refs = evidence
        db.flush()
        return {"feedback_id": row.id, "dimension": dimension, "decision": decision}

    result, _ = run_with_receipt(db, actor_user_id=access.actor_user_id, operation_scope=f"item_feedback:{item_id}",
        idempotency_key=idempotency_key, request_payload=payload, execute=execute)
    return result
