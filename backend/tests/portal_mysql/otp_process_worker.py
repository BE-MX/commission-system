"""Spawn-only OTP worker. Credentials travel through multiprocessing IPC, never logs."""
def run(url, settings, now, attempt, code, release, output, commit):
    import os
    from pathlib import Path
    from types import SimpleNamespace
    import pymysql
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session
    import conftest as isolation

    engine = None
    try:
        assert not (Path(__file__).resolve().parents[2] / '.env').exists()
        isolation.ALLOWED.update(port=url.port, password=url.password, database=url.database)
        pymysql.connect = isolation.isolated_connect
        event.listen(Engine, 'do_connect', isolation.isolated_engine)
        # Register the same upstream ORM models, but never run fixture setup here.
        import mysql_service_fixture  # noqa: F401
        from app.portal import auth_service as auth, authority
        from app.portal.errors import PortalError
        from app.portal.schemas import VerifyInput
        config = SimpleNamespace(**settings)
        auth.get_settings = authority.get_settings = lambda: config
        auth.beijing_now = lambda: now
        engine = create_engine(url, isolation_level='REPEATABLE READ', hide_parameters=True)
        @event.listens_for(engine, 'connect')
        def configure(connection, record):
            with connection.cursor() as cursor:
                cursor.execute("SET time_zone = '+08:00'")
                cursor.execute('SET SESSION innodb_lock_wait_timeout = 8')
        with Session(engine) as db:
            output.put(('connected', os.getpid(), db.scalar(text('SELECT CONNECTION_ID()'))))
            try:
                result = auth.verify(db, auth.require_preauth(db, attempt.token, attempt.csrf),
                    VerifyInput(challenge_id=attempt.public_id, code=code), '127.0.0.1')
                output.put(('verified', result is not None))
                assert release.wait(15), 'Parent did not release the owned transaction'
                if commit:
                    db.commit()
                else:
                    db.rollback()
                output.put(('finished', result is not None))
            except PortalError as error:
                db.rollback()
                output.put(('denied', error.code, error.status))
    except Exception as error:
        # Do not serialize exceptions that could embed credentials or SQL parameters.
        output.put(('worker_error', type(error).__name__))
    finally:
        if engine is not None:
            engine.dispose()
