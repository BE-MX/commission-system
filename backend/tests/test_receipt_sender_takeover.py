"""Receipt sender eligibility and audited takeover (isolated SQLite, mocked OKKI).

The original registrant sends while still active, holding receipt:write and the
same invoice scope used at registration (delegated order creators included).
When the registrant no longer qualifies, the scheduler blocks; a currently
authorized owner retrying the receipt takes it over with an immutable audit.
"""
import json

import httpx
import pytest
from fastapi import HTTPException

from app.auth.models import ArkUser
from app.commerce_transition.models import SendingClaim
from app.core.time import beijing_today
from app.invoice.models import Invoice, InvoiceDelegateGrant
from app.receipt.models import Receipt, ReceiptLog
from tests.authority_helpers import seed_authority
from tests.test_commerce_legacy_transition_sending import pushable  # noqa: F401  (fixture reuse)
from tests.test_commerce_manual_unlock import ready, receipts  # noqa: F401  (fixture reuse)

OWNER = {'id': 1, 'sub': '1', 'roles': ['super_admin'], 'permissions': []}


def receipt_by(db, invoice_id, key, actor, source='manual'):
    row = Receipt(receipt_no=key, invoice_id=invoice_id, source=source, request_key=key, request_hash='a' * 64,
                  amount=10, bank_charge=0, currency='USD', customer_id='101',
                  collection_date=beijing_today(),
                  payment_type='T/T', attachment_ids=[], xiaoman_order_id='2001', sync_status='pending',
                  created_by=actor, purpose='ordinary')
    db.add(row); db.commit(); identity = row.id; db.rollback()
    return identity


def deliver(db, monkeypatch, identity, remote_id):
    from app.receipt import sync_service
    posts = []

    def post(*a, **k):
        posts.append(k.get('json'))
        return httpx.Response(200, json={'code': 200, 'data': {'cash_collection_id': remote_id,
                                                              'cash_collection_no': f'HK{remote_id}'}})
    monkeypatch.setattr(httpx, 'post', post)
    db.rollback()
    sync_service.deliver(db, identity)
    db.rollback()
    return posts


def retry(db, identity, user):
    from app.receipt import retry_service
    db.rollback()
    retry_service.retry(db, identity, user)
    db.commit()


def takeovers(db, identity):
    return db.query(ReceiptLog).filter_by(receipt_id=identity, action='sender_takeover').order_by(ReceiptLog.id).all()


def test_delegated_assistant_auto_receipt_is_sent(db, receipts, monkeypatch):
    # The assistant built the order for salesperson 1 and saved it (intent.created_by).
    seed_authority(db, 5, 'receipt:write', 'invoice:write')
    db.add(InvoiceDelegateGrant(delegate_user_id=5, sales_user_id=1))
    db.get(Invoice, receipts.id).created_by = 5
    db.commit()
    identity = receipt_by(db, receipts.id, 'assistant-auto', 5, source='auto')
    posts = deliver(db, monkeypatch, identity, '801')
    saved = db.get(Receipt, identity)
    assert saved.sync_status == 'synced' and saved.xiaoman_receipt_id == '801', saved.last_error
    assert len(posts) == 1 and takeovers(db, identity) == []
    claim = db.query(SendingClaim).filter_by(operation='receipt_push').one()
    assert claim.responsibilities['actor_id'] == 5


def test_assistant_without_receipt_write_is_not_a_sender(db, receipts, monkeypatch):
    seed_authority(db, 5, 'invoice:write')
    db.add(InvoiceDelegateGrant(delegate_user_id=5, sales_user_id=1))
    db.get(Invoice, receipts.id).created_by = 5
    db.commit()
    identity = receipt_by(db, receipts.id, 'assistant-no-write', 5, source='auto')
    assert deliver(db, monkeypatch, identity, '802') == []
    saved = db.get(Receipt, identity)
    assert saved.sync_status == 'failed' and saved.recovery_kind == 'blocked'


def test_departed_registrant_blocks_then_owner_retry_takes_over_with_audit(db, receipts, monkeypatch):
    seed_authority(db, 6, 'receipt:write', roles=('super_admin',))
    identity = receipt_by(db, receipts.id, 'departed-registrant', 6)
    db.get(ArkUser, 6).is_active = False
    db.commit()
    assert deliver(db, monkeypatch, identity, '803') == []
    blocked = db.get(Receipt, identity)
    assert blocked.sync_status == 'failed' and blocked.recovery_kind == 'blocked'
    assert '原登记人已停用或无权' in blocked.last_error and '订单负责人点重试接手' in blocked.last_error
    assert db.query(SendingClaim).count() == 0
    db.rollback()

    retry(db, identity, OWNER)
    [audit] = takeovers(db, identity)
    detail = json.loads(audit.message)
    assert audit.created_by == 1 and audit.created_at is not None
    assert detail['from_actor'] == 6 and detail['to_actor'] == 1
    assert detail['reason'] and detail['at']
    assert db.get(Receipt, identity).created_by == 6  # Registration fact is never rewritten.

    posts = deliver(db, monkeypatch, identity, '804')
    saved = db.get(Receipt, identity)
    assert saved.sync_status == 'synced' and saved.xiaoman_receipt_id == '804', saved.last_error
    assert len(posts) == 1
    claim = db.query(SendingClaim).filter_by(operation='receipt_push').one()
    assert claim.responsibilities['actor_id'] == 1


def test_valid_registrant_is_kept_when_another_user_retries(db, receipts, monkeypatch):
    seed_authority(db, 9, 'receipt:write', 'receipt:read_all')
    identity = receipt_by(db, receipts.id, 'valid-registrant', 9)
    db.query(Receipt).filter_by(id=identity).update({'sync_status': 'failed', 'recovery_kind': 'blocked'})
    db.commit()
    retry(db, identity, OWNER)
    assert takeovers(db, identity) == []
    deliver(db, monkeypatch, identity, '805')
    claim = db.query(SendingClaim).filter_by(operation='receipt_push').one()
    assert claim.responsibilities['actor_id'] == 9


def test_unauthorized_user_retry_is_refused_without_takeover(db, receipts, monkeypatch):
    seed_authority(db, 6, 'receipt:write')
    identity = receipt_by(db, receipts.id, 'refused-retry', 6)
    db.get(ArkUser, 6).is_active = False
    db.commit()
    deliver(db, monkeypatch, identity, '806')
    assert db.get(Receipt, identity).sync_status == 'failed'
    seed_authority(db, 7, 'receipt:read')
    with pytest.raises(HTTPException) as denied:
        retry(db, identity, {'id': 7, 'sub': '7'})
    assert denied.value.status_code == 403
    db.rollback()
    seed_authority(db, 8, 'receipt:write')  # Not the salesperson, no read-all scope.
    with pytest.raises(HTTPException) as hidden:
        retry(db, identity, {'id': 8, 'sub': '8'})
    assert hidden.value.status_code == 404
    db.rollback()
    assert takeovers(db, identity) == []
    assert db.get(Receipt, identity).sync_status == 'failed'
