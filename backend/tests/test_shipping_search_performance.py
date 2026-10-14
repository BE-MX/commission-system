"""Keep outbound lookups bounded without changing ownership or pagination."""
from sqlalchemy import event, text

from app.shipping_inspection import outbound_queue_service as queue, outbound_service as records
from tests.test_shipping_inspection import outbound_scope_seed


def test_empty_first_page_does_not_repeat_the_combined_lookup(db, outbound_scope_seed):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        assert queue.list_outbound_records(db, keyword='no-such-outbound', okki_user_id='9001') == ([], 0)
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)
    assert sum('COUNT(*) OVER ()' in sql for sql in statements) == 1
    assert not any('SELECT COUNT(*) FROM (' in sql for sql in statements)


def test_mirror_scope_materializes_customers_once_for_large_lookup(db, outbound_scope_seed):
    # All records share a customer with many orders. A correlated ownership
    # lookup repeatedly scans those orders even when none belongs to this user.
    db.execute(text('CREATE INDEX lsordertest.search_perf_company ON okki_orders(company_id)'))
    db.execute(text('INSERT INTO lsordertest.okki_orders(order_id, company_id, user_id) VALUES (:id, :company, :owner)'),
               [{'id': f'PERF-ORDER-{i}', 'company': 'PERF-CUSTOMER', 'owner': 'other'} for i in range(500)])
    db.execute(text('INSERT INTO lsordertest.okki_outbound_records(id,company_id) VALUES (:id,:company)'),
               [{'id': f'PERF-RECORD-{i}', 'company': 'PERF-CUSTOMER'} for i in range(500)])
    rm = records._record_columns(db)
    clause = records._owner_scope_clause(db, rm)
    steps = 0

    def progress():
        nonlocal steps
        steps += 1
        return 0

    connection = db.connection().connection.driver_connection
    connection.set_progress_handler(progress, 1000)
    try:
        visible = db.execute(text(f'SELECT r.id FROM lsordertest.okki_outbound_records r WHERE {clause}'),
                             {'scope_okki_user_id': '9001'}).scalars().all()
    finally:
        connection.set_progress_handler(None, 0)
    assert visible == ['OB001']
    # Use deterministic VM work, not machine-dependent elapsed time. The former
    # correlated plan needs over 1,000,000 steps for this 500-by-500 workload.
    assert steps < 50, f'Ownership lookup repeated work: at least {steps * 1000} VM steps'
