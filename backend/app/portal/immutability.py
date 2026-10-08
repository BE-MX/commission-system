"""Reject ORM rewrites of accepted evidence; services must not bulk-update snapshots."""

from sqlalchemy import event, inspect

from app.portal.catalog_models import MappingRevision
from app.portal.event_models import AuditEvent
from app.portal.order_models import CommandReceipt, Conversion, Publication, Quote, RequestLine, Revision


def _changed(target):
    return {attr.key for attr in inspect(target).attrs if attr.history.has_changes()} - {"updated_at"}


def _old(target, key):
    history = inspect(target).attrs[key].history
    return history.deleted[0] if history.deleted else getattr(target, key)


def guard_update(mapper, connection, target):
    changed = _changed(target)
    if not changed:
        return
    if isinstance(target, Revision):
        permitted = {"customer_accepted_by", "customer_accepted_at"}
        if changed <= permitted and all(_old(target, key) is None for key in permitted):
            if target.customer_accepted_by is not None and target.customer_accepted_at is not None:
                return
    elif isinstance(target, Quote):
        if changed == {"status"} and _old(target, "status") == "valid" and target.status in {"consumed", "expired"}:
            return
    elif isinstance(target, MappingRevision):
        if _old(target, "status") == "draft":
            return
    elif isinstance(target, Publication):
        if changed == {"status"} and _old(target, "status") == "published" and target.status == "withdrawn":
            return
    elif isinstance(target, Conversion):
        if _old(target, "status") == "pending":
            return
        if changed == {"status"} and _old(target, "status") == "created" and target.status == "tombstoned":
            return
    raise ValueError("Portal business evidence is immutable; create a new revision")


def guard_delete(mapper, connection, target):
    raise ValueError("Portal business evidence and invoice lineage must be retained")


def install_guards():
    for model in (Revision, RequestLine, Quote, MappingRevision, Publication, Conversion, CommandReceipt, AuditEvent):
        if not event.contains(model, "before_update", guard_update):
            event.listen(model, "before_update", guard_update)
            event.listen(model, "before_delete", guard_delete)
