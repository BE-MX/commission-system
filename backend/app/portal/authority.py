"""Transaction-scoped authorization barrier, acquired before upstream business locks."""

import logging
from time import perf_counter

from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import beijing_now
from app.portal.errors import PortalError, reject
from app.portal.lock_timeout import bound_lock_wait
from app.portal.models import AuthorityBarrier, CustomerAccess, Invitation, Membership, PortalSession, Quote


logger = logging.getLogger(__name__)


def unavailable(error):
    diagnostics = []
    try:
        logger.warning("Portal authority unavailable (%s)", type(error).__name__)
    except Exception as failure:
        diagnostics.append(failure)
    try:
        print("[portal-authority] authorization unavailable", flush=True)
    except Exception as failure:
        diagnostics.append(failure)
    response = PortalError("SERVICE_UNAVAILABLE", "Portal authorization cannot be confirmed.", 503)
    if diagnostics:
        raise response from ExceptionGroup("Portal authority diagnostics failed", diagnostics)
    raise response from None


def lock_authority(db: Session, *, force=False) -> AuthorityBarrier | None:
    settings = get_settings()
    scope = (db.get_transaction(), db.get_nested_transaction())
    held = db.info.get("portal_authority_scope")
    if scope[0] is not None and held == scope:
        return db.info["portal_authority_row"]
    db.info.pop("portal_authority_legacy_root", None)
    with db.no_autoflush:
        connection = None
        stage = "connection"
        started = perf_counter()
        try:
            connection = db.connection(bind_arguments={'mapper': AuthorityBarrier})
            stage = "timeout"
            if connection.dialect.name == 'mysql':
                bound_lock_wait(db, settings.PORTAL_LOCK_WAIT_SECONDS, connection=connection)
            stage = "barrier"
            barrier = db.scalar(select(AuthorityBarrier).where(AuthorityBarrier.code == "authority")
                                .with_for_update().execution_options(populate_existing=True))
        except SQLAlchemyError as error:
            values = getattr(getattr(error, 'orig', None), 'args', ())
            if (force or settings.PORTAL_ENABLED or stage != "barrier" or connection is None
                or connection.dialect.name != 'mysql' or not values
                or type(values[0]) is not int or values[0] != 1146):
                unavailable(error)
            try:
                # Current read: never trust an earlier caller RR snapshot.
                heads = connection.execute(text('SELECT version_num FROM alembic_version FOR UPDATE')).all()
            except SQLAlchemyError as head_error:
                unavailable(head_error)
            if heads != [('171_customer_tag_display_value',)]:
                unavailable(error)
            db.info['portal_authority_legacy_root'] = db.get_transaction()
            return None
        finally:
            db.info['portal_authority_wait_ms'] = (perf_counter() - started) * 1000
    if barrier is None:
        reject("SERVICE_UNAVAILABLE", "Portal authorization is unavailable.", 503)
    db.info.pop("portal_authority_legacy_root", None)
    db.info["portal_authority_scope"] = (db.get_transaction(), db.get_nested_transaction())
    db.info["portal_authority_row"] = barrier
    return barrier


def authority_changed(db: Session):
    barrier = lock_authority(db)
    if barrier is not None:
        barrier.version += 1


def suspend_customer_access(db: Session, customer_ids):
    """Caller already holds the barrier before changing customer identity/ownership.

    Source evidence refresh alone must not call this function.
    """
    if db.get_transaction() is not None and db.info.get("portal_authority_legacy_root") is db.get_transaction():
        return
    scope = (db.get_transaction(), db.get_nested_transaction())
    if db.info.get("portal_authority_scope") != scope:
        raise RuntimeError("Customer authority mutation did not acquire the portal barrier first")
    rows = db.scalars(select(CustomerAccess).where(CustomerAccess.customer_id.in_(set(customer_ids)))
                      .order_by(CustomerAccess.id).with_for_update().execution_options(populate_existing=True)).all()
    for access in rows:
        if access.status != "review_required":
            access.status = "review_required"
            access.auth_version += 1
            access.row_version += 1
        memberships = select(Membership.id).where(Membership.access_id == access.id)
        sessions = db.scalars(select(PortalSession).where(PortalSession.membership_id.in_(memberships),
                               PortalSession.revoked_at.is_(None)).with_for_update()).all()
        for session in sessions:
            session.revoked_at = beijing_now()
        invitations = db.scalars(select(Invitation).where(Invitation.access_id == access.id,
            Invitation.revoked_at.is_(None), Invitation.consumed_at.is_(None)).with_for_update()).all()
        for invitation in invitations:
            invitation.revoked_at = beijing_now()
        quotes = db.scalars(select(Quote).where(Quote.access_id == access.id,
            Quote.status == "valid").with_for_update()).all()
        for quote in quotes:
            quote.status = "expired"
    authority_changed(db)


def review_customer_bindings(db: Session, customer_ids):
    """Recheck persisted bindings after identity edits; evidence refresh is harmless."""
    if db.get_transaction() is not None and db.info.get("portal_authority_legacy_root") is db.get_transaction():
        return
    from app.portal.access_policy import validate_binding
    from app.portal.errors import PortalError
    from app.customer.models import CustomerExternalIdentity

    scope = (db.get_transaction(), db.get_nested_transaction())
    if db.info.get("portal_authority_scope") != scope:
        held = db.info.get("portal_authority_scope")
        if scope[0] is None or held is None or held[0] is not scope[0]:
            raise RuntimeError("Identity mutation did not acquire the portal barrier first")
        # A nested savepoint may have started since its outer caller took the lock.
        lock_authority(db)
    customer_ids = set(customer_ids)
    identities = select(CustomerExternalIdentity.id).where(CustomerExternalIdentity.customer_id.in_(customer_ids))
    # Logical merge/split ownership can differ from an identity's storage customer.
    rows = db.scalars(select(CustomerAccess).where(or_(CustomerAccess.customer_id.in_(customer_ids),
        CustomerAccess.external_identity_id.in_(identities)),
        CustomerAccess.status != "review_required").order_by(CustomerAccess.id).with_for_update()
        .execution_options(populate_existing=True)).all()
    invalid_ids = set()
    for access in rows:
        try:
            validate_binding(db, access)
        except PortalError as error:
            if error.code not in {"IDENTITY_REVIEW_REQUIRED", "ASSIGNMENT_CHANGED"}:
                raise
            invalid_ids.add(access.customer_id)
    if invalid_ids:
        suspend_customer_access(db, invalid_ids)
