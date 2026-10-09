"""Exact production parent recognition; no database connections or writes."""
from contextlib import nullcontext
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rollback_protocol
from app.invoice import outbound_mode


@pytest.mark.parametrize('head,allowed', [
    ('171_customer_tag_display_value', True), ('175_receipt_recovery', True),
    ('174_domestic_decision', False), ('176_customer_order_portal', False),
    ('177_portal_pi_header', False), ('178_account_unlock', False),
    ('999_unknown', False), (None, False),
    (['175_receipt_recovery', '171_customer_tag_display_value'], False),
    (['175_receipt_recovery', '175_receipt_recovery'], False),
])
@pytest.mark.parametrize('reader', ['application', 'rollback'])
def test_exact_missing_table_boundary(head, allowed, reader):
    missing = OperationalError('mode query', {}, Exception(1146, 'isolated missing table'))
    heads = [] if head is None else [(item,) for item in head] if isinstance(head, list) else [(head,)]
    connection = Mock()
    if reader == 'application':
        db = Mock(no_autoflush=nullcontext())
        db.connection.return_value = connection
        connection.execute.side_effect = [missing, Mock(all=Mock(return_value=heads))]
        call = lambda: outbound_mode.read_mode(db)
    else:
        connection.exec_driver_sql.side_effect = [
            Mock(all=Mock(return_value=[('11111111-2222-3333-4444-555555555555', 'isolated_test')])),
            missing, Mock(all=Mock(return_value=heads)),
        ]
        call = lambda: rollback_protocol.observe(connection)['mode']
    if allowed:
        assert call() == 'legacy'
    else:
        with pytest.raises(RuntimeError):
            call()


@pytest.mark.parametrize('reader', ['application', 'rollback'])
def test_permission_error_never_reads_parent(reader):
    denied = OperationalError('mode query', {}, Exception(1142, 'isolated denied'))
    connection = Mock()
    if reader == 'application':
        db = Mock(no_autoflush=nullcontext())
        db.connection.return_value = connection
        connection.execute.side_effect = denied
        call = lambda: outbound_mode.read_mode(db)
    else:
        connection.exec_driver_sql.side_effect = [
            Mock(all=Mock(return_value=[('11111111-2222-3333-4444-555555555555', 'isolated_test')])), denied,
        ]
        call = lambda: rollback_protocol.observe(connection)
    with pytest.raises(Exception):
        call()
    assert (connection.execute.call_count if reader == 'application'
            else connection.exec_driver_sql.call_count) == (1 if reader == 'application' else 2)
