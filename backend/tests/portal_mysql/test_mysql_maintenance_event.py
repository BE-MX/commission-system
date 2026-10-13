"""Real owned MySQL: pause preserves definer, CRLF, modes and scheduling."""
from pathlib import Path
import sys
import time

from sqlalchemy import text

from conftest import ALLOWED
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'deploy'))
import portal_maintenance as maintenance


def test_real_event_pause_drain_and_original_definition_restore(request, mysql_engine, monkeypatch):
    if not request.config.getoption('portal_maintenance_events'):
        import pytest
        pytest.skip('Explicit synthetic event maintenance scope required')
    state = Path(request.config.getoption('portal_mysql_workspace'))
    (state / 'credentials').mkdir()
    credential = state / 'credentials/event-maintenance.env'
    credential.write_text('COMMISSION_DB_USER=root\nCOMMISSION_DB_PASSWORD=' + ALLOWED['password'] + '\n')
    class Settings:
        commission_db_url = mysql_engine.url.render_as_string(hide_password=False)
        def model_copy(self, update):
            assert update['COMMISSION_DB_USER'] == 'root'
            assert update['COMMISSION_DB_PASSWORD'] == ALLOWED['password']
            return self
    calls = []
    monkeypatch.setattr(maintenance, 'mirror', lambda action, baseline=None:
        calls.append(action) or {'cron_sha256': 'synthetic-cron', 'status': 'ready'})
    try:
        with mysql_engine.connect() as connection:
            connection.execute(text('CREATE EVENT `' + maintenance.EVENT + '` ON SCHEDULE EVERY 1 HOUR '
                "STARTS '2030-01-01 00:00:00' DO BEGIN\r\n SELECT 'synthetic';\r\n END"))
            connection.commit()
            original = maintenance.event_snapshot(connection)
            connection.execute(text('SET GLOBAL event_scheduler=ON'))
            baseline = maintenance.check(state, Settings(), connection)
            saved = []
            maintenance.freeze(state, Settings(), connection, baseline, lambda: saved.append(True))
            assert len(saved) >= 3 and baseline['event_paused'] is True
            assert maintenance.event_snapshot(connection)['fields_sha256'] == original['paused_fields_sha256']
            # Publication finalization runs after the migration connection closes.
            connection.commit()
            maintenance.restore(state, Settings(), baseline)
            assert baseline['restored'] is True
            assert maintenance.event_snapshot(connection)['fields_sha256'] == original['fields_sha256']
            assert calls == ['check', 'freeze', 'verify-frozen', 'thaw']
            connection.execute(text('SET GLOBAL event_scheduler=OFF'))
    finally:
        credential.unlink(missing_ok=True)


def test_uninstrumented_active_worker_is_visible_and_drains(request, mysql_engine, monkeypatch):
    if not request.config.getoption('portal_maintenance_events'):
        import pytest
        pytest.skip('Explicit synthetic event maintenance scope required')
    state = Path(request.config.getoption('portal_mysql_workspace'))
    credential = state / 'credentials/event-maintenance.env'
    credential.write_text('COMMISSION_DB_USER=root\nCOMMISSION_DB_PASSWORD=' + ALLOWED['password'] + '\n')
    class Settings:
        commission_db_url = mysql_engine.url.render_as_string(hide_password=False)
        def model_copy(self, update): return self
    monkeypatch.setattr(maintenance, 'mirror', lambda action, baseline=None: {'cron_sha256': 'synthetic-cron', 'status': 'ready'})
    try:
        with mysql_engine.connect() as connection:
            connection.execute(text('DROP EVENT `' + maintenance.EVENT + '`'))
            connection.execute(text("UPDATE performance_schema.setup_threads SET ENABLED='NO' WHERE NAME='thread/sql/event_worker'"))
            connection.execute(text('CREATE EVENT `' + maintenance.EVENT + '` ON SCHEDULE EVERY 1 DAY '
                'STARTS CURRENT_TIMESTAMP + INTERVAL 2 SECOND ON COMPLETION PRESERVE '
                'DO BEGIN\r\n SELECT SLEEP(8);\r\n END'))
            connection.commit()
            connection.execute(text('SET GLOBAL event_scheduler=ON'))
            deadline = time.monotonic() + 15
            while not connection.scalar(text("SELECT COUNT(*) FROM performance_schema.threads WHERE NAME='thread/sql/event_worker'")):
                assert time.monotonic() < deadline, 'Owned synthetic event worker was not observed'
                time.sleep(.1)
            # The event's authenticated definer can override the class default.
            # Disable this live owned thread explicitly and prove it remains visible.
            connection.execute(text("UPDATE performance_schema.threads SET INSTRUMENTED='NO' WHERE NAME='thread/sql/event_worker'"))
            assert connection.scalar(text("SELECT COUNT(*) FROM performance_schema.threads WHERE NAME='thread/sql/event_worker' AND INSTRUMENTED='NO'")) == 1
            baseline = maintenance.check(state, Settings(), connection)
            maintenance.freeze(state, Settings(), connection, baseline, lambda: None)
            assert connection.scalar(text("SELECT COUNT(*) FROM performance_schema.threads WHERE NAME='thread/sql/event_worker'")) == 0
            connection.commit()
            maintenance.restore(state, Settings(), baseline)
            connection.execute(text('SET GLOBAL event_scheduler=OFF'))
    finally:
        credential.unlink(missing_ok=True)
