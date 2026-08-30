"""Frozen input contract and live-basis checks for merge/split execution."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Mapping

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer import models
from app.customer.contracts import (
    OBJECT_OWNERSHIP_REGISTRY,
    OBJECT_OWNERSHIP_REGISTRY_VERSION,
)
from app.customer.ownership_execution_validation import (
    DYNAMIC_REF_FIELDS,
    ROOT_LIST_REF_FIELDS,
    ROOT_REF_FIELDS,
    TERMINAL_RESEARCH,
    TRANSITION_KEYS,
    validate_graph_targets,
    validate_projected_conflicts,
    validate_transition_graph_targets,
    validate_transition_plan,
)


ROOT_MODELS = {
    "name": models.CustomerName,
    "external_identity": models.CustomerExternalIdentity,
    "contact_point": models.CustomerContactPoint,
    "source_record": models.CustomerSourceRecord,
    "fact": models.CustomerFact,
    "conversation": models.CustomerConversation,
    "order": models.CustomerOrder,
    "research_task": models.CustomerResearchTask,
    "search_result": models.SearchResult,
    "opportunity": models.CustomerOpportunity,
    "action": models.CustomerAction,
    "annotation": models.CustomerAnnotation,
    "acquisition_attribution": models.CustomerAcquisitionAttribution,
}
if set(ROOT_MODELS) != set(OBJECT_OWNERSHIP_REGISTRY):  # pragma: no cover
    raise RuntimeError("ownership execution roots do not match the versioned registry")
COMMON_PAYLOAD_KEYS = frozenset({
    "ownership_registry_version", "source_customer_id", "target_customer_ids",
    "source_profile_version_id", "source_profile_input_seq", "target_profile_versions",
    "evidence_fact_ids", "root_inventory", "ownership_partitions", "transition_plan",
    "proposal_redirects", "reason_code", "reason_text",
})
OPEN_PROPOSAL_STATUSES = frozenset({"draft", "pending", "approved"})
PARTITION_KEYS = frozenset({
    "object_type", "object_id", "expected_storage_customer_id",
    "expected_current_customer_id", "expected_ownership_version", "target_customer_id",
})


class ExecutionContractError(ValueError):
    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _action_hash(proposal: models.CustomerChangeProposal, payload: Mapping[str, Any]) -> str:
    return _canonical_hash({
        "action_type": proposal.action_type,
        "customer_id": proposal.customer_id,
        "target_customer_id": proposal.target_customer_id,
        "payload_json": payload,
        "profile_version_id": proposal.profile_version_id,
        "evidence_fact_ids": sorted(set(proposal.evidence_fact_ids or [])),
    })


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _overlay_map(db: Session) -> dict[tuple[str, int], models.CustomerObjectOwnership]:
    return {
        (row.object_type, int(row.object_id)): row
        for row in db.query(models.CustomerObjectOwnership).all()
    }


def _row_owner(
    db: Session,
    object_type: str,
    row: object,
    overlays: Mapping[tuple[str, int], models.CustomerObjectOwnership],
) -> tuple[int | None, int | None, int]:
    overlay = overlays.get((object_type, int(row.id)))
    if overlay is not None:
        return int(overlay.current_customer_id), int(overlay.storage_customer_id), int(overlay.ownership_version)
    customer_id = getattr(row, "customer_id", None)
    if customer_id is not None:
        return int(customer_id), int(customer_id), 0
    source_record_id = getattr(row, "source_record_id", None)
    if source_record_id is not None:
        source = db.get(models.CustomerSourceRecord, source_record_id)
        storage = int(source.customer_id) if source is not None and source.customer_id else None
        return storage, storage, 0
    contact_id = getattr(row, "contact_id", None)
    if contact_id is None:
        return None, None, 0
    rows = db.query(models.CustomerContactRelationship.customer_id).filter(
        models.CustomerContactRelationship.contact_id == contact_id,
        models.CustomerContactRelationship.verification_status.in_(("identified", "verified")),
        models.CustomerContactRelationship.effective_to.is_(None),
        or_(
            models.CustomerContactRelationship.effective_from.is_(None),
            models.CustomerContactRelationship.effective_from <= beijing_now(),
        ),
    ).all()
    owners = {int(item[0]) for item in rows}
    if len(owners) != 1:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_STORAGE_AMBIGUOUS")
    storage = next(iter(owners))
    return storage, storage, 0


def _eligible_for_overlay(object_type: str, row: object) -> bool:
    if object_type == "annotation":
        return not (
            row.annotation_type == "do_not_contact" and row.status == "active"
        )
    if object_type == "research_task":
        return row.task_status in TERMINAL_RESEARCH
    return True


def _graph_inventory(
    db: Session, roots: Mapping[str, list[int]], source_customer_id: int,
) -> dict[str, object]:
    graph: dict[str, object] = {}
    root_edges: dict[str, list[list[object]]] = {}
    dynamic_by_kind = {kind: (type_field, id_field)
                       for kind, type_field, id_field in DYNAMIC_REF_FIELDS}
    for kind, refs in ROOT_REF_FIELDS.items():
        rows = [] if not roots[kind] else db.query(ROOT_MODELS[kind]).filter(
            ROOT_MODELS[kind].id.in_(roots[kind])).order_by(ROOT_MODELS[kind].id).all()
        dynamic = dynamic_by_kind.get(kind)
        root_edges[kind] = [[
            int(row.id),
            *[getattr(row, field) for field, _ in refs],
            *([] if dynamic is None else [getattr(row, dynamic[0]), getattr(row, dynamic[1])]),
        ] for row in rows]
    for kind, (type_field, id_field) in dynamic_by_kind.items():
        if kind in root_edges:
            continue
        rows = [] if not roots[kind] else db.query(ROOT_MODELS[kind]).filter(
            ROOT_MODELS[kind].id.in_(roots[kind])).order_by(ROOT_MODELS[kind].id).all()
        root_edges[kind] = [[int(row.id), getattr(row, type_field), getattr(row, id_field)]
                            for row in rows]
    for kind, refs in ROOT_LIST_REF_FIELDS.items():
        rows = [] if not roots[kind] else db.query(ROOT_MODELS[kind]).filter(
            ROOT_MODELS[kind].id.in_(roots[kind])).order_by(ROOT_MODELS[kind].id).all()
        existing = {item[0]: item for item in root_edges.get(kind, [])}
        for row in rows:
            existing.setdefault(int(row.id), [int(row.id)]).extend(
                [list(getattr(row, field) or []) for field, _ in refs])
        root_edges[kind] = [existing[row_id] for row_id in sorted(existing)]
    for row in ([] if not roots["fact"] else db.query(models.CustomerFact).filter(
        models.CustomerFact.id.in_(roots["fact"])).order_by(models.CustomerFact.id).all()):
        next(item for item in root_edges["fact"] if item[0] == row.id).extend(
            [row.subject_type, row.subject_id, row.evidence_json or {}])
    graph["root_edges"] = root_edges
    graph["transition_edges"] = {
        "contact_relationships": [
            [row.id, row.customer_id, row.source_fact_id]
            for row in db.query(models.CustomerContactRelationship).filter(
                models.CustomerContactRelationship.customer_id == source_customer_id,
                models.CustomerContactRelationship.effective_to.is_(None),
            ).order_by(models.CustomerContactRelationship.id).all()
        ],
        "customer_relationships": [
            [row.id, row.from_customer_id, row.to_customer_id, row.source_fact_id]
            for row in db.query(models.CustomerRelationship).filter(
                (models.CustomerRelationship.from_customer_id == source_customer_id)
                | (models.CustomerRelationship.to_customer_id == source_customer_id),
                models.CustomerRelationship.effective_to.is_(None),
            ).order_by(models.CustomerRelationship.id).all()
        ],
    }
    source_ids = set(roots["source_record"])
    child_specs = (
        ("messages", models.CustomerMessage, "conversation_id", "conversation"),
        ("order_items", models.CustomerOrderItem, "order_id", "order"),
        ("opportunity_events", models.CustomerOpportunityEvent, "opportunity_id", "opportunity"),
        ("search_result_sources", models.SearchResultSource, "result_id", "search_result"),
    )
    for name, model, parent_field, root_type in child_specs:
        parent_ids = roots[root_type]
        rows = [] if not parent_ids else db.query(model).filter(
            getattr(model, parent_field).in_(parent_ids)
        ).order_by(model.id).all()
        if any(
            getattr(row, "source_record_id", None) is not None
            and row.source_record_id not in source_ids
            for row in rows
        ):
            raise ExecutionContractError("OWNERSHIP_EXECUTION_GRAPH_CLOSURE_INVALID")
        graph[name] = [
            [int(row.id), int(getattr(row, parent_field)), getattr(row, "source_record_id", None),
             getattr(row, "customer_id", None), getattr(row, "evidence_fact_ids", None)]
            for row in rows
        ]
    fact_ids = roots["fact"]
    evidence_rows = (
            [] if not fact_ids else db.query(models.CustomerFactEvidenceLink).filter(
                models.CustomerFactEvidenceLink.fact_id.in_(fact_ids)
            ).order_by(models.CustomerFactEvidenceLink.id).all()
    )
    message_ids = {item[0] for item in graph["messages"]}
    if any(
        (row.source_record_id is not None and row.source_record_id not in source_ids)
        or (row.message_id is not None and row.message_id not in message_ids)
        or (row.order_id is not None and row.order_id not in set(roots["order"]))
        or (row.supporting_fact_id is not None and row.supporting_fact_id not in set(fact_ids))
        for row in evidence_rows
    ):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_GRAPH_CLOSURE_INVALID")
    graph["fact_evidence_links"] = [
        [row.id, row.customer_id, row.fact_id, row.source_record_id, row.message_id,
         row.order_id, row.supporting_fact_id]
        for row in evidence_rows
    ]
    conflict_rows = (
            [] if not fact_ids else db.query(models.CustomerFactConflict).filter(
                (models.CustomerFactConflict.left_fact_id.in_(fact_ids))
                | (models.CustomerFactConflict.right_fact_id.in_(fact_ids))
            ).order_by(models.CustomerFactConflict.id).all()
    )
    graph["fact_conflicts"] = [
        [row.id, row.customer_id, row.left_fact_id, row.right_fact_id, row.resolution_fact_id]
        for row in conflict_rows
    ]
    return graph


def build_execution_basis(
    db: Session, *, source_customer_id: int, target_customer_ids: list[int],
) -> dict[str, object]:
    """Freeze all roots, child closure and CAS versions for one pairwise action."""
    if not _positive_int(source_customer_id) or (
        not isinstance(target_customer_ids, list)
        or len(target_customer_ids) != 1
        or not _positive_int(target_customer_ids[0])
        or target_customer_ids[0] == source_customer_id
    ):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_SCOPE_INVALID")
    overlays = _overlay_map(db)
    roots: dict[str, list[int]] = {key: [] for key in ROOT_MODELS}
    partitions: list[dict[str, object]] = []
    target = target_customer_ids[0]
    for object_type, model in ROOT_MODELS.items():
        for row in db.query(model).order_by(model.id).all():
            current, storage, version = _row_owner(db, object_type, row, overlays)
            if current != source_customer_id:
                continue
            roots[object_type].append(int(row.id))
            if _eligible_for_overlay(object_type, row):
                partitions.append({
                    "object_type": object_type,
                    "object_id": int(row.id),
                    "expected_storage_customer_id": storage,
                    "expected_current_customer_id": source_customer_id,
                    "expected_ownership_version": version,
                    "target_customer_id": target,
                })
    graph = _graph_inventory(db, roots, source_customer_id)
    inventory = {
        "registry_version": OBJECT_OWNERSHIP_REGISTRY_VERSION,
        "roots": {
            key: {"count": len(ids), "sorted_ids_hash": _canonical_hash(ids)}
            for key, ids in roots.items()
        },
        "graph_hash": _canonical_hash({"roots": roots, "children": graph}),
    }
    return {
        "ownership_registry_version": OBJECT_OWNERSHIP_REGISTRY_VERSION,
        "root_inventory": inventory,
        "ownership_partitions": partitions,
    }


def _partitions_match_live_basis(
    payload: Mapping[str, Any], expected: list[dict[str, object]], *, action_type: str,
) -> bool:
    actual = payload.get("ownership_partitions")
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    expected_by_key = {(item["object_type"], item["object_id"]): item for item in expected}
    seen: set[tuple[object, object]] = set()
    allowed_targets = {payload["source_customer_id"], *payload["target_customer_ids"]}
    used_non_source: set[int] = set()
    for item in actual:
        if not isinstance(item, Mapping) or set(item) != PARTITION_KEYS:
            return False
        key = (item["object_type"], item["object_id"])
        basis = expected_by_key.get(key)
        if basis is None or key in seen:
            return False
        seen.add(key)
        if any(
            item[field] != basis[field]
            for field in PARTITION_KEYS - {"target_customer_id"}
        ) or item["target_customer_id"] not in allowed_targets:
            return False
        if action_type == "merge" and item["target_customer_id"] != payload["keep_customer_id"]:
            return False
        if item["target_customer_id"] != payload["source_customer_id"]:
            used_non_source.add(item["target_customer_id"])
    required_targets = set(payload["target_customer_ids"]) if expected_by_key else set()
    return seen == set(expected_by_key) and used_non_source == required_targets


def validate_execution_contract(
    db: Session, proposal: models.CustomerChangeProposal,
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate every approved byte and live basis before the first write."""
    if proposal.status != "approved" or not proposal.approved_action_hash:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_APPROVAL_INVALID")
    if proposal.action_type not in {"merge", "split"}:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_ACTION_INVALID")
    if proposal.payload_schema_version != f"customer_{proposal.action_type}_v1":
        raise ExecutionContractError("OWNERSHIP_EXECUTION_SCHEMA_INVALID")
    payload = proposal.payload_json
    action_key = "keep_customer_id" if proposal.action_type == "merge" else "retain_source"
    if not isinstance(payload, Mapping) or set(payload) != COMMON_PAYLOAD_KEYS | {action_key}:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_PAYLOAD_INVALID")
    targets = payload["target_customer_ids"]
    if targets != [proposal.target_customer_id] or payload["source_customer_id"] != proposal.customer_id:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_SCOPE_INVALID")
    if proposal.action_type == "merge" and payload[action_key] != proposal.target_customer_id:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_SCOPE_INVALID")
    if proposal.action_type == "split" and type(payload[action_key]) is not bool:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_SCOPE_INVALID")
    if payload["ownership_registry_version"] != OBJECT_OWNERSHIP_REGISTRY_VERSION:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_REGISTRY_STALE")
    if not isinstance(payload["reason_code"], str) or not payload["reason_code"].strip() or (
        not isinstance(payload["reason_text"], str) or not payload["reason_text"].strip()
    ):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_REASON_INVALID")
    if not secrets.compare_digest(_action_hash(proposal, payload), proposal.action_hash) or not secrets.compare_digest(
        proposal.approved_action_hash, proposal.action_hash
    ):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_ACTION_HASH_INVALID")
    evidence = payload["evidence_fact_ids"]
    if evidence != sorted(set(proposal.evidence_fact_ids or [])) or not evidence:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_EVIDENCE_INVALID")
    live_evidence = db.query(models.CustomerFact.id).filter(
        models.CustomerFact.id.in_(evidence),
        models.CustomerFact.customer_id == proposal.customer_id,
        models.CustomerFact.effective_to.is_(None),
        models.CustomerFact.verification_status.in_(("verified", "candidate", "unverified")),
    ).all()
    if {int(item[0]) for item in live_evidence} != set(evidence):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_EVIDENCE_INVALID")
    basis = build_execution_basis(
        db, source_customer_id=proposal.customer_id, target_customer_ids=targets,
    )
    if payload["root_inventory"] != basis["root_inventory"] or not _partitions_match_live_basis(
        payload, basis["ownership_partitions"], action_type=proposal.action_type,
    ):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_INVENTORY_STALE")
    allowed = set(targets)
    if proposal.action_type == "split" and payload["retain_source"]:
        allowed.add(proposal.customer_id)
    if any(item["target_customer_id"] not in allowed for item in payload["ownership_partitions"]):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_DESTINATION_INVALID")
    plan = validate_transition_plan(db, payload, action_type=proposal.action_type)
    validate_graph_targets(db, payload, plan)
    validate_transition_graph_targets(db, payload, plan)
    validate_projected_conflicts(db, payload, plan, proposal.action_type)
    redirects = payload["proposal_redirects"]
    target_profiles = {
        item["customer_id"]: item["profile_version_id"]
        for item in payload["target_profile_versions"]
    }
    if proposal.action_type == "split" and payload["retain_source"]:
        target_profiles[proposal.customer_id] = payload["source_profile_version_id"]
    if not isinstance(redirects, list) or any(
        not isinstance(item, Mapping)
        or set(item) != {
            "proposal_id", "target_customer_id", "target_profile_version_id",
        }
        or not _positive_int(item["proposal_id"])
        or item["target_customer_id"] not in target_profiles
        or item["target_profile_version_id"] != target_profiles.get(item["target_customer_id"])
        for item in redirects
    ):
        raise ExecutionContractError("OWNERSHIP_EXECUTION_REDIRECT_PLAN_INVALID")
    redirect_ids = [int(item["proposal_id"]) for item in redirects]
    if len(set(redirect_ids)) != len(redirect_ids) or proposal.id in redirect_ids:
        raise ExecutionContractError("OWNERSHIP_EXECUTION_REDIRECT_PLAN_INVALID")
    if redirect_ids:
        affected = {proposal.customer_id, *targets}
        rows = db.query(models.CustomerChangeProposal).filter(
            models.CustomerChangeProposal.id.in_(redirect_ids),
            models.CustomerChangeProposal.status.in_(OPEN_PROPOSAL_STATUSES),
            (models.CustomerChangeProposal.customer_id.in_(affected))
            | (models.CustomerChangeProposal.target_customer_id.in_(affected)),
        ).all()
        if {int(row.id) for row in rows} != set(redirect_ids):
            raise ExecutionContractError("OWNERSHIP_EXECUTION_REDIRECT_PLAN_INVALID")
    return dict(payload), {"transition_plan": plan, "proposal_redirects": redirects}


__all__ = [
    "ExecutionContractError",
    "build_execution_basis",
    "validate_execution_contract",
]
