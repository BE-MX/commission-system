"""Resolve immutable storage ownership into current logical customer ownership."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import func, or_, tuple_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer import models
from app.customer.contracts import OBJECT_OWNERSHIP_REGISTRY
from app.customer.ownership_contract_service import (
    OwnershipContractError,
    require_approved_partition,
    require_overlay_eligibility,
)


class CustomerOwnershipError(ValueError):
    def __init__(self, error_code: str, message: str = "Customer ownership rejected"):
        super().__init__(error_code)
        self.error_code = error_code
        self.message = message


class CustomerOwnershipRetryRequired(CustomerOwnershipError):
    requires_new_transaction = True

    def __init__(self):
        super().__init__("RETRY_NEW_TRANSACTION")


@dataclass(frozen=True, slots=True)
class ObjectReference:
    object_type: str
    object_id: int


@dataclass(frozen=True, slots=True)
class _ObjectAdapter:
    model: type[Any]
    subject_owned: bool = False


_OBJECT_ADAPTERS = {
    "name": _ObjectAdapter(models.CustomerName),
    "external_identity": _ObjectAdapter(models.CustomerExternalIdentity, True),
    "contact_point": _ObjectAdapter(models.CustomerContactPoint, True),
    "source_record": _ObjectAdapter(models.CustomerSourceRecord),
    "fact": _ObjectAdapter(models.CustomerFact),
    "conversation": _ObjectAdapter(models.CustomerConversation),
    "order": _ObjectAdapter(models.CustomerOrder),
    "research_task": _ObjectAdapter(models.CustomerResearchTask),
    "search_result": _ObjectAdapter(models.SearchResult),
    "opportunity": _ObjectAdapter(models.CustomerOpportunity),
    "action": _ObjectAdapter(models.CustomerAction),
    "annotation": _ObjectAdapter(models.CustomerAnnotation),
    "acquisition_attribution": _ObjectAdapter(models.CustomerAcquisitionAttribution),
}
if set(_OBJECT_ADAPTERS) != set(OBJECT_OWNERSHIP_REGISTRY) or any(  # pragma: no cover
    adapter.subject_owned
    != (OBJECT_OWNERSHIP_REGISTRY[key].storage_mode == "subject")
    for key, adapter in _OBJECT_ADAPTERS.items()
):
    raise RuntimeError("ownership object adapters do not match the registry")


def effective_customer_id_expression(storage_customer_id: Any, overlay_customer_id: Any):
    return func.coalesce(overlay_customer_id, storage_customer_id)


def _adapter(object_type: object) -> _ObjectAdapter:
    if not isinstance(object_type, str) or object_type not in _OBJECT_ADAPTERS:
        raise CustomerOwnershipError("OWNERSHIP_OBJECT_TYPE_NOT_REGISTERED")
    return _OBJECT_ADAPTERS[object_type]


def _reference(object_type: object, object_id: object) -> ObjectReference:
    _adapter(object_type)
    if type(object_id) is not int or object_id <= 0:
        raise CustomerOwnershipError("OWNERSHIP_OBJECT_ID_INVALID")
    return ObjectReference(object_type, object_id)


def _overlay(db: Session, ref: ObjectReference, *, lock: bool):
    query = db.query(models.CustomerObjectOwnership).filter_by(
        object_type=ref.object_type,
        object_id=ref.object_id,
    )
    return (query.with_for_update() if lock else query).one_or_none()


def _object(db: Session, ref: ObjectReference, *, lock: bool):
    adapter = _adapter(ref.object_type)
    query = db.query(adapter.model).filter(adapter.model.id == ref.object_id)
    row = (query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise CustomerOwnershipError("OWNERSHIP_OBJECT_NOT_FOUND")
    return adapter, row


def _initial_storage(db: Session, adapter: _ObjectAdapter, row: object, *, lock: bool) -> int:
    customer_id = getattr(row, "customer_id", None)
    if customer_id is not None:
        return int(customer_id)
    if not adapter.subject_owned:
        raise CustomerOwnershipError("OWNERSHIP_STORAGE_CUSTOMER_UNRESOLVED")
    source_record_id = getattr(row, "source_record_id", None)
    if source_record_id is not None:
        query = db.query(models.CustomerSourceRecord).filter_by(id=source_record_id)
        source = (query.with_for_update() if lock else query).one_or_none()
        if source is not None and source.customer_id is not None:
            return int(source.customer_id)
        raise CustomerOwnershipError("OWNERSHIP_STORAGE_CUSTOMER_UNRESOLVED")
    contact_id = getattr(row, "contact_id", None)
    if contact_id is None:
        raise CustomerOwnershipError("OWNERSHIP_STORAGE_CUSTOMER_UNRESOLVED")
    now = beijing_now()
    query = db.query(models.CustomerContactRelationship.customer_id).filter(
        models.CustomerContactRelationship.contact_id == contact_id,
        models.CustomerContactRelationship.verification_status.in_(("identified", "verified")),
        models.CustomerContactRelationship.effective_to.is_(None),
        or_(
            models.CustomerContactRelationship.effective_from.is_(None),
            models.CustomerContactRelationship.effective_from <= now,
        ),
    )
    if lock:
        query = query.with_for_update()
    candidates = {int(item[0]) for item in query.all()}
    if not candidates:
        raise CustomerOwnershipError("OWNERSHIP_STORAGE_CUSTOMER_UNRESOLVED")
    if len(candidates) != 1:
        raise CustomerOwnershipError("OWNERSHIP_STORAGE_CUSTOMER_AMBIGUOUS")
    return next(iter(candidates))


def get_effective_owner(db: Session, object_type: str, object_id: int) -> int | None:
    ref = _reference(object_type, object_id)
    overlay = _overlay(db, ref, lock=False)
    try:
        adapter, row = _object(db, ref, lock=False)
    except CustomerOwnershipError as exc:
        if exc.error_code == "OWNERSHIP_OBJECT_NOT_FOUND":
            return None
        raise
    if overlay is not None:
        return int(overlay.current_customer_id)
    return _initial_storage(db, adapter, row, lock=False)


def require_effective_owner(db: Session, object_type: str, object_id: int) -> int:
    owner = get_effective_owner(db, object_type, object_id)
    if owner is None:
        raise CustomerOwnershipError("OWNERSHIP_OBJECT_NOT_FOUND")
    return owner


def resolve_effective_owners(
    db: Session,
    references: Iterable[ObjectReference],
) -> dict[ObjectReference, int]:
    normalized = {_reference(item.object_type, item.object_id) for item in references}
    if not normalized:
        return {}
    overlay_rows = db.query(models.CustomerObjectOwnership).filter(
        tuple_(
            models.CustomerObjectOwnership.object_type,
            models.CustomerObjectOwnership.object_id,
        ).in_([(item.object_type, item.object_id) for item in normalized]),
    ).all()
    overlays = {ObjectReference(row.object_type, int(row.object_id)): row for row in overlay_rows}
    grouped: dict[str, set[int]] = defaultdict(set)
    for ref in normalized:
        grouped[ref.object_type].add(ref.object_id)
    objects: dict[ObjectReference, object] = {}
    for object_type, ids in grouped.items():
        adapter = _adapter(object_type)
        for row in db.query(adapter.model).filter(adapter.model.id.in_(ids)).all():
            objects[ObjectReference(object_type, int(row.id))] = row
    if set(objects) != normalized:
        raise CustomerOwnershipError("OWNERSHIP_OBJECT_NOT_FOUND")
    result = {}
    for ref in sorted(normalized, key=lambda item: (item.object_type, item.object_id)):
        if ref in overlays:
            result[ref] = int(overlays[ref].current_customer_id)
        else:
            result[ref] = _initial_storage(db, _adapter(ref.object_type), objects[ref], lock=False)
    return result


def _retryable_operational_error(exc: OperationalError) -> bool:
    args = getattr(exc.orig, "args", ())
    code = args[0] if args else None
    text = str(exc.orig).casefold()
    return code in {1205, 1213, "40001"} or any(
        marker in text for marker in ("deadlock", "lock wait timeout", "serialization failure", "40001")
    )


def _ownership_duplicate(exc: IntegrityError) -> bool:
    text = str(exc.orig).casefold()
    return "ark_customer_object_ownerships" in text and any(
        marker in text for marker in ("unique", "duplicate", "primary key")
    )


def _cas(
    db: Session,
    *,
    object_type: str,
    object_id: int,
    storage_customer_id: int,
    expected_current_customer_id: int,
    current_customer_id: int,
    expected_version: int,
    change_proposal_id: int,
    action_type: str,
):
    if action_type not in {"merge", "split"}:
        raise CustomerOwnershipError("OWNERSHIP_ACTION_TYPE_INVALID")
    if type(expected_version) is not int or expected_version < 0:
        raise CustomerOwnershipError("OWNERSHIP_VERSION_INVALID")
    for value, code in (
        (storage_customer_id, "OWNERSHIP_STORAGE_CUSTOMER_ID_INVALID"),
        (expected_current_customer_id, "OWNERSHIP_CURRENT_CUSTOMER_ID_INVALID"),
        (current_customer_id, "OWNERSHIP_CURRENT_CUSTOMER_ID_INVALID"),
        (change_proposal_id, "OWNERSHIP_PROPOSAL_ID_INVALID"),
    ):
        if type(value) is not int or value <= 0:
            raise CustomerOwnershipError(code)
    ref = _reference(object_type, object_id)
    proposal = db.query(models.CustomerChangeProposal).filter_by(
        id=change_proposal_id,
    ).with_for_update().one_or_none()
    if proposal is None:
        raise CustomerOwnershipError("OWNERSHIP_PROPOSAL_NOT_FOUND")
    if proposal.action_type != action_type:
        raise CustomerOwnershipError("OWNERSHIP_PROPOSAL_ACTION_MISMATCH")
    try:
        require_approved_partition(
            proposal,
            object_type=object_type,
            object_id=object_id,
            expected_storage_customer_id=storage_customer_id,
            expected_current_customer_id=expected_current_customer_id,
            expected_ownership_version=expected_version,
            target_customer_id=current_customer_id,
        )
    except OwnershipContractError as exc:
        raise CustomerOwnershipError(exc.error_code) from exc
    scope = {proposal.customer_id, *proposal.payload_json["target_customer_ids"]}
    locked_ids = {
        int(item[0])
        for item in db.query(models.CustomerAccount.id).filter(
            models.CustomerAccount.id.in_(scope),
        ).order_by(models.CustomerAccount.id).with_for_update().all()
    }
    if locked_ids != scope:
        raise CustomerOwnershipError("OWNERSHIP_CUSTOMER_NOT_FOUND")
    overlay = _overlay(db, ref, lock=True)
    adapter, object_row = _object(db, ref, lock=True)
    try:
        require_overlay_eligibility(object_type, object_row)
    except OwnershipContractError as exc:
        raise CustomerOwnershipError(exc.error_code) from exc
    if overlay is None:
        if expected_version != 0:
            raise CustomerOwnershipError("OWNERSHIP_VERSION_CONFLICT")
        actual_storage = _initial_storage(db, adapter, object_row, lock=True)
        if actual_storage != storage_customer_id:
            raise CustomerOwnershipError("OWNERSHIP_STORAGE_CUSTOMER_MISMATCH")
        if expected_current_customer_id != actual_storage:
            raise CustomerOwnershipError("OWNERSHIP_CURRENT_CUSTOMER_MISMATCH")
        now = beijing_now()
        overlay = models.CustomerObjectOwnership(
            object_type=object_type,
            object_id=object_id,
            storage_customer_id=storage_customer_id,
            current_customer_id=current_customer_id,
            ownership_version=1,
            last_change_proposal_id=change_proposal_id,
            last_action_type=action_type,
            created_at=now,
            updated_at=now,
        )
        db.add(overlay)
    else:
        if overlay.storage_customer_id != storage_customer_id:
            raise CustomerOwnershipError("OWNERSHIP_STORAGE_CUSTOMER_MISMATCH")
        if overlay.current_customer_id != expected_current_customer_id:
            raise CustomerOwnershipError("OWNERSHIP_CURRENT_CUSTOMER_MISMATCH")
        if overlay.ownership_version != expected_version:
            raise CustomerOwnershipError("OWNERSHIP_VERSION_CONFLICT")
        overlay.current_customer_id = current_customer_id
        overlay.ownership_version += 1
        overlay.last_change_proposal_id = change_proposal_id
        overlay.last_action_type = action_type
        overlay.updated_at = beijing_now()
    db.flush()
    return overlay


def compare_and_set_effective_owner(db: Session, **kwargs):
    """CAS one action-hashed approved partition; caller owns commit."""
    try:
        return _cas(db, **kwargs)
    except IntegrityError as exc:
        duplicate = _ownership_duplicate(exc)
        db.rollback()
        if duplicate:
            raise CustomerOwnershipError("OWNERSHIP_VERSION_CONFLICT") from exc
        raise
    except OperationalError as exc:
        if not _retryable_operational_error(exc):
            raise
        db.rollback()
        raise CustomerOwnershipRetryRequired() from exc


__all__ = [
    "CustomerOwnershipError",
    "CustomerOwnershipRetryRequired",
    "ObjectReference",
    "compare_and_set_effective_owner",
    "effective_customer_id_expression",
    "get_effective_owner",
    "require_effective_owner",
    "resolve_effective_owners",
]
