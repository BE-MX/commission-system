"""Spawn-only notification process; owned DB configuration is transferred by IPC."""
def run(url, settings, instant, kind, hold, gate, output):
    import os
    from pathlib import Path
    from types import SimpleNamespace
    from datetime import datetime
    import pymysql
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, sessionmaker
    import conftest as isolation
    engine = None
    try:
        assert not (Path(__file__).resolve().parents[2] / '.env').exists()
        isolation.ALLOWED.update(port=url.port, password=url.password, database=url.database)
        pymysql.connect = isolation.isolated_connect
        event.listen(Engine, 'do_connect', isolation.isolated_engine)
        import mysql_service_fixture  # noqa: F401; register actual models, no seed
        from app.core import time as platform_time
        from app.portal import auth_service, authority, admin_service, order_queries, mail_worker, notification_worker
        config = SimpleNamespace(**settings)
        for module in (auth_service, authority, admin_service, order_queries, mail_worker, notification_worker):
            module.get_settings = lambda: config
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)
        platform_time.datetime = Clock
        engine = create_engine(url, isolation_level='REPEATABLE READ', hide_parameters=True)
        @event.listens_for(engine, 'connect')
        def configure(connection, record):
            with connection.cursor() as cursor:
                cursor.execute("SET time_zone = '+08:00'")
                cursor.execute('SET SESSION innodb_lock_wait_timeout = 8')
        with Session(engine) as db:
            connection_id = db.scalar(text('SELECT CONNECTION_ID()'))
        output.put(('started', os.getpid(), connection_id))
        factory = sessionmaker(bind=engine)
        sessions = []
        def tracked():
            db = factory(); sessions.append(db); return db
        def forbidden(*args):
            raise AssertionError('Real SMTP is forbidden in the isolated process')
        mail_worker.smtp_sender = notification_worker.smtp_sender = forbidden
        def accepted(mail):
            assert all(not db.in_transaction() for db in sessions)
            assert mail.valid_until > platform_time.beijing_now()
            # No recipient, body, token or lease value is sent to the result queue.
            output.put(('accepted', mail.message_id, len(sessions)))
            if hold:
                assert gate.wait(30), 'Parent failed to terminate/release the controlled sender'
            return True
        worker = mail_worker if kind in {'invitation', 'auth_code'} else notification_worker
        result = worker.run_once(tracked, accepted)
        output.put(('finished', result))
    except Exception as error:
        output.put(('worker_error', type(error).__name__))
    finally:
        if engine is not None: engine.dispose()