"""Batch validation of claim evidence against Ark's provenance graph."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.access_service import CLASSIFICATION_ORDER, VISIBILITY_ORDER
from app.customer.evidence_contract import fact_evidence_content_hash
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.models import (
    CustomerConversation, CustomerFact, CustomerMessage, CustomerOrder,
    CustomerSourceRecord,
)


_INVALID_VERIFICATION = {"disputed", "rejected", "superseded"}
_MAX_FACT_NODES = 64
_MAX_FACT_DEPTH = 8


def _within(value: str, ceiling: str, order: tuple[str, ...]) -> bool:
    return value in order and ceiling in order and order.index(value) <= order.index(ceiling)


def _ids(evidence: dict, key: str) -> set[int] | None:
    values = evidence.get(key, [])
    if not isinstance(values, list) or any(type(value) is not int or value <= 0 for value in values):
        return None
    return set(values)


def _fact_state_errors(fact, *, now, max_classification, max_visibility) -> list[str]:
    errors = []
    if fact.verification_status in _INVALID_VERIFICATION:
        errors.append("verification is invalid")
    if fact.effective_from is not None and fact.effective_from > now:
        errors.append("is not yet effective")
    if fact.effective_to is not None and fact.effective_to <= now:
        errors.append("is no longer effective")
    if fact.expires_at is not None and fact.expires_at <= now:
        errors.append("is expired")
    if not _within(fact.data_classification, max_classification, CLASSIFICATION_ORDER):
        errors.append("exceeds classification scope")
    if not _within(fact.visibility_scope, max_visibility, VISIBILITY_ORDER):
        errors.append("exceeds visibility scope")
    return errors


def _load_fact_graph(db, *, root_ids: set[int], customer_id: int):
    facts, errors, frontier = {}, [], set(root_ids)
    for _depth in range(_MAX_FACT_DEPTH):
        if not frontier:
            break
        if len(facts) + len(frontier) > _MAX_FACT_NODES:
            return facts, ["Ark supporting fact node budget exceeded"]
        rows = db.query(CustomerFact).filter(
            CustomerFact.id.in_(frontier),
            logical_root_predicate(CustomerFact, "fact", customer_id),
        ).all()
        found = {row.id: row for row in rows}
        if frontier - set(found):
            errors.append("Ark supporting fact is missing or crosses customer scope")
        facts.update(found)
        next_ids = set()
        for row in rows:
            ids = _ids(row.evidence_json or {}, "fact_ids")
            if ids is None:
                errors.append(f"Ark fact {row.id} has invalid fact_ids provenance")
            else:
                next_ids.update(ids)
        frontier = next_ids - set(facts)
    if frontier:
        errors.append("Ark supporting fact depth budget exceeded")
    return facts, errors


def _has_cycle(facts: dict[int, CustomerFact], root_ids: Iterable[int]) -> bool:
    visited, active = set(), set()

    def visit(fact_id: int, depth: int) -> bool:
        if fact_id in active or depth > _MAX_FACT_DEPTH:
            return True
        if fact_id in visited:
            return False
        visited.add(fact_id)
        active.add(fact_id)
        fact = facts.get(fact_id)
        children = _ids(fact.evidence_json or {}, "fact_ids") if fact else set()
        if children is None or any(visit(child, depth + 1) for child in children):
            return True
        active.remove(fact_id)
        return False

    return any(visit(fact_id, 1) for fact_id in root_ids)


def _source_errors(source, *, max_classification, max_visibility) -> list[str]:
    if source is None:
        return ["source evidence is unavailable or crosses customer scope"]
    errors = []
    if source.processing_status != "processed":
        errors.append("source evidence is not processed")
    if not _within(source.data_classification, max_classification, CLASSIFICATION_ORDER):
        errors.append("source evidence exceeds classification scope")
    if not _within(source.visibility_scope, max_visibility, VISIBILITY_ORDER):
        errors.append("source evidence exceeds visibility scope")
    return errors


def _layer_errors(fact, evidence: dict) -> list[str]:
    kinds = {
        kind for kind, key in (
            ("source_record", "source_record_ids"), ("conversation", "conversation_ids"),
            ("message", "message_ids"), ("order", "order_ids"), ("fact", "fact_ids"),
        ) if evidence.get(key)
    }
    if fact.fact_layer == "source" and "source_record" not in kinds:
        return ["source fact requires source provenance"]
    if fact.fact_layer == "expressed" and not kinds.intersection({"message", "conversation"}):
        return ["expressed fact requires message or conversation provenance"]
    if fact.fact_layer == "observed":
        allowed = (
            {"order"} if fact.fact_key.startswith("preference.observed.")
            or fact.fact_key == "commercial.has_valid_order" else {"message", "conversation"}
        )
        if not kinds.intersection(allowed):
            return ["observed fact requires direct provenance"]
    if fact.fact_layer == "inferred" and (
        not fact.rule_version or not kinds or kinds != {"fact"}
    ):
        return ["inferred fact requires only supporting facts and a rule version"]
    review = evidence.get("human_review")
    if fact.fact_layer == "confirmed" and (
        not isinstance(review, dict)
        or type(review.get("reviewer_id")) is not int
        or review["reviewer_id"] <= 0
        or not isinstance(review.get("review_reference"), str)
        or not review["review_reference"].strip()
        or fact.reviewed_by != review["reviewer_id"]
        or fact.reviewed_at is None
        or fact.verification_status != "verified"
        or "fact" not in kinds
    ):
        return ["confirmed fact requires a valid review and supporting facts"]
    return []


def _validate_provenance(
    db, *, facts, root_ids, customer_id, max_classification, max_visibility,
) -> list[str]:
    errors = []
    evidence_by_fact = {row.id: row.evidence_json or {} for row in facts.values()}
    keys = ("source_record_ids", "conversation_ids", "message_ids", "order_ids", "fact_ids")
    indexes = {key: set() for key in keys}
    for fact in facts.values():
        evidence = evidence_by_fact[fact.id]
        if fact.source_record_id is not None:
            values = set(evidence.get("source_record_ids") or [])
            values.add(fact.source_record_id)
            evidence = {**evidence, "source_record_ids": sorted(values)}
            evidence_by_fact[fact.id] = evidence
        for key in keys:
            values = _ids(evidence, key)
            if values is None:
                errors.append(f"Ark fact {fact.id} has invalid {key} provenance")
            else:
                indexes[key].update(values)
        errors.extend(f"Ark fact {fact.id} {message}" for message in _layer_errors(fact, evidence))
    if _has_cycle(facts, root_ids):
        errors.append("Ark supporting fact provenance contains a cycle")

    messages = db.query(CustomerMessage).filter(
        CustomerMessage.id.in_(indexes["message_ids"]),
    ).all() if indexes["message_ids"] else []
    messages_by_id = {row.id: row for row in messages}
    conversation_ids = set(indexes["conversation_ids"])
    conversation_ids.update(row.conversation_id for row in messages)
    conversations = db.query(CustomerConversation).filter(
        CustomerConversation.id.in_(conversation_ids),
        logical_root_predicate(CustomerConversation, "conversation", customer_id),
    ).all() if conversation_ids else []
    conversations_by_id = {row.id: row for row in conversations}
    orders = db.query(CustomerOrder).filter(
        CustomerOrder.id.in_(indexes["order_ids"]),
        logical_root_predicate(CustomerOrder, "order", customer_id),
    ).all() if indexes["order_ids"] else []
    orders_by_id = {row.id: row for row in orders}
    source_ids = set(indexes["source_record_ids"])
    source_ids.update(row.source_record_id for row in messages)
    source_ids.update(row.latest_source_record_id for row in conversations if row.latest_source_record_id)
    source_ids.update(row.source_record_id for row in orders)
    sources = db.query(CustomerSourceRecord).filter(
        CustomerSourceRecord.id.in_(source_ids),
        logical_root_predicate(CustomerSourceRecord, "source_record", customer_id),
    ).all() if source_ids else []
    sources_by_id = {row.id: row for row in sources}

    for fact in facts.values():
        evidence = evidence_by_fact[fact.id]
        for source_id in _ids(evidence, "source_record_ids") or ():
            errors.extend(_source_errors(
                sources_by_id.get(source_id), max_classification=max_classification,
                max_visibility=max_visibility,
            ))
        for message_id in _ids(evidence, "message_ids") or ():
            message = messages_by_id.get(message_id)
            if message is None or message.conversation_id not in conversations_by_id:
                errors.append("message evidence is missing or crosses customer scope")
            else:
                errors.extend(_source_errors(
                    sources_by_id.get(message.source_record_id),
                    max_classification=max_classification, max_visibility=max_visibility,
                ))
        for conversation_id in _ids(evidence, "conversation_ids") or ():
            conversation = conversations_by_id.get(conversation_id)
            if conversation is None:
                errors.append("conversation evidence is missing or crosses customer scope")
            else:
                errors.extend(_source_errors(
                    sources_by_id.get(conversation.latest_source_record_id),
                    max_classification=max_classification, max_visibility=max_visibility,
                ))
        for order_id in _ids(evidence, "order_ids") or ():
            order = orders_by_id.get(order_id)
            if order is None:
                errors.append("order evidence is missing or crosses customer scope")
            else:
                errors.extend(_source_errors(
                    sources_by_id.get(order.source_record_id),
                    max_classification=max_classification, max_visibility=max_visibility,
                ))
    return errors


def validate_ark_claim_evidence(
    db: Session, *, citations: list[dict], customer_id: int | None,
    profile_version: int | None, max_classification: str, max_visibility: str,
) -> list[str]:
    if customer_id is None:
        return ["Ark customer scope is missing"]
    errors, fact_ids = [], []
    for index, citation in enumerate(citations):
        ref = str(citation.get("evidence_ref") or "") if isinstance(citation, dict) else ""
        prefix, separator, raw_id = ref.partition(":")
        try:
            fact_id = int(raw_id) if separator and prefix == "fact" else None
        except ValueError:
            fact_id = None
        if fact_id is None or fact_id <= 0:
            errors.append(f"Ark evidence {index + 1} uses unsupported evidence_ref")
        else:
            fact_ids.append(fact_id)
    if errors:
        return errors
    facts, graph_errors = _load_fact_graph(db, root_ids=set(fact_ids), customer_id=customer_id)
    errors.extend(graph_errors)
    now = beijing_now()
    for index, (citation, fact_id) in enumerate(zip(citations, fact_ids, strict=True)):
        fact = facts.get(fact_id)
        if fact is None:
            errors.append(f"Ark evidence {index + 1} is missing or crosses customer scope")
            continue
        expected_hash = fact_evidence_content_hash(
            fact_id=fact.id, value=fact.value_json, fingerprint=fact.fact_fingerprint,
        )
        if citation.get("evidence_content_hash") != expected_hash:
            errors.append(f"Ark evidence {index + 1} content hash does not match current fact")
        if citation.get("customer_id") != customer_id or citation.get("profile_version") != profile_version:
            errors.append(f"Ark evidence {index + 1} crosses customer or profile version")
    for fact in facts.values():
        errors.extend(
            f"Ark fact {fact.id} {message}" for message in _fact_state_errors(
                fact, now=now, max_classification=max_classification,
                max_visibility=max_visibility,
            )
        )
    errors.extend(_validate_provenance(
        db, facts=facts, root_ids=set(fact_ids), customer_id=customer_id,
        max_classification=max_classification, max_visibility=max_visibility,
    ))
    return errors


__all__ = ["validate_ark_claim_evidence"]
