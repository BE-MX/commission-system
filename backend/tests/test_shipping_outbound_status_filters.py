"""Outbound filters match displayed states before scoped pagination."""
import json

import pytest

from app.shipping_inspection import outbound_queue_service as queue
from app.shipping_inspection.models import ShippingInspection
from tests.test_shipping_outbound_queue import waiting
from tests.test_shipping_inspection import _pc_client, outbound_scope_seed, product_display_source


@pytest.mark.parametrize('task_status,expected', [
    ('pending', 'pending'), ('running', 'running'), ('waiting_stock', 'waiting_stock'),
    ('done', 'awaiting_sync'), ('skipped', 'awaiting_sync'),
    ('failed', 'failed'), ('uncertain', 'uncertain'),
])
def test_outbound_filter_matches_displayed_task_state(db, waiting, task_status, expected):
    task = waiting[2]
    task.status, task.reason = task_status, 'existing:123'
    db.commit()
    rows, total = queue.list_outbound_records(db, outbound_state=expected, okki_user_id='9001')
    assert total == 1 and rows[0]['outbound_record_id'] == f'task:{task.id}'
    assert rows[0]['outbound_state'] == expected
    assert queue.list_outbound_records(db, outbound_state=expected, okki_user_id='9002')[1] == 0
    rows, total = queue.list_outbound_records(db, outbound_state='ready', okki_user_id='9001')
    assert total == 1 and rows[0]['outbound_record_id'] == 'OB001'


def test_retrying_filter_excludes_terminal_failure(db, waiting):
    task = waiting[2]
    task.status, task.attempts = 'failed', 1
    task.last_error = json.dumps({'outcome': 'pre_submit_failed', 'attempts': 1,
                                  'max_attempts': 5, 'retry_delay_minutes': 10})
    db.commit()
    rows, total = queue.list_outbound_records(db, outbound_state='retrying')
    assert total == 1 and rows[0]['outbound_state'] == 'retrying'
    assert queue.list_outbound_records(db, outbound_state='failed')[1] == 0
    task.last_error = 'invalid JSON'
    db.commit()
    assert queue.list_outbound_records(db, outbound_state='retrying')[1] == 0
    assert queue.list_outbound_records(db, outbound_state='failed')[1] == 1


@pytest.mark.parametrize('status', ['none', 'draft', 'submitted'])
def test_inspection_filter_excludes_local_tasks_and_applies_before_pagination(db, waiting, status):
    if status != 'none':
        db.add(ShippingInspection(outbound_record_id='OB001', status=status))
        db.add(ShippingInspection(outbound_record_id='OB002', status=status))
        db.commit()
    for page, expected in [(1, 1), (2, 1), (3, 0)]:
        rows, total = queue.list_outbound_records(db, inspection_status=status,
            outbound_state='ready', page=page, page_size=1, sort_field='outbound_no', sort_order='asc')
        assert total == 2 and len(rows) == expected
        assert all(row['record_source'] == 'okki' for row in rows)
    rows, total = queue.list_outbound_records(db, inspection_status=status, okki_user_id='9001')
    assert total == 1 and rows[0]['outbound_record_id'] == 'OB001'
    assert queue.list_outbound_records(db, inspection_status=status, outbound_state='waiting_stock')[1] == 0
    assert queue.list_outbound_records(db, inspection_status=status, keyword='WAIT')[1] == 0
    if status != 'none':
        assert queue.list_outbound_records(db, inspection_status='none')[1] == 0


def test_api_combines_filters_and_rejects_unknown_values(db, waiting):
    db.add(ShippingInspection(outbound_record_id='OB001', status='draft'))
    db.commit()
    with _pc_client(db, waiting[0], ['shipping_inspection:read']) as client:
        url = '/api/shipping-inspection/outbound-records'
        response = client.get(url, params={'outbound_state': 'ready', 'inspection_status': 'draft'})
        assert response.status_code == 200
        data = response.json()['data']
        assert data['total'] == 1 and data['items'][0]['status'] == 'draft'
        assert client.get(url, params={'inspection_status': 'submitted'}).json()['data']['total'] == 0
        for field in ('outbound_state', 'inspection_status'):
            assert client.get(url, params={field: 'invalid'}).status_code == 422
