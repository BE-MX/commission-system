"""Administrator retry of an uncertain presale freight target (SQLite, no HTTP).

Canonical name absence plus the administrator's attestation releases the
original unknown freight POST, which otherwise blocks the whole order.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.invoice import shipment_retry_service as retry
from tests.claim_helpers import claim_state, unknown_claim
from tests.test_commerce_manual_unlock import ready  # noqa: F401  (fixture reuse)

ADMIN = {'id': 1, 'roles': [], 'permissions': ['shipment:write', 'shipment:admin']}
WRITER = {'id': 2, 'roles': [], 'permissions': ['shipment:write']}


def case(db, ready, monkeypatch, current, *, exists=False):
    claim = unknown_claim(db, ready, 'legacy:freight:77:tok:1', 'freight_order_create', {'target_id': 77})
    target = SimpleNamespace(id=77, kind='freight', remote_status='uncertain', remote_order_id=None,
                             remote_order_name='FREIGHT-77', attempt_token='tok', lease_until=None,
                             last_error='待核对', version=3)
    row = SimpleNamespace(id=5, invoice_id=ready.id, state='awaiting_payment', version=9)
    lookup = retry.RetryTarget('freight', 77, 'FREIGHT-77', None)
    monkeypatch.setattr(retry, '_capture', lambda *a: (row, target, current, 'binding', lookup))
    monkeypatch.setattr(retry, '_read_evidence', lambda *a: retry.RetryEvidence(lookup, exists))
    monkeypatch.setattr(retry.shipments, 'describe', lambda *a, **k: {'remote_status': target.remote_status})
    monkeypatch.setattr(retry, 'SettlementEvent', lambda **k: SimpleNamespace(**k))
    monkeypatch.setattr(db, 'add', lambda *_: None)
    db.rollback()
    return claim, target, SimpleNamespace(version=9, reason='Checked OKKI: freight order absent')


def test_admin_retry_after_absence_releases_original_freight_claim(db, ready, monkeypatch):
    claim, target, body = case(db, ready, monkeypatch, ADMIN)
    retry.retry(db, 5, body, {'id': 1}, kind='freight')
    assert claim_state(db, claim) == 'not_sent' and target.remote_status == 'unverified'


def test_non_admin_cannot_retry_uncertain_freight(db, ready, monkeypatch):
    claim, target, body = case(db, ready, monkeypatch, WRITER)
    with pytest.raises(HTTPException) as denied:
        retry.retry(db, 5, body, {'id': 2}, kind='freight')
    assert denied.value.status_code == 403
    db.rollback()
    assert claim_state(db, claim) == 'unknown' and target.remote_status == 'uncertain'


def test_existing_remote_order_keeps_the_claim(db, ready, monkeypatch):
    claim, target, body = case(db, ready, monkeypatch, ADMIN, exists=True)
    with pytest.raises(ValueError, match='同名运费订单'):
        retry.retry(db, 5, body, {'id': 1}, kind='freight')
    db.rollback()
    assert claim_state(db, claim) == 'unknown'
