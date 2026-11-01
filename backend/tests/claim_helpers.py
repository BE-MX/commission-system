"""Seed an original unknown sending claim for an isolated legacy order (tests only)."""
from datetime import timedelta

from app.commerce_transition import service as ownership
from app.commerce_transition.models import InvoiceAuthority, SendingClaim
from app.core.time import beijing_now
from app.invoice import legacy_sending as gate


def unknown_claim(db, invoice, request_key, operation, responsibilities=None):
    if db.get(InvoiceAuthority, invoice.id) is None:
        invoice.transaction_mode = 'legacy'
        ownership.ensure_authority(db, invoice, route='legacy', source_evidence={'fixture': 'explicit'}, confirmed=True)
        db.commit()
    gate.start(db, invoice, request_key, operation, {'request': request_key}, responsibilities or {}, 1)
    db.commit()
    gate.finish(db, request_key, 'unknown', {'transport_outcome': 'unknown'})
    claim = gate.find(db, request_key)
    claim.lease_until = beijing_now() - timedelta(minutes=1)  # The original request has timed out.
    db.commit()
    return claim.id


def claim_state(db, claim_id):
    return db.query(SendingClaim.state).filter_by(id=claim_id).scalar()


import pytest  # noqa: E402


@pytest.fixture
def ended_send_lease(request, monkeypatch):
    """Model a review that happens after the original request window ended.

    Manual unsent confirmations refuse a claim still inside its provider
    lease (legacy_sending.send_lease_until). Tests of the release itself start
    claims whose window has already ended; tests marked ``real_send_lease``
    keep the production lease.
    """
    if request.node.get_closest_marker('real_send_lease'):
        return
    from app.invoice import legacy_sending
    monkeypatch.setattr(legacy_sending, 'send_lease_until', lambda: beijing_now() - timedelta(seconds=1))
