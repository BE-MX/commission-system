"""Write phase and postconditions for customer ownership execution."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.customer import models
from app.customer.ownership_execution_validation import (
    validate_graph_targets,
    validate_transition_graph_targets,
)


class ExecutionPostconditionError(ValueError):
    error_code = "OWNERSHIP_EXECUTION_POSTCONDITION_FAILED"


def _digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(item) for item in parts).encode()).hexdigest()


def _copy(row: object, *, omit: set[str]) -> dict[str, object]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
        if column.name not in omit and column.computed is None
        and not column.info.get("read_only")
    }


def _clone(db: Session, row: object, *, omit: set[str], overrides: Mapping[str, object]):
    values = _copy(row, omit=omit)
    values.update(overrides)
    clone = type(row)(**values)
    db.add(clone)
    return clone


def _assignments(db: Session, section: Mapping[str, Any], actor_id: int, now) -> None:
    for item in section["rebuilds"]:
        source = db.get(models.CustomerAssignment, item["source_id"])
        source.assignment_status = "ended"
        source.effective_to = now
        source.updated_at = now
        _clone(db, source, omit={"id", "active_assignment_key", "active_primary_slot"}, overrides={
            "id": item["new_id"], "customer_id": item["target_customer_id"],
            "user_id": item.get("user_id", source.user_id),
            "assignment_role": item.get("assignment_role", source.assignment_role),
            "assignment_status": "active", "effective_from": now, "effective_to": None,
            "assignment_source": "transfer", "operated_by": actor_id,
            "change_reason": "merge_split_rebuild", "created_at": now, "updated_at": now,
        })


def _contact_relationships(db: Session, section: Mapping[str, Any], now) -> None:
    for item in section["rebuilds"]:
        source = db.get(models.CustomerContactRelationship, item["source_id"])
        source.effective_to = now
        source.updated_at = now
        _clone(db, source, omit={"id", "active_relation_key"}, overrides={
            "id": item["new_id"], "customer_id": item["target_customer_id"],
            "effective_from": now, "effective_to": None,
            "relationship_fingerprint": _digest("contact_relation", item["new_id"]),
            "created_at": now, "updated_at": now,
        })


def _customer_relationships(db: Session, section: Mapping[str, Any], now) -> None:
    for item in section["rebuilds"]:
        source = db.get(models.CustomerRelationship, item["source_id"])
        source.effective_to = now
        source.updated_at = now
        _clone(db, source, omit={"id", "active_relation_key"}, overrides={
            "id": item["new_id"], "from_customer_id": item["from_customer_id"],
            "to_customer_id": item["to_customer_id"], "effective_from": now,
            "effective_to": None,
            "relationship_fingerprint": _digest("customer_relation", item["new_id"]),
            "created_at": now, "updated_at": now,
        })


def _dnc(db: Session, section: Mapping[str, Any], actor_id: int, now) -> None:
    revoked: set[int] = set()
    for item in section["rebuilds"]:
        source = db.get(models.CustomerAnnotation, item["source_id"])
        if source.id not in revoked:
            source.status = "revoked"
            source.revoked_by = actor_id
            source.revoked_at = now
            source.updated_at = now
            revoked.add(source.id)
        if "existing_id" not in item:
            _clone(db, source, omit={"id", "active_dnc_key"}, overrides={
                "id": item["new_id"], "customer_id": item["target_customer_id"],
                "status": "active", "revoked_by": None, "revoked_at": None,
                "authored_by": actor_id, "created_at": now, "updated_at": now,
            })


def _qualifications(db: Session, section: Mapping[str, Any], actor_id: int, now) -> None:
    for item in section["rebuilds"]:
        source = db.get(models.CustomerQualificationReview, item["source_id"])
        source.is_current = False
        _clone(db, source, omit={"id", "current_scope_slot"}, overrides={
            "id": item["new_id"], "customer_id": item["target_customer_id"],
            "review_version": source.review_version + 1,
            "supersedes_review_id": source.id, "is_current": True,
            "decision_request_key": _digest("qualification", item["new_id"]),
            "reviewed_by": actor_id, "reviewed_at": now, "created_at": now,
        })


def _research(db: Session, section: Mapping[str, Any], now) -> None:
    for item in section["rebuilds"]:
        source = db.get(models.CustomerResearchTask, item["source_id"])
        source.task_status = "cancelled"
        source.finished_at = now
        source.updated_at = now
        _clone(db, source, omit={"id"}, overrides={
            "id": item["new_id"], "customer_id": item["target_customer_id"],
            "task_status": "pending", "gate_status": "pending",
            "result_review_status": "pending", "result_schema_version": None,
            "result_json": None, "research_summary": None, "agent_run_id": None,
            "claimed_by": None, "lease_token_hash": None, "lease_expires_at": None,
            "lease_generation": 0, "attempt_count": 0,
            "error_code": None, "error_message": None, "reviewed_by": None,
            "reviewed_at": None, "started_at": None, "finished_at": None,
            "task_fingerprint": _digest("research", item["new_id"]),
            "created_at": now, "updated_at": now,
        })


def apply_transition_plan(db: Session, plan: Mapping[str, Any], actor_id: int, now) -> None:
    _assignments(db, plan["assignments"], actor_id, now)
    _contact_relationships(db, plan["contact_relationships"], now)
    _customer_relationships(db, plan["customer_relationships"], now)
    _dnc(db, plan["dnc"], actor_id, now)
    _qualifications(db, plan["qualifications"], actor_id, now)
    _research(db, plan["research_tasks"], now)


def invalidate_projections(db: Session, customer_ids: set[int]) -> None:
    for model in (models.CustomerAgentContext, models.CustomerListProjection):
        db.query(model).filter(model.customer_id.in_(customer_ids)).delete(
            synchronize_session=False)
    db.query(models.CustomerTargetMatch).filter(
        models.CustomerTargetMatch.customer_id.in_(customer_ids),
        models.CustomerTargetMatch.is_current.is_(True),
    ).delete(synchronize_session=False)


def validate_postconditions(
    db: Session, payload: Mapping[str, Any], plan: Mapping[str, Any], action_type: str,
) -> None:
    validate_graph_targets(db, payload, plan)
    validate_transition_graph_targets(db, payload, plan, rebuilt=True)
    source = payload["source_customer_id"]
    resulting = set(payload["target_customer_ids"])
    if action_type == "split" and payload["retain_source"]:
        resulting.add(source)
    accounts = db.query(models.CustomerAccount).filter(
        models.CustomerAccount.id.in_(resulting)).all()
    if len(accounts) != len(resulting) or any(row.record_status != "active" for row in accounts):
        raise ExecutionPostconditionError()
    affected = {source, *payload["target_customer_ids"]}
    if (
        db.query(models.CustomerAgentContext.customer_id).filter(
            models.CustomerAgentContext.customer_id.in_(affected)).first() is not None
        or db.query(models.CustomerListProjection.customer_id).filter(
            models.CustomerListProjection.customer_id.in_(affected)).first() is not None
        or db.query(models.CustomerTargetMatch.id).filter(
            models.CustomerTargetMatch.customer_id.in_(affected),
            models.CustomerTargetMatch.is_current.is_(True)).first() is not None
    ):
        raise ExecutionPostconditionError()
    for item in payload["ownership_partitions"]:
        owner = db.get(models.CustomerObjectOwnership, (item["object_type"], item["object_id"]))
        if owner is None or owner.current_customer_id != item["target_customer_id"]:
            raise ExecutionPostconditionError()
    if source not in resulting:
        active_checks = (
            db.query(models.CustomerAssignment.id).filter_by(customer_id=source, assignment_status="active"),
            db.query(models.CustomerContactRelationship.id).filter_by(customer_id=source, effective_to=None),
            db.query(models.CustomerRelationship.id).filter(
                ((models.CustomerRelationship.from_customer_id == source)
                 | (models.CustomerRelationship.to_customer_id == source)),
                models.CustomerRelationship.effective_to.is_(None)),
            db.query(models.CustomerAnnotation.id).filter_by(
                customer_id=source, annotation_type="do_not_contact", status="active"),
            db.query(models.CustomerQualificationReview.id).filter_by(customer_id=source, is_current=True),
            db.query(models.CustomerResearchTask.id).filter(
                models.CustomerResearchTask.customer_id == source,
                ~models.CustomerResearchTask.task_status.in_(("completed", "failed", "skipped", "cancelled"))),
        )
        if any(query.first() is not None for query in active_checks):
            raise ExecutionPostconditionError()
    for source_id in plan["dnc"]["source_ids"]:
        old = db.get(models.CustomerAnnotation, source_id)
        for customer_id in resulting:
            exists = db.query(models.CustomerAnnotation.id).filter_by(
                customer_id=customer_id, annotation_type="do_not_contact", status="active",
                policy_scope_type=old.policy_scope_type,
                policy_scope_ref_id=old.policy_scope_ref_id,
            ).first()
            if exists is None:
                raise ExecutionPostconditionError()


__all__ = [
    "ExecutionPostconditionError", "apply_transition_plan",
    "invalidate_projections", "validate_postconditions",
]
