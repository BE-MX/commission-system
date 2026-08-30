"""Batch validation of claim evidence against Ark's customer truth store."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer.access_service import CLASSIFICATION_ORDER, VISIBILITY_ORDER
from app.customer.evidence_contract import fact_evidence_content_hash
from app.customer.logical_customer_service import logical_root_predicate
from app.customer.models import CustomerFact, CustomerSourceRecord


_INVALID_VERIFICATION = {"disputed", "rejected", "superseded"}


def _within(value: str, ceiling: str, order: tuple[str, ...]) -> bool:
    return value in order and ceiling in order and order.index(value) <= order.index(ceiling)


def validate_ark_claim_evidence(
    db: Session, *, citations: list[dict], customer_id: int | None,
    profile_version: int | None, max_classification: str, max_visibility: str,
) -> list[str]:
    if customer_id is None:
        return ["Ark customer scope is missing"]
    errors: list[str] = []
    fact_ids: list[int] = []
    citation_fact_ids: list[int | None] = []
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
        citation_fact_ids.append(fact_id)
    if errors:
        return errors

    facts = db.query(CustomerFact).filter(
        CustomerFact.id.in_(set(fact_ids)),
        logical_root_predicate(CustomerFact, "fact", customer_id),
    ).all()
    facts_by_id = {row.id: row for row in facts}
    source_ids: set[int] = set()
    for fact in facts:
        if fact.source_record_id is not None:
            source_ids.add(int(fact.source_record_id))
        evidence = fact.evidence_json or {}
        source_ids.update(
            int(value) for value in evidence.get("source_record_ids", [])
            if isinstance(value, int) and value > 0
        )
    sources = db.query(CustomerSourceRecord).filter(
        CustomerSourceRecord.id.in_(source_ids),
        logical_root_predicate(CustomerSourceRecord, "source_record", customer_id),
    ).all() if source_ids else []
    sources_by_id = {row.id: row for row in sources}
    now = beijing_now()

    for index, (citation, fact_id) in enumerate(zip(citations, citation_fact_ids, strict=True)):
        fact = facts_by_id.get(fact_id)
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
        if fact.verification_status in _INVALID_VERIFICATION:
            errors.append(f"Ark evidence {index + 1} verification is invalid")
        if fact.effective_from is not None and fact.effective_from > now:
            errors.append(f"Ark evidence {index + 1} is not yet effective")
        if fact.expires_at is not None and fact.expires_at <= now:
            errors.append(f"Ark evidence {index + 1} is expired")
        if fact.effective_to is not None and fact.effective_to <= now:
            errors.append(f"Ark evidence {index + 1} is no longer effective")
        if not _within(fact.data_classification, max_classification, CLASSIFICATION_ORDER):
            errors.append(f"Ark evidence {index + 1} exceeds classification scope")
        if not _within(fact.visibility_scope, max_visibility, VISIBILITY_ORDER):
            errors.append(f"Ark evidence {index + 1} exceeds visibility scope")
        related_ids = set((fact.evidence_json or {}).get("source_record_ids", []))
        if fact.source_record_id is not None:
            related_ids.add(fact.source_record_id)
        for source_id in related_ids:
            source = sources_by_id.get(source_id)
            if source is None:
                errors.append(f"Ark evidence {index + 1} has unavailable source evidence")
            elif source.processing_status != "processed":
                errors.append(f"Ark evidence {index + 1} source is not processed")
            elif (
                not _within(source.data_classification, max_classification, CLASSIFICATION_ORDER)
                or not _within(source.visibility_scope, max_visibility, VISIBILITY_ORDER)
            ):
                errors.append(f"Ark evidence {index + 1} source exceeds scope")
    return errors


__all__ = ["validate_ark_claim_evidence"]
