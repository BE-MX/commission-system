"""Read-only business acceptance metrics for Agent Runtime gray release."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.agent_runtime.models import AgentArtifact, AgentEvent, AgentProfile, AgentRun
from app.sales_automation.models import SearchJob


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _profile_ids(db: Session, profile_key: str) -> list[int]:
    return [row[0] for row in db.query(AgentProfile.id).filter(
        AgentProfile.profile_key == profile_key,
    ).all()]


def _latest_explicit_ratings(db: Session, run_ids: list[int]) -> dict[int, str]:
    if not run_ids:
        return {}
    ratings: dict[int, str] = {}
    rows = db.query(AgentEvent).filter(
        AgentEvent.run_id.in_(run_ids),
        AgentEvent.event_type == "user.feedback",
    ).order_by(AgentEvent.run_id, AgentEvent.sequence_no).all()
    for row in rows:
        rating = str((row.payload_json or {}).get("rating") or "")
        if rating:
            ratings[row.run_id] = rating
    return ratings


def _copilot_artifact_is_evidence_bound(artifact: AgentArtifact) -> bool:
    if artifact.validation_status != "valid":
        return False
    content = artifact.content_json or {}
    evidence_ids = {
        str(item.get("tool_call_id"))
        for item in (artifact.evidence_json or [])
        if isinstance(item, dict) and item.get("tool_call_id")
    }
    if not evidence_ids:
        return False
    for field in ("key_findings", "risks", "recommended_actions"):
        for item in content.get(field) or []:
            if not isinstance(item, dict):
                return False
            citations = item.get("evidence_call_ids") or []
            if not citations or any(str(call_id) not in evidence_ids for call_id in citations):
                return False
    return True


def readiness_report(db: Session) -> dict:
    copilot_profile_ids = _profile_ids(db, "customer_order_copilot")
    completed_copilot_runs = db.query(AgentRun).filter(
        AgentRun.profile_id.in_(copilot_profile_ids or [-1]),
        AgentRun.status == "completed",
    ).order_by(AgentRun.id.asc()).all()
    # Only an explicitly labelled, versioned evaluation suite may advance the
    # 30-standard-question gate. Ordinary production questions and duplicate
    # reruns of one case must never inflate business-readiness metrics.
    copilot_by_case: dict[str, AgentRun] = {}
    for row in completed_copilot_runs:
        run_input = row.input_json or {}
        if run_input.get("evaluation_suite") != "customer_order_copilot_v1":
            continue
        case_id = str(run_input.get("evaluation_case_id") or "").strip()
        if case_id:
            # Use the first completed attempt so later cherry-picked reruns do
            # not improve a standard case's quality score after the fact.
            copilot_by_case.setdefault(case_id, row)
    copilot_runs = list(copilot_by_case.values())
    copilot_run_ids = [row.id for row in copilot_runs]
    copilot_artifacts = db.query(AgentArtifact).filter(
        AgentArtifact.run_id.in_(copilot_run_ids or [-1]),
        AgentArtifact.artifact_type == "copilot_answer",
    ).all()
    ratings = _latest_explicit_ratings(db, copilot_run_ids)
    reviewed = len(ratings)
    directly_usable = sum(1 for value in ratings.values() if value == "useful")
    evidence_bound = sum(1 for item in copilot_artifacts if _copilot_artifact_is_evidence_bound(item))
    copilot_evidence_rate = _ratio(evidence_bound, len(copilot_runs))
    copilot_use_rate = _ratio(directly_usable, reviewed)
    copilot_pass = (
        len(copilot_runs) >= 30
        and reviewed >= 30
        and copilot_use_rate >= 0.8
        and copilot_evidence_rate == 1.0
    )

    repurchase_profile_ids = _profile_ids(db, "repurchase_risk_analyst")
    repurchase_run_ids = [row[0] for row in db.query(AgentRun.id).filter(
        AgentRun.profile_id.in_(repurchase_profile_ids or [-1]),
        AgentRun.status == "completed",
    ).all()]
    repurchase_cards = db.query(AgentArtifact).filter(
        AgentArtifact.run_id.in_(repurchase_run_ids or [-1]),
        AgentArtifact.artifact_type == "repurchase_action_card",
    ).all()
    valid_cards = sum(1 for item in repurchase_cards if item.validation_status == "valid")
    repurchase_valid_rate = _ratio(valid_cards, len(repurchase_cards))
    repurchase_pass = len(repurchase_cards) >= 200 and repurchase_valid_rate >= 0.95

    shadow_profile_ids = _profile_ids(db, "sales_discovery_shadow")
    shadow_runs = db.query(AgentRun).filter(
        AgentRun.profile_id.in_(shadow_profile_ids or [-1]),
        AgentRun.status == "completed",
        AgentRun.business_ref_type == "search_job",
    ).all()
    job_ids = {int(row.business_ref_id) for row in shadow_runs if str(row.business_ref_id or "").isdigit()}
    completed_jobs: set[int] = set()
    if job_ids:
        completed_jobs = {row[0] for row in db.query(SearchJob.id).filter(
            SearchJob.id.in_(job_ids),
            SearchJob.status == "completed",
        ).all()}
    shadow_artifact_run_ids = {row[0] for row in db.query(AgentArtifact.run_id).filter(
        AgentArtifact.run_id.in_([item.id for item in shadow_runs] or [-1]),
        AgentArtifact.artifact_type == "sales_discovery_shadow_result",
        AgentArtifact.validation_status == "valid",
    ).all()}
    paired_job_ids = {
        int(row.business_ref_id) for row in shadow_runs
        if row.id in shadow_artifact_run_ids
        and str(row.business_ref_id or "").isdigit()
        and int(row.business_ref_id) in completed_jobs
    }
    paired = len(paired_job_ids)
    shadow_pass = paired >= 50
    all_passed = copilot_pass and repurchase_pass and shadow_pass

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "business_validation_complete": all_passed,
        "copilot": {
            "completed_standard_runs": len(copilot_runs),
            "evaluation_suite": "customer_order_copilot_v1",
            "reviewed_runs": reviewed,
            "directly_usable_runs": directly_usable,
            "direct_use_rate": copilot_use_rate,
            "evidence_bound_runs": evidence_bound,
            "evidence_binding_rate": copilot_evidence_rate,
            "thresholds": {"samples": 30, "reviewed": 30, "direct_use_rate": 0.8, "evidence_binding_rate": 1.0},
            "passed": copilot_pass,
        },
        "repurchase": {
            "cards": len(repurchase_cards),
            "valid_cards": valid_cards,
            "evidence_valid_rate": repurchase_valid_rate,
            "state_preservation_control": "database invariant plus refresh/projection regression",
            "thresholds": {"cards": 200, "evidence_valid_rate": 0.95},
            "passed": repurchase_pass,
        },
        "sales_shadow": {
            "same_input_completed_pairs": paired,
            "comparison_key": "search_job",
            "thresholds": {"pairs": 50},
            "passed": shadow_pass,
        },
        "promotion_decision": "eligible_for_human_review" if all_passed else "remain_in_shadow",
    }
