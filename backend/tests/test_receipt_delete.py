"""Standalone receipt deletion: isolated SQLite, live grants, no real OKKI calls."""
from copy import deepcopy
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.invoice import lifecycle_remote, okki_client
from app.invoice.models import Invoice
from app.receipt import deletion_service, remote, service, balance
from app.receipt.models import Receipt, ReceiptIntent, ReceiptLog, ReceiptAttempt
from app.receipt.schemas import ReceiptDeletion
from tests.authority_helpers import seed_authority

USER = {'sub': '1', 'roles': [], 'permissions': ['receipt:delete']}


@pytest.fixture
def receipt(db):
    seed_authority(db, 1, 'receipt:delete', 'receipt:read')
    invoice = Invoice(invoice_no='DELETE-RECEIPT', order_type='stock', customer_id='101',
        customer_name='Test', sales_user_id=1, created_by=1, invoice_date=date(2026, 10, 14),
        currency='USD', total_amount=Decimal('105'), surcharge_amount=Decimal('5'),
        xiaoman_order_id='2001', status='synced', sync_status='synced')
    db.add(invoice); db.flush()
    row = Receipt(receipt_no='HK-DELETE', invoice_id=invoice.id, source='auto',
        auto_key=f'invoice:{invoice.id}:initial', request_key='delete_receipt_key', request_hash='x',
        amount=105, bank_charge=5, currency='USD', customer_id='101', xiaoman_order_id='2001',
        collection_date=date(2026, 10, 14), payment_type='Other', created_by=1,
        attachment_ids=['original-proof'], xiaoman_receipt_id='701',
        status='active', sync_status='synced', collect_status=1, send_phase='verified')
    db.add(row); db.flush()
    db.add(ReceiptIntent(invoice_id=invoice.id, eligible=1, status='converted', receipt_id=row.id,
        amount=105, attachment_ids=['original-proof'], created_by=1))
    db.commit()
    return row.id, invoice.id


@pytest.fixture(autouse=True)
def okki(monkeypatch):
    detail = {'cash_collection_id': '701', 'cash_collection_no': 'HK-DELETE', 'order_id': '2001',
        'currency': 'USD', 'amount': '100', 'bank_charge': '0', 'real_amount': '100',
        'collection_date': '2026-10-14', 'collect_status': 1, 'update_time': '2026-10-14 10:00:00'}
    state = {'detail': detail, 'deleted': False, 'posts': 0, 'fail_delete': False, 'fail_read': False}
    monkeypatch.setattr(okki_client, 'ensure_access_token', lambda *a, **k: 'test-token')
    def request(token, kind, identity, *, remove=False):
        assert kind == 'receipt' and identity == '701'
        if remove:
            state['posts'] += 1
            if state['fail_delete']:
                raise okki_client.OkkiOutcomeUncertainError('unknown')
            state['deleted'] = True
            return True
        if state['fail_read']:
            raise okki_client.OkkiApiError('read unavailable')
        return deepcopy(state['detail'])
    monkeypatch.setattr(lifecycle_remote, 'request', request)
    def read(db, path, params):
        assert path == '/v1/invoices/receipt/list'
        rows = [deepcopy(state['detail'])] if bool(params['removed']) == state['deleted'] else []
        return {'list': rows, 'totalItem': len(rows)}
    monkeypatch.setattr(remote, 'read', read)
    monkeypatch.setattr(remote, 'order_receipts', lambda *a: [] if state['deleted'] else [deepcopy(detail)])
    return state


def preview(db, identity, user=USER):
    db.rollback()
    result = deletion_service.preview(db, identity, user)
    db.commit()
    return result


def remove(db, identity, proof, user=USER):
    db.rollback()
    body = ReceiptDeletion(expected_version=proof['expected_version'], confirmed=True, reason='用户重新提交回款')
    result = deletion_service.remove(db, identity, body, user)
    db.commit()
    return result


def test_owner_can_delete_only_receipt_and_register_again(db, receipt, okki):
    identity, invoice_id = receipt
    invoice_before = service.remote.invoice_binding(db.get(Invoice, invoice_id))
    proof = preview(db, identity)
    assert proof['remote_state'] == 'active' and proof['can_delete']
    result = remove(db, identity, proof)
    assert result['status'] == 'deleted' and okki['posts'] == 1
    row = db.get(Receipt, identity)
    assert row.status == 'remote_deleted' and row.amount == Decimal('105') and row.bank_charge == Decimal('5')
    assert row.attachment_ids == ['original-proof'] and row.xiaoman_receipt_id == '701'
    intent = db.query(ReceiptIntent).filter_by(invoice_id=invoice_id).one()
    assert intent.status == 'converted' and intent.receipt_id == identity
    invoice = db.get(Invoice, invoice_id)
    assert remote.invoice_binding(invoice) == invoice_before
    assert balance.calculate(db, invoice, {'rows': []})['remaining_amount'] == '105.00'
    assert db.query(ReceiptLog).filter_by(receipt_id=identity, action='delete_started').count() == 1
    remove(db, identity, proof)
    assert okki['posts'] == 1


def test_unknown_delete_is_quarantined_and_resume_never_resends(db, receipt, okki):
    identity, invoice_id = receipt
    proof = preview(db, identity)
    okki['fail_delete'] = True
    result = remove(db, identity, proof)
    assert result['status'] == 'uncertain' and okki['posts'] == 1
    assert db.get(Receipt, identity).status == 'active'
    assert db.get(Receipt, identity).recovery_kind == 'blocked'
    with pytest.raises(ValueError):
        balance.calculate(db, db.get(Invoice, invoice_id), {'rows': []})
    resume = preview(db, identity)
    assert resume['can_resume'] and not resume['can_delete']
    remove(db, identity, resume)
    assert okki['posts'] == 1
    okki['deleted'] = True
    assert remove(db, identity, preview(db, identity))['status'] == 'deleted'
    assert okki['posts'] == 1


@pytest.mark.parametrize('actor,codes,expected', [(1, ['receipt:write'], 403),
    (1, ['receipt:admin'], 403), (2, ['receipt:delete'], 404)])
def test_live_delete_grant_and_ownership_checked_before_remote(db, receipt, monkeypatch, actor, codes, expected):
    from app.auth.models import ArkRolePermission, ArkUserRole
    role_ids = [x.role_id for x in db.query(ArkUserRole).filter_by(user_id=actor)]
    db.query(ArkRolePermission).filter(ArkRolePermission.role_id.in_(role_ids)).delete(synchronize_session=False)
    db.commit()
    seed_authority(db, actor, *codes)
    monkeypatch.setattr(lifecycle_remote, 'request', lambda *a, **k: pytest.fail('No unauthorized remote reads'))
    with pytest.raises(HTTPException) as error:
        preview(db, receipt[0], {**USER, 'sub': str(actor)})
    assert error.value.status_code == expected


def test_changed_remote_amount_and_stale_preview_never_delete(db, receipt, okki):
    identity, _ = receipt
    proof = preview(db, identity)
    okki['detail']['amount'] = '99'
    with pytest.raises((ValueError, HTTPException)):
        remove(db, identity, proof)
    assert okki['posts'] == 0 and db.get(Receipt, identity).sync_status == 'synced'


def test_local_unsent_receipt_is_voided_without_remote_write(db, receipt, okki):
    identity, _ = receipt
    row = db.get(Receipt, identity)
    row.xiaoman_receipt_id = None; row.sync_status = 'failed'; row.collect_status = None
    db.commit()
    result = remove(db, identity, preview(db, identity))
    assert result['receipt']['status'] == 'voided' and okki['posts'] == 0


def test_returned_attempt_identity_prevents_local_void(db, receipt):
    identity, _ = receipt
    row = db.get(Receipt, identity)
    row.xiaoman_receipt_id = None; row.sync_status = 'failed'
    db.add(ReceiptAttempt(token='late-result', receipt_id=identity, remote_id='701'))
    db.commit()
    with pytest.raises(ValueError):
        preview(db, identity)


@pytest.mark.parametrize('field,value', [('purpose','presale_advance'), ('batch_id', 99),
    ('sync_status','syncing')])
def test_unsupported_funds_and_sending_receipts_are_blocked(db, receipt, field, value, okki):
    setattr(db.get(Receipt, receipt[0]), field, value); db.commit()
    with pytest.raises((ValueError, HTTPException)):
        preview(db, receipt[0])
    assert okki['posts'] == 0


def test_delete_in_progress_blocks_receipt_recovery_and_edits(db, receipt, okki):
    from app.receipt import authority
    proof = preview(db, receipt[0]); okki['fail_delete'] = True
    remove(db, receipt[0], proof)
    db.rollback()
    seed_authority(db, 1, 'receipt:write')
    with pytest.raises(HTTPException) as error:
        authority.local_group(db, receipt[0], USER, 'receipt:write')
    assert error.value.status_code == 409


def test_durable_marker_and_quarantine_exist_before_only_post(db, receipt, okki, monkeypatch):
    original = lifecycle_remote.request
    def checked(token, kind, identity, *, remove=False):
        if remove:
            assert not db.in_transaction(), 'No authority/receipt locks across destructive I/O'
            row = db.get(Receipt, receipt[0])
            assert row.sync_status == 'uncertain' and row.recovery_kind == 'blocked'
            assert db.query(ReceiptLog).filter_by(receipt_id=row.id, action='delete_started').count() == 1
            db.rollback()
        return original(token, kind, identity, remove=remove)
    monkeypatch.setattr(lifecycle_remote, 'request', checked)
    assert remove(db, receipt[0], preview(db, receipt[0]))['status'] == 'deleted'


def test_revoked_delete_grant_during_evidence_prevents_post(db, receipt, okki, monkeypatch):
    from app.auth.models import ArkPermission, ArkRolePermission
    proof = preview(db, receipt[0])
    original = deletion_service._read
    def revoke(db, target):
        evidence = original(db, target)
        permission = db.query(ArkPermission).filter_by(code='receipt:delete').one()
        db.query(ArkRolePermission).filter_by(permission_id=permission.id).delete()
        db.commit()
        return evidence
    monkeypatch.setattr(deletion_service, '_read', revoke)
    with pytest.raises(HTTPException) as error:
        remove(db, receipt[0], proof)
    assert error.value.status_code == 403 and okki['posts'] == 0


def test_remote_not_found_checks_global_identity_not_old_order(db, receipt, okki, monkeypatch):
    from app.receipt import receipt_index
    okki['detail'] = None
    monkeypatch.setattr(receipt_index, 'verified_rows', lambda *a: [
        {'cash_collection_id': '701', 'order_id': 'different-order'}])
    with pytest.raises(ValueError, match='有效索引'):
        preview(db, receipt[0])
    assert okki['posts'] == 0


def test_failed_readback_retains_marker_and_get_only_recovery(db, receipt, okki, monkeypatch):
    original = lifecycle_remote.request
    def fail_after_post(token, kind, identity, *, remove=False):
        result = original(token, kind, identity, remove=remove)
        if remove: okki['fail_read'] = True
        return result
    monkeypatch.setattr(lifecycle_remote, 'request', fail_after_post)
    assert remove(db, receipt[0], preview(db, receipt[0]))['status'] == 'uncertain'
    assert okki['posts'] == 1
    okki['fail_read'] = False
    assert remove(db, receipt[0], preview(db, receipt[0]))['status'] == 'deleted'
    assert okki['posts'] == 1


def test_stale_local_version_and_missing_confirmation_cannot_delete(db, receipt, okki):
    proof = preview(db, receipt[0])
    db.get(Receipt, receipt[0]).version += 1
    db.commit()
    with pytest.raises(HTTPException) as error:
        remove(db, receipt[0], proof)
    assert error.value.status_code == 409 and okki['posts'] == 0
    with pytest.raises(ValueError):
        db.rollback()
        deletion_service.remove(db, receipt[0], ReceiptDeletion(expected_version=proof['expected_version'],
            confirmed=False, reason='用户重新登记'), USER)
    assert okki['posts'] == 0


def test_real_api_preview_and_delete_envelopes(db, receipt):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.receipt.router import router
    app = FastAPI()
    app.include_router(router, prefix='/api/receipts')
    app.dependency_overrides[get_db] = lambda: (db.rollback(), db)[1]
    app.dependency_overrides[get_current_user] = lambda: USER
    with TestClient(app) as client:
        proof = client.get(f'/api/receipts/{receipt[0]}/deletion')
        assert proof.status_code == 200
        response = client.post(f'/api/receipts/{receipt[0]}/deletion', json={
            'expected_version': proof.json()['data']['expected_version'], 'reason': '用户重新提交回款', 'confirmed': True})
        assert response.status_code == 200
        assert response.json()['data']['receipt']['status'] == 'remote_deleted'


def test_prequeued_background_verification_cannot_unfreeze_deletion(db, receipt, okki, monkeypatch):
    from app.receipt import sync_service
    okki['fail_delete'] = True
    remove(db, receipt[0], preview(db, receipt[0]))
    row = db.get(Receipt, receipt[0])
    before = (row.version, row.sync_status, row.recovery_kind, row.last_error)
    db.rollback()
    monkeypatch.setattr(remote, 'receipt_info', lambda *a: pytest.fail('Deletion marker prevents background readback'))
    sync_service.refresh_accepted(db, receipt[0])
    row = db.get(Receipt, receipt[0])
    assert (row.version, row.sync_status, row.recovery_kind, row.last_error) == before
    with pytest.raises(ValueError, match='删除正在核验'):
        sync_service.bind_remote(db, row, okki['detail'], None)


def test_remote_unavailable_preview_returns_controlled_503_without_mutation(db, receipt, okki):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.receipt.router import router
    app = FastAPI()
    app.include_router(router, prefix='/api/receipts')
    app.dependency_overrides[get_db] = lambda: (db.rollback(), db)[1]
    app.dependency_overrides[get_current_user] = lambda: USER
    okki['fail_read'] = True
    with TestClient(app) as client:
        response = client.get(f'/api/receipts/{receipt[0]}/deletion')
        assert response.status_code == 503
    assert okki['posts'] == 0 and db.get(Receipt, receipt[0]).sync_status == 'synced'


def test_deletion_audit_contains_financial_facts_without_private_provider_urls(db, receipt, okki):
    okki['detail']['file_list'] = [{'url': 'https://private.example/proof?signature=private-sentinel'}]
    remove(db, receipt[0], preview(db, receipt[0]))
    marker = db.query(ReceiptLog).filter_by(receipt_id=receipt[0], action='delete_started').one()
    assert 'private-sentinel' not in marker.message and 'file_list' not in marker.message
    assert json.loads(marker.message)['remote_before']['detail']['amount'] == '100'
