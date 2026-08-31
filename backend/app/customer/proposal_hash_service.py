"""Atomic action-hash updates shared by proposal rebase and redirects."""

import hashlib
import json

from sqlalchemy.exc import IntegrityError

from app.customer.models import CustomerChangeProposal


class ProposalActionHashConflict(ValueError):
    pass


def canonical_action_hash(
    *, action_type: str, customer_id: int, target_customer_id: int | None,
    payload_json: object, profile_version_id: int, evidence_fact_ids: list[int],
) -> str:
    body = {
        "action_type": action_type,
        "customer_id": customer_id,
        "target_customer_id": target_customer_id,
        "payload_json": payload_json,
        "profile_version_id": profile_version_id,
        "evidence_fact_ids": sorted(set(evidence_fact_ids)),
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def is_action_hash_unique_conflict(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower()
    return "action_hash" in message and ("unique" in message or "duplicate" in message)


def _action_hash_conflict_exists(db, *, hashes: set[str], excluded_ids: set[int]) -> bool:
    return db.query(CustomerChangeProposal.id).filter(
        CustomerChangeProposal.action_hash.in_(hashes),
        CustomerChangeProposal.id.notin_(excluded_ids),
    ).first() is not None


def apply_action_hash_updates(
    db, updates: list[tuple[CustomerChangeProposal, str, dict]], *, savepoint: bool,
) -> None:
    hashes = {action_hash for _row, action_hash, _values in updates}
    ids = {row.id for row, _action_hash, _values in updates}
    if len(hashes) != len(updates) or _action_hash_conflict_exists(
        db, hashes=hashes, excluded_ids=ids,
    ):
        raise ProposalActionHashConflict
    def apply():
        for row, action_hash, values in updates:
            for field, value in values.items():
                setattr(row, field, value)
            row.action_hash = action_hash
        db.flush()

    try:
        if savepoint:
            with db.begin_nested():
                apply()
        else:
            apply()
    except IntegrityError as exc:
        if not savepoint:
            db.rollback()
        if not is_action_hash_unique_conflict(exc):
            raise
        raise ProposalActionHashConflict from exc
