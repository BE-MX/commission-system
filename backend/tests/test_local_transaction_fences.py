"""Legacy workers and generic invoice writes stop before reading external state."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from sqlalchemy import event
import pytest
from fastapi import HTTPException
from app.core.config import get_settings
from app.invoice.lifecycle_guard import ensure_legacy_transaction
from app.invoice.service import create_invoice
from app.receipt.scheduler import process_receipts
from app.services.payment_sync_service import sync_payments
from app.shipping_inspection.outbound_reconcile_service import reconcile_deleted_outbounds


def test_installed_local_phase_stops_legacy_effects_before_provider_or_mirror_access(db, monkeypatch):
    from tests.test_commerce_transition_authority import install
    from app.invoice.models import Invoice
    install(db, phase='local_only')
    db.commit()
    monkeypatch.setattr(get_settings(), "TRANSACTION_MODE", "local")
    import httpx
    def forbidden(*args, **kwargs):
        pytest.fail('Rejected legacy command must not call a provider')
    monkeypatch.setattr(httpx, 'get', forbidden)
    monkeypatch.setattr(httpx, 'post', forbidden)
    monkeypatch.setattr(httpx, 'request', forbidden)
    def no_transaction_mirror(conn, cursor, statement, parameters, context, executemany):
        assert 'lsordertest' not in statement.lower(), statement
    event.listen(db.get_bind(), 'before_cursor_execute', no_transaction_mirror)
    try:
        with pytest.raises(ValueError, match='路线'):
            create_invoice(db, SimpleNamespace(source_type='manual', transaction_route='legacy'))
        with pytest.raises(ValueError, match="承接"):
            ensure_legacy_transaction(SimpleNamespace(transaction_mode="okki"))
        with pytest.raises(HTTPException) as failure:
            sync_payments(db, date(2026, 10, 1), date(2026, 10, 3))
        assert failure.value.status_code == 409
        assert reconcile_deleted_outbounds(db)["skipped"] == "local_transaction_mode"
        session = Mock(side_effect=AssertionError("legacy worker opened a database"))
        monkeypatch.setattr("app.receipt.scheduler.SessionLocal", session)
        process_receipts()
        assert not session.mock_calls and db.query(Invoice).count() == 0
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', no_transaction_mirror)
