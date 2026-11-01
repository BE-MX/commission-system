"""Admin abandon of a timed-out receipt deletion whose receipt still exists (SQLite, mocked OKKI).

The original removal claim (receipt_remove) otherwise blocks every legacy send
of the order. Mirrors the outbound delete abandon: canonical readback must
show the receipt still active; the claim closes as not_sent with audit and the
receipt returns to its pre-delete synced state.
"""
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commerce_transition.models import ClaimEvidence, SendingClaim
from app.invoice import legacy_sending as gate
from app.receipt.models import Receipt, ReceiptLog
from tests.authority_helpers import seed_authority
from tests.claim_helpers import ended_send_lease  # noqa: F401  (fixture)
from tests.test_commerce_legacy_transition_sending import ready, receipt  # noqa: F401  (fixture reuse)

ACTIVE = {'status': 'active', 'detail': {'cash_collection_id': '701', 'order_id': '2001', 'amount': '10.00',
                                         'currency': 'USD', 'collect_status': 1}}
REASON = 'Checked OKKI: receipt 701 is still present'


@pytest.fixture(autouse=True)
def _ended_send_lease(request, ended_send_lease):
    """The original delete request window has ended unless a test keeps the real lease."""


def stuck_delete(db, ready, monkeypatch):
    from app.receipt import deletion_service
    identity = receipt(db, ready.id, 'abandon-receipt-delete')
    row = db.get(Receipt, identity)
    row.sync_status = 'synced'; row.xiaoman_receipt_id = '701'; row.collect_status = 1
    db.commit(); db.rollback()
    monkeypatch.setattr(deletion_service, '_read', lambda *a: dict(ACTIVE))
    preview = deletion_service.preview(db, identity, {'id': 1}); db.commit()
    def request(method, url, **kwargs):
        with Session(db.get_bind()) as observer:
            assert observer.scalar(select(SendingClaim)).state == 'sending'
        raise httpx.ReadTimeout('original delete unknown')
    monkeypatch.setattr(httpx, 'request', request)
    body = SimpleNamespace(confirmed=True, reason='Original reviewed receipt deletion',
                           expected_version=preview['expected_version'], resolution=None)
    assert deletion_service.remove(db, identity, body, {'id': 1})['status'] == 'uncertain'
    db.commit()
    monkeypatch.setattr(httpx, 'request', lambda *a, **k: pytest.fail('abandon must not send'))
    assert db.scalar(select(SendingClaim)).state == 'unknown'
    return identity, body


def abandon(db, identity, body, user, reason=REASON):
    from app.receipt import deletion_service
    db.rollback()
    result = deletion_service.remove(db, identity, SimpleNamespace(**{**vars(body), 'resolution': 'abandon',
                                                                       'reason': reason}), user)
    db.commit()
    return result


def test_admin_abandon_releases_removal_claim_and_restores_receipt(db, ready, monkeypatch):
    identity, body = stuck_delete(db, ready, monkeypatch)
    with pytest.raises(ValueError, match='正在发送或结果未知'):  # The whole order is blocked.
        gate.start(db, ready, 'other-object', 'order_push', {'order_id': '2001'}, {}, 1)
    db.rollback()
    result = abandon(db, identity, body, {'id': 1})
    assert result['status'] == 'abandoned' and result['message']
    claim = db.scalar(select(SendingClaim))
    assert claim.state == 'not_sent' and claim.operation == 'receipt_remove'
    proof = db.query(ClaimEvidence).filter_by(claim_id=claim.id, outcome='not_sent').one()
    assert proof.evidence['source'] == 'receipt.delete_abandon' and proof.evidence['reason'] == REASON
    assert proof.evidence['remote_evidence']['remote_still_exists'] is True
    row = db.get(Receipt, identity)
    assert row.status == 'active' and row.sync_status == 'synced' and row.last_error is None
    assert row.recovery_kind is None
    log = db.query(ReceiptLog).filter_by(receipt_id=identity, action='delete_abandoned').one()
    assert log.created_by == 1 and REASON in log.message
    from app.receipt import deletion_service
    assert not deletion_service.pending(db, row)  # The receipt can be edited or deleted again.
    db.rollback()
    gate.start(db, ready, 'other-object', 'order_push', {'order_id': '2001'}, {}, 1)  # Order is free.
    db.rollback()


def test_abandon_requires_receipt_admin_and_reason(db, ready, monkeypatch):
    identity, body = stuck_delete(db, ready, monkeypatch)
    seed_authority(db, 4, 'receipt:delete', 'receipt:read_all')
    with pytest.raises(HTTPException) as denied:
        abandon(db, identity, body, {'id': 4})
    assert denied.value.status_code == 403
    db.rollback()
    with pytest.raises(ValueError, match='8'):
        abandon(db, identity, body, {'id': 1}, reason='short')
    db.rollback()
    assert db.scalar(select(SendingClaim)).state == 'unknown'


def test_abandon_refused_when_readback_does_not_show_the_receipt(db, ready, monkeypatch):
    from app.receipt import deletion_service
    identity, body = stuck_delete(db, ready, monkeypatch)
    monkeypatch.setattr(deletion_service, '_read', lambda *a: {'status': 'deleted', 'detail': None})
    with pytest.raises(HTTPException) as refused:
        abandon(db, identity, body, {'id': 1})
    assert refused.value.status_code == 409
    db.rollback()
    assert db.scalar(select(SendingClaim)).state == 'unknown'
    assert db.get(Receipt, identity).sync_status == 'uncertain'


@pytest.mark.real_send_lease
def test_abandon_inside_the_original_send_lease_is_a_readable_409(db, ready, monkeypatch):
    identity, body = stuck_delete(db, ready, monkeypatch)
    with pytest.raises(ValueError, match='租约'):
        abandon(db, identity, body, {'id': 1})
    db.rollback()
    assert db.scalar(select(SendingClaim)).state == 'unknown'
