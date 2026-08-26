"""Business evaluation catalogs, controlled launches and readiness metrics."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from app.core.time import beijing_today
from app.core.time import beijing_now
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.agent_runtime import service as runtime_service
from app.agent_runtime.errors import ConflictError, ForbiddenError, NotFoundError
from app.agent_runtime.evaluation_cases import (
    COPILOT_CASES_BY_ID,
    COPILOT_EVALUATION_CASES,
    COPILOT_EVALUATION_SUITE,
)
from app.agent_runtime.evaluation_contract import copilot_contract
from app.agent_runtime.models import AgentArtifact, AgentEvent, AgentProfile, AgentRun
from app.auth.models import ArkUser
from app.insight.models import CustomerAction, CustomerProfile, CustomerProfileEvent
from app.order_intelligence import service as order_service
from app.sales_automation.models import SearchJob


logger = logging.getLogger("commission.agent_runtime.evaluation")


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


def _copilot_evaluation_runs(
    db: Session, *, contract: dict, completed_only: bool = False,
) -> list[AgentRun]:
    query = db.query(AgentRun).filter(
        AgentRun.profile_id == contract["profile_id"],
        AgentRun.input_json["evaluation_suite"].as_string() == COPILOT_EVALUATION_SUITE,
        AgentRun.input_json["evaluation_contract_hash"].as_string() == contract["hash"],
    )
    if completed_only:
        query = query.filter(AgentRun.status == "completed")
    return query.order_by(AgentRun.id.asc()).all()


def _canonical_case_for_run(run: AgentRun, *, contract_hash: str) -> dict | None:
    run_input = run.input_json or {}
    if run_input.get("evaluation_contract_hash") != contract_hash:
        return None
    case = COPILOT_CASES_BY_ID.get(str(run_input.get("evaluation_case_id") or ""))
    if case is None or run_input.get("question") != case["question"]:
        return None
    customer_id = str(run_input.get("customer_profile_id") or "")
    if (
        run.business_ref_type != "customer_profile"
        or not customer_id
        or str(run.business_ref_id or "") != customer_id
    ):
        return None
    return case


def _same_evaluation_run(run: AgentRun, *, run_input: dict, profile_ids: set[int]) -> bool:
    return bool(
        run.profile_id in profile_ids
        and run.input_json == run_input
        and run.business_ref_type == "customer_profile"
        and str(run.business_ref_id or "") == str(run_input["customer_profile_id"])
    )


def copilot_case_catalog(db: Session) -> dict:
    contract = copilot_contract(db)
    attempts: dict[str, list[AgentRun]] = {}
    for run in _copilot_evaluation_runs(db, contract=contract):
        case = _canonical_case_for_run(run, contract_hash=contract["hash"])
        if case is not None:
            attempts.setdefault(case["case_id"], []).append(run)
    rows = []
    for case in COPILOT_EVALUATION_CASES:
        case_attempts = attempts.get(case["case_id"], [])
        completed = next((item for item in case_attempts if item.status == "completed"), None)
        latest = case_attempts[-1] if case_attempts else None
        rows.append({
            **case,
            "attempt_count": len(case_attempts),
            "completed_run_id": completed.id if completed else None,
            "latest_run_id": latest.id if latest else None,
            "latest_status": latest.status if latest else "not_started",
            "customer_profile_id": (
                (latest.input_json or {}).get("customer_profile_id") if latest else None
            ),
        })
    return {
        "suite": COPILOT_EVALUATION_SUITE,
        "cohort_id": f"{COPILOT_EVALUATION_SUITE}:{contract['hash'][:12]}",
        "evaluation_contract_hash": contract["hash"],
        "contract_ready": contract["ready"],
        "profile_version": contract["profile_version"],
        "model": contract["model"],
        "total_cases": len(rows),
        "completed_cases": sum(1 for item in rows if item["completed_run_id"] is not None),
        "cases": rows,
    }


def _customer_scope(
    db: Session,
    *,
    user_id: int,
    permissions: set[str],
    roles: set[str],
):
    can_read = bool(
        "super_admin" in roles
        or {"customer_radar:read", "customer_radar:write", "customer_radar:manage"} & permissions
    )
    if not can_read:
        raise ForbiddenError("启动副驾驶评测需要客户经营雷达查看权限")
    query = db.query(CustomerProfile).filter(CustomerProfile.status == "active")
    if "super_admin" not in roles and "customer_radar:manage" not in permissions:
        query = query.filter(CustomerProfile.owner_user_id == user_id)
    return query


def _preflight_case(
    db: Session,
    *,
    case: dict,
    customer: CustomerProfile,
    user_id: int,
    permissions: set[str],
    roles: set[str],
) -> None:
    required = set(case["requires"])
    if "profile_events" in required and not db.query(CustomerProfileEvent.id).filter(
        CustomerProfileEvent.profile_id == customer.id,
    ).first():
        raise ConflictError("该标准题需要客户画像事件，请更换有近期事件的客户")
    if "customer_actions" in required and not db.query(CustomerAction.id).filter(
        CustomerAction.profile_id == customer.id,
    ).first():
        raise ConflictError("该标准题需要客户行动记录，请更换有行动记录的客户")
    needs_orders = bool({"order_history", "repurchase_analysis"} & required)
    if not needs_orders:
        return
    if "super_admin" not in roles and not {
        "order_intelligence:read", "order_intelligence:read_all",
    } & permissions:
        raise ForbiddenError("该标准题需要订单经营分析查看权限")
    if not customer.customer_external_id:
        raise ConflictError("该标准题需要已绑定 OKKI 客户 ID 的客户")
    identity = {
        "sub": str(user_id), "permissions": sorted(permissions), "roles": sorted(roles),
    }
    try:
        scope = order_service.resolve_scope(db, identity)
        end = beijing_today()
        start = end - timedelta(days=1095)
        timeline = order_service.get_customer_order_timeline(
            db, scope, customer.customer_external_id, start, end, limit=50,
        )
        if int((timeline.get("summary") or {}).get("orders") or 0) <= 0:
            raise ConflictError("该标准题需要近三年内存在有效订单的客户")
        if "repurchase_analysis" in required:
            result = order_service.get_customer_repurchase_analysis(
                db, scope, customer.customer_external_id, start, end,
            )
            analysis = result.get("analysis") or {}
            typical_cycle = analysis.get("typical_cycle_days")
            if (
                not result.get("found")
                or not isinstance(typical_cycle, (int, float))
                or typical_cycle <= 0
                or analysis.get("risk_status") == "insufficient_data"
            ):
                raise ConflictError("该标准题需要具备可计算复购周期的客户")
    except (ForbiddenError, ConflictError):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("副驾驶标准评测数据预检失败 type=%s", type(exc).__name__)
        raise ConflictError("无法确认该客户的订单评测数据，请检查 OKKI 绑定与数据同步") from None


def search_copilot_evaluation_customers(
    db: Session,
    *,
    user_id: int,
    permissions: set[str],
    roles: set[str],
    keyword: str | None,
    limit: int,
) -> list[dict]:
    query = _customer_scope(
        db, user_id=user_id, permissions=permissions, roles=roles,
    )
    cleaned = (keyword or "").strip()
    if cleaned:
        pattern = f"%{cleaned}%"
        query = query.filter(or_(
            CustomerProfile.customer_name.ilike(pattern),
            CustomerProfile.customer_company.ilike(pattern),
            CustomerProfile.customer_external_id.ilike(pattern),
        ))
    rows = query.order_by(
        CustomerProfile.priority_score.desc(), CustomerProfile.updated_at.desc(),
    ).limit(limit).all()
    return [{
        "id": row.id,
        "customer_name": row.customer_name,
        "customer_company": row.customer_company,
        "customer_region": row.customer_region,
        "priority_score": row.priority_score,
        "has_order_binding": bool(row.customer_external_id),
        "has_profile_events": bool(row.total_events),
    } for row in rows]


def start_copilot_evaluation_case(
    db: Session,
    *,
    case_id: str,
    customer_profile_id: int,
    idempotency_key: str,
    user_id: int,
    permissions: set[str],
    roles: set[str],
) -> AgentRun:
    case = COPILOT_CASES_BY_ID.get(case_id)
    if case is None:
        raise NotFoundError("副驾驶标准评测题不存在")
    customer = _customer_scope(
        db, user_id=user_id, permissions=permissions, roles=roles,
    ).filter(CustomerProfile.id == customer_profile_id).one_or_none()
    if customer is None:
        raise NotFoundError("客户画像不存在或不在当前账号数据范围内")
    run_input = {
        "question": case["question"],
        "customer_profile_id": customer.id,
        "evaluation_suite": COPILOT_EVALUATION_SUITE,
        "evaluation_case_id": case_id,
    }
    contract = copilot_contract(db)
    if not contract["ready"]:
        raise ConflictError("副驾驶评测模型 Preset 未就绪，请先完成 direct/openai 配置")
    run_input["evaluation_contract_hash"] = contract["hash"]
    copilot_profile_ids = {contract["profile_id"]}
    existing = db.query(AgentRun).filter(
        AgentRun.owner_user_id == user_id,
        AgentRun.idempotency_key == idempotency_key,
    ).one_or_none()
    if existing is not None:
        if not _same_evaluation_run(
            existing, run_input=run_input, profile_ids=copilot_profile_ids,
        ):
            raise ConflictError("相同幂等键对应不同标准评测任务")
        return existing
    _preflight_case(
        db,
        case=case,
        customer=customer,
        user_id=user_id,
        permissions=permissions,
        roles=roles,
    )
    # Serialize the entire evaluation Session+Run transaction by owner. This
    # makes retries idempotent without committing an empty Session first.
    if db.query(ArkUser).filter(ArkUser.id == user_id).with_for_update().one_or_none() is None:
        raise NotFoundError("Agent 任务所有者不存在")
    existing = db.query(AgentRun).filter(
        AgentRun.owner_user_id == user_id,
        AgentRun.idempotency_key == idempotency_key,
    ).with_for_update().one_or_none()
    if existing is not None:
        if not _same_evaluation_run(
            existing, run_input=run_input, profile_ids=copilot_profile_ids,
        ):
            raise ConflictError("相同幂等键对应不同标准评测任务")
        return existing

    label = customer.customer_company or customer.customer_name or f"客户 #{customer.id}"
    session = runtime_service.create_session(db, {
        "profile_key": "customer_order_copilot",
        "title": f"标准评测 {case_id} · {label}"[:255],
        "context_type": "customer",
        "context_id": str(customer.id),
    }, user_id=user_id, commit=False)
    try:
        return runtime_service.create_run(
            db,
            session.id,
            {
                "idempotency_key": idempotency_key,
                "input": run_input,
                "trigger_type": "user",
                "business_ref_type": "customer_profile",
                "business_ref_id": str(customer.id),
            },
            user_id=user_id,
            permissions=sorted(permissions),
            roles=sorted(roles),
            evaluation_initiated=True,
        )
    except Exception:
        db.rollback()
        raise


def readiness_report(db: Session) -> dict:
    contract = copilot_contract(db)
    completed_copilot_runs = _copilot_evaluation_runs(
        db, contract=contract, completed_only=True,
    )
    # Only an explicitly labelled, versioned evaluation suite may advance the
    # 30-standard-question gate. Ordinary production questions and duplicate
    # reruns of one case must never inflate business-readiness metrics.
    copilot_by_case: dict[str, AgentRun] = {}
    for row in completed_copilot_runs:
        case = _canonical_case_for_run(row, contract_hash=contract["hash"])
        if case is not None:
            # Use the first completed attempt so later cherry-picked reruns do
            # not improve a standard case's quality score after the fact.
            copilot_by_case.setdefault(case["case_id"], row)
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
        "generated_at": beijing_now().isoformat(),
        "business_validation_complete": all_passed,
        "copilot": {
            "completed_standard_runs": len(copilot_runs),
            "evaluation_suite": COPILOT_EVALUATION_SUITE,
            "cohort_id": f"{COPILOT_EVALUATION_SUITE}:{contract['hash'][:12]}",
            "evaluation_contract_hash": contract["hash"],
            "contract_ready": contract["ready"],
            "profile_version": contract["profile_version"],
            "model": contract["model"],
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
