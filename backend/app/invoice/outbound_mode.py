"""Durable outbound protocol and shared executor fence; no caller-owned commits."""
from contextlib import contextmanager
import logging

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.portal import authority
from app.portal.models import AuthorityBarrier

logger = logging.getLogger(__name__)
MODE = 'outbound-worker-v1'
LEGACY = 'legacy'
LOCK_NAME = 'ark-okki-outbound-poller'


def read_mode(db):
    """Query directly; a missing table needs same-connection parent evidence."""
    connection = None
    try:
        with db.no_autoflush:
            connection = db.connection(bind_arguments={'mapper':AuthorityBarrier})
            rows = connection.execute(select(AuthorityBarrier.code, AuthorityBarrier.version)
                .where(AuthorityBarrier.code.like('outbound-worker-%'))).all()
    except SQLAlchemyError as error:
        logger.warning('Outbound mode query unavailable (%s)', type(error).__name__)
        print('[outbound-mode] mode query unavailable; verifying schema boundary', flush=True)
        values = getattr(getattr(error, 'orig', None), 'args', ())
        if connection is None or not values or type(values[0]) is not int or values[0] != 1146:
            raise RuntimeError('Outbound execution mode cannot be confirmed') from None
        try:
            with db.no_autoflush:
                heads = connection.execute(text('SELECT version_num FROM alembic_version')).all()
        except SQLAlchemyError as head_error:
            logger.warning('Outbound mode parent evidence unavailable (%s)', type(head_error).__name__)
            print('[outbound-mode] parent evidence unavailable; writers remain paused', flush=True)
            raise RuntimeError('Outbound execution mode cannot be confirmed') from None
        if heads not in ([('171_customer_tag_display_value',)], [('175_receipt_recovery',)]):
            raise RuntimeError('Outbound execution mode cannot be confirmed') from None
        return LEGACY
    if not rows:
        return LEGACY
    if len(rows) != 1 or rows[0].code != MODE or type(rows[0].version) is not int or rows[0].version != 1:
        raise RuntimeError('Outbound execution mode cannot be confirmed')
    return MODE


def rollback_owned(db):
    try:
        db.rollback()
        db.expire_all()
    except BaseException as error:
        logger.warning('Outbound business cleanup unavailable (%s)', type(error).__name__)
        print('[outbound-mode] business cleanup unavailable; discarding connection', flush=True)
        db.invalidate()
        raise


@contextmanager
def executor_fence(db):
    # A stale RR read transaction must never precede the advisory lock.
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise RuntimeError('Outbound executor requires a fresh owned session')
    with db.get_bind().connect() as fence:
        try:
            connection_id, prior_owner = fence.execute(text(
                'SELECT CONNECTION_ID(), IS_USED_LOCK(:name)'), {'name':LOCK_NAME}).one()
            if type(connection_id) is not int or connection_id < 1:
                raise RuntimeError('Outbound fence connection cannot be confirmed')
            if prior_owner is not None and (type(prior_owner) is not int or prior_owner < 1):
                raise RuntimeError('Outbound fence owner cannot be confirmed')
            if prior_owner == connection_id:
                # A pooled socket may carry a lock leaked by an older binary.
                # MySQL GET_LOCK is recursive; acquiring it again would hide the leak.
                raise RuntimeError('Outbound fence connection already owns the lock')
            acquired = fence.scalar(text('SELECT GET_LOCK(:name,0)'), {'name':LOCK_NAME})
            fence.rollback()
            if type(acquired) is not int or acquired not in (0,1):
                raise RuntimeError('Outbound fence acquisition cannot be confirmed')
        except BaseException as error:
            fence.invalidate()
            logger.warning('Outbound fence acquisition unavailable (%s)', type(error).__name__)
            print('[outbound-mode] fence acquisition unavailable', flush=True)
            if not isinstance(error,Exception):
                raise
            raise RuntimeError('Outbound executor fence acquisition is unavailable') from None
        if acquired == 0:
            yield False
            return
        try:
            yield True
        finally:
            try:
                released = fence.scalar(text('SELECT RELEASE_LOCK(:name)'), {'name':LOCK_NAME})
                remaining_owner = fence.scalar(text('SELECT IS_USED_LOCK(:name)'), {'name':LOCK_NAME})
                fence.rollback()
                if type(released) is not int or released != 1:
                    raise RuntimeError('Outbound executor fence release cannot be confirmed')
                if remaining_owner == connection_id or (remaining_owner is not None and
                        (type(remaining_owner) is not int or remaining_owner < 1)):
                    raise RuntimeError('Outbound executor fence ownership remains uncertain')
            except BaseException as error:
                # Never return a physical connection with an unknown named lock to its pool.
                fence.invalidate()
                logger.warning('Outbound fence release unavailable (%s)', type(error).__name__)
                print('[outbound-mode] fence release unavailable', flush=True)
                if not isinstance(error,Exception):
                    raise
                raise RuntimeError('Outbound executor fence release is unavailable') from None


def establish_under_fence(db):
    """Caller owns the advisory fence and a fresh dedicated session."""
    if db.in_transaction() or db.new or db.dirty or db.deleted:
        raise RuntimeError('Outbound mode installation requires a fresh owned session')
    try:
        authority.lock_authority(db, force=True)
        current = read_mode(db)
        if current == LEGACY:
            db.add(AuthorityBarrier(code=MODE,version=1))
        db.commit()
        db.expire_all()
        confirmed = read_mode(db)
        rollback_owned(db)
        if confirmed != MODE:
            raise RuntimeError('Outbound execution mode commit cannot be confirmed')
        return confirmed
    except Exception:
        rollback_owned(db)
        raise


def initialize(factory, *, portal_enabled):
    # This read is never reused for a first installation: release its RR snapshot.
    with factory() as initial:
        current = read_mode(initial)
    if current == MODE or not portal_enabled:
        return current
    with factory() as db:
        with executor_fence(db) as acquired:
            if not acquired:
                raise RuntimeError('Outbound executor still owns the fence; bootstrap remains paused')
            return establish_under_fence(db)


def reconcile_legacy(factory, *, limit=None):
    """Recheck under the shared owner until the legacy queue commits or rolls back."""
    with factory() as db:
        with executor_fence(db) as acquired:
            if not acquired:
                return {'status':'busy','enqueued':0}
            try:
                if read_mode(db) != LEGACY:
                    return {'status':'disabled','enqueued':0}
                from app.invoice.outbound_task_service import _reconcile_missing_outbound_tasks
                result = (_reconcile_missing_outbound_tasks(db) if limit is None
                    else _reconcile_missing_outbound_tasks(db, limit=limit))
                db.commit()
                db.expire_all()
                return result
            finally:
                # End the owned business transaction before releasing the fence,
                # including KeyboardInterrupt/SystemExit and commit ACK loss.
                rollback_owned(db)
