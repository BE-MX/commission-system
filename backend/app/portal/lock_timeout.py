"""Bound MySQL row-lock waits only for transactions participating in portal authority.

MySQL 1205 rolls back a statement, not the transaction. Callers own full rollback;
a timed-out transaction cannot commit. Restore the prior session variable at root
transaction end, including externally bound Connections, with pool reset as a
backstop. Savepoint completion must not release this outer transaction policy.
"""
import logging

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import Pool

from app.portal.errors import TransactionBusy

logger = logging.getLogger(__name__)
_STATE = 'portal_lock_timeout_state'


def busy():
    return TransactionBusy()


def bound_lock_wait(db, seconds, *, connection=None):
    if connection is None:
        connection = db.connection()
    if connection.dialect.name != 'mysql' or _STATE in connection.info:
        return
    original = int(connection.exec_driver_sql('SELECT @@SESSION.innodb_lock_wait_timeout').scalar_one())
    connection.info[_STATE] = {'original':original, 'seconds':seconds, 'timed_out':False}
    connection.exec_driver_sql('SET SESSION innodb_lock_wait_timeout = %s', (seconds,))


def _restore(dbapi_connection, info):
    state = info.get(_STATE)
    if state is None:
        return
    with dbapi_connection.cursor() as cursor:
        cursor.execute('SET SESSION innodb_lock_wait_timeout = %s', (state['original'],))
    del info[_STATE]


def _restore_connection(connection):
    if connection.closed or connection.invalidated or _STATE not in connection.info:
        return
    try:
        _restore(connection.connection.dbapi_connection, connection.info)
    except Exception:
        # Do not reuse a connection with leaked policy or log SQL/parameters.
        logger.warning('Portal lock timeout restoration failed; invalidating connection')
        print('Portal lock timeout restoration failed; invalidating connection', flush=True)
        connection.invalidate()
        raise


@event.listens_for(Engine, 'commit')
def _before_commit(connection):
    if not connection.closed and not connection.invalidated:
        state = connection.info.get(_STATE)
        if state is not None and state['timed_out']:
            # A commit-event exception makes SQLAlchemy's RootTransaction
            # inactive before caller rollback; an externally bound Connection
            # then skips DBAPI rollback. Abort the physical transaction here.
            try:
                connection.connection.dbapi_connection.rollback()
            except Exception:
                logger.warning('Portal timed-out commit rollback failed; invalidating connection')
                print('Portal timed-out commit rollback failed; invalidating connection', flush=True)
                connection.invalidate()
                raise
            _restore_connection(connection)
            raise busy()
    _restore_connection(connection)


@event.listens_for(Engine, 'rollback')
def _before_rollback(connection):
    _restore_connection(connection)


@event.listens_for(Pool, 'reset')
def _reset_connection(dbapi_connection, record, reset_state):
    if reset_state.terminate_only or _STATE not in record.info:
        return
    try:
        _restore(dbapi_connection, record.info)
    except Exception:
        logger.warning('Portal pool timeout restoration failed; discarding connection')
        print('Portal pool timeout restoration failed; discarding connection', flush=True)
        raise  # SQLAlchemy invalidates a connection whose pool reset fails.


@event.listens_for(Engine, 'handle_error', retval=True)
def _lock_wait_error(context):
    connection = context.connection
    if connection is None or connection.closed or connection.invalidated:
        return None
    state = connection.info.get(_STATE)
    args = getattr(context.original_exception, 'args', ())
    if connection.dialect.name != 'mysql' or state is None or not args or args[0] != 1205:
        return None  # Unrelated errors and nonparticipating transactions retain their contract.
    state['timed_out'] = True
    logger.warning('Portal transaction row-lock wait timed out after %s seconds', state['seconds'])
    print('Portal transaction row-lock wait timed out', flush=True)
    return busy()
