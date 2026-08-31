"""Projected-state validation for customer ownership execution."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.customer import models


TERMINAL_RESEARCH = frozenset({"completed", "failed", "skipped", "cancelled"})
TRANSITION_KEYS = (
    "assignments", "contact_relationships", "customer_relationships",
    "dnc", "qualifications", "research_tasks",
)
ROOT_REF_FIELDS = {
    "name": (("source_record_id", "source_record"),),
    "external_identity": (("source_record_id", "source_record"),),
    "contact_point": (("source_record_id", "source_record"),),
    "fact": (("source_record_id", "source_record"), ("supersedes_fact_id", "fact")),
    "conversation": (("latest_source_record_id", "source_record"),),
    "order": (("source_record_id", "source_record"),),
    "opportunity": (("linked_order_id", "order"),),
    "action": (("opportunity_id", "opportunity"),),
    "annotation": (("target_fact_id", "fact"),),
    "acquisition_attribution": (
        ("research_task_id", "research_task"), ("opportunity_id", "opportunity"),
        ("order_id", "order"),
    ),
}
DYNAMIC_REF_FIELDS = (
    ("research_task", "source_ref_type", "source_ref_id"),
    ("opportunity", "source_ref_type", "source_ref_id"),
    ("acquisition_attribution", "origin_ref_type", "origin_ref_id"),
)
ROOT_LIST_REF_FIELDS = {
    "research_task": (("evidence_fact_ids", "fact"),),
    "opportunity": (("evidence_fact_ids", "fact"),),
    "action": (("evidence_fact_ids", "fact"),),
}


def _fail(code: str = "OWNERSHIP_EXECUTION_TRANSITION_PLAN_INVALID") -> None:
    from app.customer.ownership_execution_contract import ExecutionContractError
    raise ExecutionContractError(code)


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


def _active_ids(db: Session, source_id: int) -> dict[str, list[int]]:
    return {
        "assignments": sorted(row.id for row in db.query(models.CustomerAssignment.id).filter_by(
            customer_id=source_id, assignment_status="active").all()),
        "contact_relationships": sorted(row.id for row in db.query(models.CustomerContactRelationship.id).filter(
            models.CustomerContactRelationship.customer_id == source_id,
            models.CustomerContactRelationship.effective_to.is_(None)).all()),
        "customer_relationships": sorted(row.id for row in db.query(models.CustomerRelationship.id).filter(
            (models.CustomerRelationship.from_customer_id == source_id)
            | (models.CustomerRelationship.to_customer_id == source_id),
            models.CustomerRelationship.effective_to.is_(None)).all()),
        "dnc": sorted(row.id for row in db.query(models.CustomerAnnotation.id).filter_by(
            customer_id=source_id, annotation_type="do_not_contact", status="active").all()),
        "qualifications": sorted(row.id for row in db.query(models.CustomerQualificationReview.id).filter_by(
            customer_id=source_id, is_current=True).all()),
        "research_tasks": sorted(row.id for row in db.query(models.CustomerResearchTask.id).filter(
            models.CustomerResearchTask.customer_id == source_id,
            ~models.CustomerResearchTask.task_status.in_(TERMINAL_RESEARCH)).all()),
    }


def _result_customers(payload: Mapping[str, Any], action_type: str) -> set[int]:
    result = set(payload["target_customer_ids"])
    if action_type == "split" and payload["retain_source"]:
        result.add(payload["source_customer_id"])
    return result


def _customer_relation_destinations(
    db: Session, item: Mapping[str, int], source_id: int, allowed: set[int],
) -> set[int]:
    source = db.get(models.CustomerRelationship, item["source_id"])
    if source is None:
        _fail()
    original = (int(source.from_customer_id), int(source.to_customer_id))
    proposed = (item["from_customer_id"], item["to_customer_id"])
    replacements: set[int] = set()
    for old, new in zip(original, proposed):
        if old == source_id:
            if new not in allowed:
                _fail("OWNERSHIP_EXECUTION_DESTINATION_INVALID")
            replacements.add(new)
        elif new != old:
            _fail()
    if not replacements or proposed[0] == proposed[1]:
        _fail()
    return replacements


def validate_transition_plan(
    db: Session, payload: Mapping[str, Any], *, action_type: str,
) -> dict[str, object]:
    source_id = payload["source_customer_id"]
    allowed = _result_customers(payload, action_type)
    plan = payload.get("transition_plan")
    if not isinstance(plan, Mapping) or set(plan) != set(TRANSITION_KEYS):
        _fail()
    active = _active_ids(db, source_id)
    model_by_key = {
        "assignments": models.CustomerAssignment,
        "contact_relationships": models.CustomerContactRelationship,
        "customer_relationships": models.CustomerRelationship,
        "dnc": models.CustomerAnnotation,
        "qualifications": models.CustomerQualificationReview,
        "research_tasks": models.CustomerResearchTask,
    }
    for key in TRANSITION_KEYS:
        section = plan[key]
        if not isinstance(section, Mapping) or set(section) != {"source_ids", "rebuilds"}:
            _fail()
        source_ids, rebuilds = section["source_ids"], section["rebuilds"]
        if source_ids != active[key] or not isinstance(rebuilds, list):
            _fail("OWNERSHIP_EXECUTION_TRANSITION_PLAN_INCOMPLETE")
        destinations = {row_id: set() for row_id in source_ids}
        reserved: set[int] = set()
        seen: set[tuple[int, ...]] = set()
        for item in rebuilds:
            normal = {"source_id", "new_id", "target_customer_id"}
            assignment = normal | {"user_id", "assignment_role"}
            relation = {"source_id", "new_id", "from_customer_id", "to_customer_id"}
            existing_dnc = {"source_id", "existing_id", "target_customer_id"}
            expected = relation if key == "customer_relationships" else (
                existing_dnc if key == "dnc" and isinstance(item, Mapping)
                and "existing_id" in item else assignment if key == "assignments"
                and isinstance(item, Mapping) and "user_id" in item else normal
            )
            if not isinstance(item, Mapping) or set(item) != expected or any(
                not _positive(item[field]) for field in expected - {"assignment_role"}
            ) or (key == "assignments" and "assignment_role" in item
                  and item["assignment_role"] not in {"primary", "collaborator"}):
                _fail()
            if item["source_id"] not in destinations:
                _fail()
            new_id = item.get("new_id")
            if new_id is not None and (new_id in reserved or new_id in destinations):
                _fail()
            if new_id is not None:
                reserved.add(new_id)
            item_destinations = (
                _customer_relation_destinations(db, item, source_id, allowed)
                if key == "customer_relationships" else {item["target_customer_id"]}
            )
            if not item_destinations <= allowed:
                _fail("OWNERSHIP_EXECUTION_DESTINATION_INVALID")
            signature = (item["source_id"], *sorted(item_destinations))
            if signature in seen:
                _fail()
            seen.add(signature)
            if key == "dnc" and "existing_id" in item:
                source_dnc = db.get(models.CustomerAnnotation, item["source_id"])
                existing = db.get(models.CustomerAnnotation, item["existing_id"])
                if item["existing_id"] == item["source_id"] or source_dnc is None or (
                    existing is None or existing.customer_id != item["target_customer_id"]
                    or existing.annotation_type != "do_not_contact" or existing.status != "active"
                    or existing.policy_scope_type != source_dnc.policy_scope_type
                    or existing.policy_scope_ref_id != source_dnc.policy_scope_ref_id
                ):
                    _fail()
            elif key == "dnc":
                source_dnc = db.get(models.CustomerAnnotation, item["source_id"])
                duplicate = db.query(models.CustomerAnnotation.id).filter_by(
                    customer_id=item["target_customer_id"],
                    annotation_type="do_not_contact", status="active",
                    policy_scope_type=source_dnc.policy_scope_type,
                    policy_scope_ref_id=source_dnc.policy_scope_ref_id,
                ).filter(models.CustomerAnnotation.id != item["source_id"]).first()
                if duplicate is not None:
                    _fail()
            destinations[item["source_id"]].update(item_destinations)
        if any(not value for value in destinations.values()):
            _fail("OWNERSHIP_EXECUTION_TRANSITION_PLAN_INCOMPLETE")
        if reserved and db.query(model_by_key[key].id).filter(
            model_by_key[key].id.in_(reserved)).first() is not None:
            _fail()
        if key == "dnc" and any(value != allowed for value in destinations.values()):
            _fail("OWNERSHIP_EXECUTION_TRANSITION_PLAN_INCOMPLETE")
    return dict(plan)


def _partition_targets(payload: Mapping[str, Any]) -> dict[tuple[str, int], int]:
    return {
        (item["object_type"], item["object_id"]): item["target_customer_id"]
        for item in payload["ownership_partitions"]
    }


def validate_graph_targets(
    db: Session, payload: Mapping[str, Any], plan: Mapping[str, Any] | None = None,
) -> None:
    target = _partition_targets(payload)
    from app.customer.ownership_execution_contract import ROOT_MODELS
    overlays = {
        (row.object_type, int(row.object_id)): int(row.current_customer_id)
        for row in db.query(models.CustomerObjectOwnership).all()
    }

    def owner(kind: str, row_id: int | None) -> int | None:
        if row_id is None:
            return None
        if kind == "message":
            message = db.get(models.CustomerMessage, int(row_id))
            return owner("conversation", message.conversation_id) if message else None
        key = (kind, int(row_id))
        if key in target:
            return target[key]
        if key in overlays:
            return overlays[key]
        model = ROOT_MODELS[kind]
        row = db.get(model, int(row_id))
        if row is None:
            return None
        customer_id = getattr(row, "customer_id", None)
        if customer_id is not None:
            return int(customer_id)
        source_record_id = getattr(row, "source_record_id", None)
        if source_record_id is not None:
            return owner("source_record", source_record_id)
        return None

    def same(values: list[int | None]) -> None:
        present = {value for value in values if value is not None}
        if len(present) > 1:
            _fail("OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT")

    def historical_research(task_id: int | None) -> bool:
        if task_id is None or plan is None:
            return False
        rebuilds = plan["research_tasks"]["rebuilds"]
        return bool(
            int(task_id) in plan["research_tasks"]["source_ids"]
            and any(item["source_id"] == int(task_id) for item in rebuilds)
        )

    for kind, refs in ROOT_REF_FIELDS.items():
        ids = [row_id for (row_kind, row_id), _ in target.items() if row_kind == kind]
        for row in ([] if not ids else db.query(ROOT_MODELS[kind]).filter(
            ROOT_MODELS[kind].id.in_(ids)).all()):
            for field, linked_kind in refs:
                if (kind == "acquisition_attribution" and field == "research_task_id"
                        and historical_research(getattr(row, field))):
                    continue
                same([owner(kind, row.id), owner(linked_kind, getattr(row, field))])
    for kind, refs in ROOT_LIST_REF_FIELDS.items():
        ids = [row_id for (row_kind, row_id), _ in target.items() if row_kind == kind]
        for row in ([] if not ids else db.query(ROOT_MODELS[kind]).filter(
            ROOT_MODELS[kind].id.in_(ids)).all()):
            for field, linked_kind in refs:
                for linked_id in getattr(row, field) or []:
                    same([owner(kind, row.id), owner(linked_kind, linked_id)])
    ref_aliases = {
        "customer_source_record": "source_record", "source_record": "source_record",
        "conversation": "conversation", "order": "order", "research_task": "research_task",
        "search_result": "search_result", "opportunity": "opportunity",
        "message": "message",
    }
    for kind, type_field, id_field in DYNAMIC_REF_FIELDS:
        ids = [row_id for (row_kind, row_id), _ in target.items() if row_kind == kind]
        for row in ([] if not ids else db.query(ROOT_MODELS[kind]).filter(
            ROOT_MODELS[kind].id.in_(ids)).all()):
            linked_kind = ref_aliases.get(getattr(row, type_field))
            linked_id = getattr(row, id_field)
            if (kind == "acquisition_attribution" and linked_kind == "research_task"
                    and historical_research(linked_id)):
                continue
            if linked_kind is not None and linked_id is not None:
                try:
                    linked_id = int(linked_id)
                except (TypeError, ValueError):
                    _fail("OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT")
                same([owner(kind, row.id), owner(linked_kind, linked_id)])
    child_specs = (
        (models.CustomerMessage, "conversation_id", "conversation"),
        (models.CustomerOrderItem, "order_id", "order"),
        (models.CustomerOpportunityEvent, "opportunity_id", "opportunity"),
        (models.SearchResultSource, "result_id", "search_result"),
    )
    for model, parent_field, parent_kind in child_specs:
        parent_ids = [row_id for (kind, row_id), _ in target.items() if kind == parent_kind]
        for row in ([] if not parent_ids else db.query(model).filter(
            getattr(model, parent_field).in_(parent_ids)).all()):
            same([owner(parent_kind, getattr(row, parent_field)),
                  owner("source_record", getattr(row, "source_record_id", None))])
            for fact_id in getattr(row, "evidence_fact_ids", None) or []:
                same([owner(parent_kind, getattr(row, parent_field)), owner("fact", fact_id)])
    fact_ids = [row_id for (kind, row_id), _ in target.items() if kind == "fact"]
    for row in ([] if not fact_ids else db.query(models.CustomerFactEvidenceLink).filter(
        models.CustomerFactEvidenceLink.fact_id.in_(fact_ids)).all()):
        message = db.get(models.CustomerMessage, row.message_id) if row.message_id else None
        same([owner("fact", row.fact_id), owner("source_record", row.source_record_id),
              owner("conversation", message.conversation_id if message else None),
              owner("order", row.order_id), owner("fact", row.supporting_fact_id)])
    for fact_id in fact_ids:
        fact = db.get(models.CustomerFact, fact_id)
        if fact.subject_type in {"conversation", "order", "opportunity"}:
            same([owner("fact", fact.id), owner(fact.subject_type, fact.subject_id)])
        evidence = fact.evidence_json or {}
        for field, kind in (
            ("source_record_ids", "source_record"), ("message_ids", "message"),
            ("order_ids", "order"), ("fact_ids", "fact"),
        ):
            for linked_id in evidence.get(field, ()):
                same([owner("fact", fact.id), owner(kind, linked_id)])
    for row in ([] if not fact_ids else db.query(models.CustomerFactConflict).filter(
        (models.CustomerFactConflict.left_fact_id.in_(fact_ids))
        | (models.CustomerFactConflict.right_fact_id.in_(fact_ids))).all()):
        same([owner("fact", row.left_fact_id), owner("fact", row.right_fact_id),
              owner("fact", row.resolution_fact_id)])


def validate_transition_graph_targets(
    db: Session, payload: Mapping[str, Any], plan: Mapping[str, Any], *, rebuilt: bool = False,
) -> None:
    target = _partition_targets(payload)
    overlays = {
        (row.object_type, int(row.object_id)): int(row.current_customer_id)
        for row in db.query(models.CustomerObjectOwnership).all()
    }

    def fact_owner(fact_id: int | None) -> int | None:
        if fact_id is None:
            return None
        fact = db.get(models.CustomerFact, fact_id)
        return target.get(("fact", fact_id), overlays.get(("fact", fact_id), fact.customer_id))

    for section in ("contact_relationships", "customer_relationships"):
        model = (models.CustomerContactRelationship if section == "contact_relationships"
                 else models.CustomerRelationship)
        for item in plan[section]["rebuilds"]:
            source = db.get(model, item["source_id"])
            row = db.get(model, item["new_id"]) if rebuilt else source
            if fact_owner(source.source_fact_id) not in (None, *(
                [(row.customer_id if rebuilt else item["target_customer_id"])]
                if section == "contact_relationships" else [
                    item["from_customer_id"] if source.from_customer_id == payload["source_customer_id"]
                    else item["to_customer_id"]
                ]
            )):
                _fail("OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT")
    for item in plan["research_tasks"]["rebuilds"]:
        row = db.get(models.CustomerResearchTask, item["new_id"] if rebuilt else item["source_id"])
        if any(fact_owner(fact_id) != item["target_customer_id"]
               for fact_id in row.evidence_fact_ids or []):
            _fail("OWNERSHIP_EXECUTION_GRAPH_TARGET_CONFLICT")


def validate_projected_conflicts(
    db: Session, payload: Mapping[str, Any], plan: Mapping[str, Any], action_type: str,
) -> None:
    affected = {payload["source_customer_id"], *payload["target_customer_ids"]}
    target = _partition_targets(payload)
    identities: dict[tuple[int, str], set[str]] = {}
    overlay_owners = {
        int(row.object_id): int(row.current_customer_id)
        for row in db.query(models.CustomerObjectOwnership).filter(
            models.CustomerObjectOwnership.object_type == "external_identity",
            models.CustomerObjectOwnership.current_customer_id.in_(affected),
        ).all()
    }
    projected_ids = {
        row_id for (kind, row_id) in target if kind == "external_identity"
    } | set(overlay_owners)
    for row in db.query(models.CustomerExternalIdentity).filter(
        (models.CustomerExternalIdentity.customer_id.in_(affected))
        | (models.CustomerExternalIdentity.id.in_(projected_ids)),
        models.CustomerExternalIdentity.status == "active",
        models.CustomerExternalIdentity.verification_status == "verified",
        (models.CustomerExternalIdentity.identity_strength == "strong")
        | models.CustomerExternalIdentity.is_primary.is_(True)).all():
        final = target.get(
            ("external_identity", int(row.id)),
            overlay_owners.get(int(row.id), int(row.customer_id)),
        )
        identities.setdefault((final, row.identifier_type), set()).add(row.normalized_value)
    if any(len(values) > 1 for values in identities.values()):
        _fail("OWNERSHIP_EXECUTION_IDENTITY_CONFLICT")
    source_assignment_ids = set(plan["assignments"]["source_ids"])
    primaries: dict[int, list[int]] = {}
    for row in db.query(models.CustomerAssignment).filter(
        models.CustomerAssignment.customer_id.in_(affected),
        models.CustomerAssignment.assignment_status == "active",
        models.CustomerAssignment.assignment_role == "primary").all():
        if row.id not in source_assignment_ids:
            primaries.setdefault(int(row.customer_id), []).append(int(row.user_id))
    for item in plan["assignments"]["rebuilds"]:
        source_row = db.get(models.CustomerAssignment, item["source_id"])
        role = item.get("assignment_role", source_row.assignment_role)
        if role == "primary":
            primaries.setdefault(item["target_customer_id"], []).append(
                int(item.get("user_id", source_row.user_id)))
    if any(len(users) > 1 for users in primaries.values()):
        _fail("OWNERSHIP_EXECUTION_PRIMARY_CONFLICT")


__all__ = [
    "DYNAMIC_REF_FIELDS", "ROOT_LIST_REF_FIELDS", "ROOT_REF_FIELDS",
    "TERMINAL_RESEARCH", "TRANSITION_KEYS",
    "validate_graph_targets",
    "validate_projected_conflicts", "validate_transition_graph_targets",
    "validate_transition_plan",
]
