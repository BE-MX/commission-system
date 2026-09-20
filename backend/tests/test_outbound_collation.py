"""Deletion IDs must compare as strings under MySQL's connection defaults."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from app.shipping_inspection.outbound_service import deleted_clause


@pytest.mark.parametrize('dialect', ['mysql', 'sqlite'])
def test_deletion_filter_only_hides_exact_completed_receipts(dialect):
    engine = create_engine('sqlite://')
    with engine.connect() as conn:
        # Execute the MySQL branch against SQLite with the named collation;
        # MySQL itself is also verified with read-only SELECTs during diagnosis.
        conn.connection.driver_connection.create_collation(
            'utf8mb4_unicode_ci', lambda a, b: (a > b) - (a < b))
        conn.execute(text('CREATE TABLE ark_shipping_operation_events '
                          '(scope TEXT, action TEXT, request_id TEXT)'))
        conn.execute(text("INSERT INTO ark_shipping_operation_events VALUES "
                          "('outbound-delete','outbound_deleted','77'),"
                          "('outbound-delete','outbound_deleted','078'),"
                          "('outbound-delete','outbound_delete_failed','79'),"
                          "('other','outbound_deleted','80')"))
        db = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name=dialect)))
        clause = deleted_clause(db, {'invoice_id': 'invoice_id'})
        if dialect == 'mysql':
            assert 'COLLATE utf8mb4_unicode_ci' in clause
        rows = conn.execute(text('SELECT r.invoice_id FROM '
                                 '(SELECT 77 AS invoice_id UNION ALL SELECT 78 '
                                 'UNION ALL SELECT 79 UNION ALL SELECT 80) r WHERE ' + clause)).scalars().all()
        assert rows == [78, 79, 80]
    engine.dispose()


def test_legacy_table_without_invoice_bridge_keeps_records():
    assert deleted_clause(None, {}) == '1=1'
