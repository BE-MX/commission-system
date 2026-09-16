"""SQLite-only submission/ownership tests; DingTalk is always a fake."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.core.time import beijing_now
from app.auth.models import ArkUserExternalBinding
from app.invoice.models import InvoiceCustomerOverlay
from app.shipping_inspection import notification_service as notices, outbound_service, service
from app.shipping_inspection.models import ShippingInspection
from tests.test_shipping_inspection import _user, _mini_client, _pc_client, _upload, storage, product_display_source
from tests.test_shipping_station import people, scan, photo


@pytest.fixture
def owner(db, monkeypatch):
    now = beijing_now()
    seller = _user(db, 'current-salesperson')
    seller.dingtalk_id = 'ding-current-owner'
    binding = ArkUserExternalBinding(ark_user_id=seller.id, provider='okki', external_account_id='1001', binding_status='active')
    db.add(binding)
    db.execute(text('ALTER TABLE lsordertest.customer_info ADD COLUMN update_time TEXT'))
    db.execute(text("INSERT OR REPLACE INTO lsordertest.customer_info (company_id, company_name, owner_user_ids, update_time) VALUES ('C001','客户甲','[1001]','2026-09-17 00:00:00')"))
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN company_id TEXT'))
    db.execute(text("UPDATE lsordertest.okki_outbound_records SET company_id='C001' WHERE id='OB001'"))
    outbound_service._columns_cache.clear()
    db.commit()
    notifier = AsyncMock()
    notifier.send_oa_notice.return_value = True
    monkeypatch.setattr(notices, 'get_work_notifier', lambda: notifier)
    yield seller, binding, notifier
    outbound_service._columns_cache.clear()


def mini_submit(client, version=0):
    return client.post('/api/mini/shipping-inspection/submit', json={
        'outbound_record_id':'OB001', 'request_id':'submit', 'edit_version':version})


def test_mini_commit_notifies_current_owner_once_and_recall_resubmission_notifies_again(db, storage, owner):
    seller, binding, notifier = owner
    inspector = _user(db, 'inspector')
    with _mini_client(db, inspector) as client:
        assert mini_submit(client).status_code == 400
        notifier.send_oa_notice.assert_not_awaited()
        _upload(client)
        response = mini_submit(client)
        assert response.status_code == 200
        assert mini_submit(client).status_code == 200
        notifier.send_oa_notice.assert_awaited_once_with(['ding-current-owner'], '出库检验完成',
            '客户【客户甲】的【CK2026001】出库单已出库检验完成，请及时验货。')
        service.recall(db, response.json()['id'], inspector.id, 0)
        replacement = _user(db, 'new-salesperson')
        replacement.dingtalk_id = 'ding-new-owner'
        binding.ark_user_id = replacement.id
        db.commit()
        assert mini_submit(client, 1).status_code == 200
        assert notifier.send_oa_notice.await_count == 2
        assert notifier.send_oa_notice.call_args.args[0] == ['ding-new-owner']


def test_station_commits_before_notice_and_replay_is_silent(db, storage, owner, people):
    _, _, notifier = owner
    login, inspector, _ = people
    async def send(*args):
        assert db.query(ShippingInspection).one().status == 'submitted'
        return True
    notifier.send_oa_notice.side_effect = send
    with _pc_client(db, login, []) as client:
        sid = scan(client, inspector).json()['data']['session_id']
        photo(client, sid)
        for _ in range(2):
            response = client.post(f'/api/shipping-inspection/station/sessions/{sid}/submit',
                json={'request_id':'same-submit', 'edit_version':0})
            assert response.status_code == 200
    notifier.send_oa_notice.assert_awaited_once()


@pytest.mark.parametrize('missing', ['dingtalk', 'inactive', 'deleted', 'binding', 'public', 'invalid'])
def test_ineligible_owner_does_not_send_or_block_submission(db, storage, owner, missing):
    seller, binding, notifier = owner
    if missing == 'dingtalk': seller.dingtalk_id = None
    if missing == 'inactive': seller.is_active = False
    if missing == 'deleted': seller.deleted_at = beijing_now()
    if missing == 'binding': binding.binding_status = 'inactive'
    if missing in ('public', 'invalid'):
        db.execute(text("UPDATE lsordertest.customer_info SET owner_user_ids=:value WHERE company_id='C001'"), {'value': '[]' if missing == 'public' else 'invalid'})
    db.commit()
    with _mini_client(db, _user(db, 'inspector')) as client:
        _upload(client)
        assert mini_submit(client).status_code == 200
    notifier.send_oa_notice.assert_not_awaited()


def test_notification_failure_keeps_committed_inspection_and_does_not_retry(db, storage, owner):
    notifier = owner[-1]
    notifier.send_oa_notice.side_effect = RuntimeError('simulated provider error')
    with _mini_client(db, _user(db, 'inspector')) as client:
        _upload(client)
        assert mini_submit(client).status_code == 200
        assert mini_submit(client).status_code == 200
    assert db.query(ShippingInspection).one().status == 'submitted'
    notifier.send_oa_notice.assert_awaited_once()


def test_failed_commit_never_sends(db, storage, owner, monkeypatch):
    inspector = _user(db, 'inspector')
    with _mini_client(db, inspector) as client:
        _upload(client)
        def fail(): raise RuntimeError('commit failed')
        monkeypatch.setattr(db, 'commit', fail)
        with pytest.raises(RuntimeError, match='commit failed'):
            mini_submit(client)
    owner[-1].send_oa_notice.assert_not_awaited()
    assert db.query(ShippingInspection).one().status == 'draft'



def test_ambiguous_external_binding_is_not_guessed(db, owner):
    other = _user(db, 'other-salesperson')
    db.add(ArkUserExternalBinding(ark_user_id=other.id, provider='okki', external_account_id='1001', binding_status='active'))
    db.flush()
    assert notices.current_salespeople(db, 'OB001') == []


@pytest.mark.parametrize('mirror_time,overlay_time,expected', [
    ('2026-09-17 00:00:00','2026-09-17 00:00:01',False),
    ('2026-09-17 00:00:01','2026-09-17 00:00:01',True),
    ('2026-09-17 00:00:02','2026-09-17 00:00:01',True),
    (None,'2026-09-17 00:00:01',False),
    ('2026-09-17 00:00:00',None,False),
    ('2026-09-17 00:00:00','2026-09-16T16:00:01Z',False),
])
def test_newer_manual_sync_can_move_customer_to_public_pool(db, owner, mirror_time, overlay_time, expected):
    db.execute(text("UPDATE lsordertest.customer_info SET update_time=:ts WHERE company_id='C001'"), {'ts':mirror_time})
    db.add(InvoiceCustomerOverlay(company_id='C001', company_name='客户甲', owner_user_ids=[], source_update_time=overlay_time))
    db.flush()
    assert bool(notices.current_salespeople(db, 'OB001')) is expected


def test_source_epoch_is_beijing_not_host_timezone():
    from datetime import datetime
    assert notices.source_time('1789574401') == datetime(2026, 9, 17, 0, 0, 1)


def test_multiple_current_owners_deduplicate_same_platform_user(db, owner):
    db.add(ArkUserExternalBinding(ark_user_id=owner[0].id, provider='okki', external_account_id='1002', binding_status='active'))
    db.execute(text("UPDATE lsordertest.customer_info SET owner_user_ids='[1001,1002,1001]' WHERE company_id='C001'"))
    db.flush()
    assert [u.id for u in notices.current_salespeople(db, 'OB001')] == [owner[0].id]
