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
