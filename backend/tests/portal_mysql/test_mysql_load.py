"""T25 simultaneous duplicate submissions; measured locally, not a production SLA."""
from concurrent.futures import ThreadPoolExecutor
import json
from math import ceil
from pathlib import Path
import threading
import time

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from app.portal import authority
from app.portal.models import AuditEvent, OrderRequest, OutboxEvent, Quote, RequestLine, Revision
from test_mysql_services import count, submit


def test_one_hundred_live_transactions_submit_one_order(trade, request):
    ctx = trade
    workers = 100
    # All workers hold a separate connection before the simultaneous release.
    # Existing session-scoped guards allow only this owned server and database.
    engine = create_engine(ctx.engine.url, isolation_level='REPEATABLE READ',
        pool_size=workers, max_overflow=0, pool_timeout=15, hide_parameters=True)
    @event.listens_for(engine, 'connect')
    def configure(connection, record):
        with connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+08:00'")
            cursor.execute('SET SESSION innodb_lock_wait_timeout = 8')
    gate = threading.Barrier(workers + 1, timeout=30)
    def worker():
        with Session(engine) as db:
            connection_id = db.scalar(text('SELECT CONNECTION_ID()'))
            gate.wait()
            started = time.perf_counter()
            result = submit(ctx, db)
            wait_ms = db.info['portal_authority_wait_ms']
            db.commit()
            return connection_id, result, (time.perf_counter() - started) * 1000, wait_ms
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(worker) for _ in range(workers)]
            gate.wait()
            results = [future.result(timeout=30) for future in futures]
        assert len({row[0] for row in results}) == workers
        assert len({row[1]['request_id'] for row in results}) == 1
        assert all(row[1]['status'] == 'submitted' for row in results)
        assert sum(not row[1]['replayed'] for row in results) == 1
        original = next(row[1] for row in results if not row[1]['replayed'])
        expected = {key: value for key, value in original.items() if key != 'replayed'}
        assert all({key: value for key, value in row[1].items() if key != 'replayed'} == expected for row in results)
        request_id = results[0][1]['request_id']
        with Session(engine) as db:
            assert count(db, OrderRequest, OrderRequest.access_id == ctx.access_id) == 1
            order = db.scalar(select(OrderRequest).where(OrderRequest.public_id == request_id))
            assert order.invoice_id is None
            assert count(db, Revision, Revision.request_id == order.id) == 1
            assert count(db, RequestLine, RequestLine.revision_id == order.active_revision_id) == 1
            assert db.get(Quote, order.quote_id).status == 'consumed'
            assert count(db, AuditEvent, (AuditEvent.object_public_id == request_id) & (AuditEvent.action == 'order.submitted')) == 1
            assert count(db, OutboxEvent, (OutboxEvent.aggregate_public_id == request_id) & (OutboxEvent.event_type == 'order_submitted')) == 1
        durations = sorted(row[2] for row in results)
        waits = sorted(row[3] for row in results)
        report = {'configured_lock_wait_seconds':authority.get_settings().PORTAL_LOCK_WAIT_SECONDS,
            'lock_wait_p95_ms':round(waits[ceil(workers*.95)-1],2),
            'lock_wait_p99_ms':round(waits[ceil(workers*.99)-1],2),
            'concurrent_connections': workers, 'created': 1, 'replayed': workers - 1,
            'p95_ms': round(durations[ceil(workers * .95) - 1], 2),
            'p99_ms': round(durations[ceil(workers * .99) - 1], 2), 'max_ms': round(durations[-1], 2),
            'scope': 'local service submit-through-commit; synthetic upstream data',
            'samples': [{'connection_id': row[0], 'replayed': row[1]['replayed'],
                'duration_ms': row[2], 'authority_wait_ms':row[3]} for row in results]}
        evidence = Path(request.config.getoption('portal_mysql_workspace')) / 'duplicate-submit-evidence.json'
        evidence.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key != 'samples'}))
    finally:
        engine.dispose()
