"""Canonical customer aliases and set-based logical business-root reads."""

from __future__ import annotations

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.customer import models


_ROOT_MODELS = {
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
_SUBJECT_ROOTS = frozenset({"external_identity", "contact_point"})


def resolve_canonical_customer_id(
    db: Session,
    requested_customer_id: int,
) -> int | None:
    """Resolve a merged alias to one active account, rejecting broken chains."""
    if type(requested_customer_id) is not int or requested_customer_id <= 0:
        return None
    current_id = requested_customer_id
    visited: set[int] = set()
    while current_id not in visited:
        visited.add(current_id)
        row = db.query(
            models.CustomerAccount.id,
            models.CustomerAccount.record_status,
            models.CustomerAccount.merged_into_customer_id,
        ).filter(models.CustomerAccount.id == current_id).one_or_none()
        if row is None:
            return None
        if row.record_status == "active":
            return int(row.id)
        if row.record_status != "merged" or row.merged_into_customer_id is None:
            return None
        current_id = int(row.merged_into_customer_id)
    return None


def _subject_storage_predicate(model, customer_id: int):
    now = beijing_now()
    source_owner = exists().where(and_(
        models.CustomerSourceRecord.id == model.source_record_id,
        logical_root_predicate(
            models.CustomerSourceRecord, "source_record", customer_id,
        ),
    ))
    current_relationship = and_(
        models.CustomerContactRelationship.contact_id == model.contact_id,
        models.CustomerContactRelationship.verification_status.in_((
            "identified", "verified",
        )),
        or_(
            models.CustomerContactRelationship.effective_from.is_(None),
            models.CustomerContactRelationship.effective_from <= now,
        ),
        models.CustomerContactRelationship.effective_to.is_(None),
    )
    contact_owner = exists().where(and_(
        current_relationship,
        models.CustomerContactRelationship.customer_id == customer_id,
    ))
    relationship_owner_count = select(func.count(func.distinct(
        models.CustomerContactRelationship.customer_id,
    ))).where(current_relationship).correlate(model).scalar_subquery()
    return or_(
        and_(model.source_record_id.is_not(None), source_owner),
        and_(
            model.source_record_id.is_(None),
            model.contact_id.is_not(None),
            relationship_owner_count == 1,
            contact_owner,
        ),
        and_(
            model.source_record_id.is_(None),
            model.contact_id.is_(None),
            model.customer_id == customer_id,
        ),
    )


def logical_root_query(
    db: Session,
    model,
    object_type: str,
    customer_id: int,
):
    """Return roots whose current overlay owner is ``customer_id`` in one query."""
    return db.query(model).filter(logical_root_predicate(
        model, object_type, customer_id,
    ))


def logical_root_predicate(model, object_type: str, customer_id: int):
    """Build a correlated effective-owner predicate for an existing query."""
    if _ROOT_MODELS.get(object_type) is not model:
        raise ValueError("LOGICAL_ROOT_NOT_REGISTERED")
    overlay_exists = exists().where(and_(
        models.CustomerObjectOwnership.object_type == object_type,
        models.CustomerObjectOwnership.object_id == model.id,
    ))
    current_overlay = exists().where(and_(
        models.CustomerObjectOwnership.object_type == object_type,
        models.CustomerObjectOwnership.object_id == model.id,
        models.CustomerObjectOwnership.current_customer_id == customer_id,
    ))
    if object_type in _SUBJECT_ROOTS:
        storage_predicate = _subject_storage_predicate(model, customer_id)
    else:
        storage_predicate = model.customer_id == customer_id
    return or_(current_overlay, and_(~overlay_exists, storage_predicate))


def logical_subject_matches_customer(model, object_type: str, outer_customer_model):
    """Match a subject root to a correlated outer customer account."""
    if object_type not in _SUBJECT_ROOTS or _ROOT_MODELS.get(object_type) is not model:
        raise ValueError("LOGICAL_SUBJECT_NOT_REGISTERED")
    customer_id = outer_customer_model.id
    correlated = (model, outer_customer_model)
    overlay_exists = exists().where(and_(
        models.CustomerObjectOwnership.object_type == object_type,
        models.CustomerObjectOwnership.object_id == model.id,
    )).correlate(*correlated)
    current_overlay = exists().where(and_(
        models.CustomerObjectOwnership.object_type == object_type,
        models.CustomerObjectOwnership.object_id == model.id,
        models.CustomerObjectOwnership.current_customer_id == customer_id,
    )).correlate(*correlated)

    source_overlay_exists = exists().where(and_(
        models.CustomerObjectOwnership.object_type == "source_record",
        models.CustomerObjectOwnership.object_id == models.CustomerSourceRecord.id,
    )).correlate(models.CustomerSourceRecord, outer_customer_model)
    source_current_overlay = exists().where(and_(
        models.CustomerObjectOwnership.object_type == "source_record",
        models.CustomerObjectOwnership.object_id == models.CustomerSourceRecord.id,
        models.CustomerObjectOwnership.current_customer_id == customer_id,
    )).correlate(models.CustomerSourceRecord, outer_customer_model)
    source_owner = exists().where(and_(
        models.CustomerSourceRecord.id == model.source_record_id,
        or_(
            source_current_overlay,
            and_(
                ~source_overlay_exists,
                models.CustomerSourceRecord.customer_id == customer_id,
            ),
        ),
    )).correlate(*correlated)

    now = beijing_now()
    current_relationship = and_(
        models.CustomerContactRelationship.contact_id == model.contact_id,
        models.CustomerContactRelationship.verification_status.in_((
            "identified", "verified",
        )),
        or_(
            models.CustomerContactRelationship.effective_from.is_(None),
            models.CustomerContactRelationship.effective_from <= now,
        ),
        models.CustomerContactRelationship.effective_to.is_(None),
    )
    contact_owner = exists().where(and_(
        current_relationship,
        models.CustomerContactRelationship.customer_id == customer_id,
    )).correlate(*correlated)
    relationship_owner_count = select(func.count(func.distinct(
        models.CustomerContactRelationship.customer_id,
    ))).where(current_relationship).correlate(*correlated).scalar_subquery()
    storage_owner = or_(
        and_(model.source_record_id.is_not(None), source_owner),
        and_(
            model.source_record_id.is_(None), model.contact_id.is_not(None),
            relationship_owner_count == 1, contact_owner,
        ),
        and_(
            model.source_record_id.is_(None), model.contact_id.is_(None),
            model.customer_id == customer_id,
        ),
    )
    return or_(current_overlay, and_(~overlay_exists, storage_owner))


def logical_owner_expression(model, object_type: str):
    """Return a correlated logical owner expression for a direct root."""
    if _ROOT_MODELS.get(object_type) is not model or object_type in _SUBJECT_ROOTS:
        raise ValueError("LOGICAL_DIRECT_ROOT_NOT_REGISTERED")
    overlay_owner = select(
        models.CustomerObjectOwnership.current_customer_id,
    ).where(
        models.CustomerObjectOwnership.object_type == object_type,
        models.CustomerObjectOwnership.object_id == model.id,
    ).correlate(model).scalar_subquery()
    return func.coalesce(overlay_owner, model.customer_id)


__all__ = [
    "logical_root_query",
    "logical_root_predicate",
    "logical_subject_matches_customer",
    "logical_owner_expression",
    "resolve_canonical_customer_id",
]
