"""Isolated SQLite: a normal invoice follow-up completes accepted partial additions."""
from datetime import timedelta
from types import SimpleNamespace
import pytest
from fastapi import HTTPException

from app.invoice.models import Invoice
from app.invoice import outbound_followup_service as followup
from app.shipping_inspection import outbound_sync_service as sync
from app.shipping_inspection import outbound_sync_state as state
from app.shipping_inspection.models import ShippingInspection, ShippingInspectionPhoto, ShippingOperationEvent
from tests.test_outbound_invoice_sync import (
    sync_case, case, outbound_scope_seed, product_display_source, _partial_additions, _synchronize,
    _save_commercial_fixture,
)


def test_invoice_followup_automatically_completes_accepted_missing_rows(db, sync_case, monkeypatch):
    user, fake, record, actor = _partial_additions(db, sync_case, monkeypatch)
    invoice_id = sync_case[1].id
    db.rollback()
    result = followup._follow_existing(db, SimpleNamespace(id=invoice_id), actor,
                                       [fake['outbound']], force_authority=True)
    assert result['status'] == 'done'
    assert len(fake['posts']) == 3
    assert {row['order_record_id'] for row in fake['outbound']['record_list']} == {100, 101, 102, 103}


def test_legacy_binding_stays_strict_after_timestamp_touch(db, sync_case, monkeypatch):
    from app.shipping_inspection import outbound_binding
    monkeypatch.setattr(outbound_binding, 'CURRENT_VERSION', 1)
    _, fake, record, actor = _partial_additions(db, sync_case, monkeypatch)
    monkeypatch.setattr(outbound_binding, 'CURRENT_VERSION', 2)
    invoice = db.get(Invoice, sync_case[1].id)
    invoice.updated_at += timedelta(minutes=1)
    db.commit(); db.rollback()
    with pytest.raises(HTTPException) as error:
        _synchronize(db, record, actor, None, repair=True)
    assert error.value.status_code == 409 and len(fake['posts']) == 1


@pytest.mark.parametrize('value', [True, 0, 3, '2'])
def test_unknown_or_alias_binding_versions_are_rejected(value):
    from app.shipping_inspection.outbound_binding import fingerprint, version
    with pytest.raises(ValueError):
        version({'binding_version': value})
    with pytest.raises(ValueError):
        fingerprint((), value)


def test_audit_timestamp_touch_does_not_block_current_accepted_attempt_recovery(db, sync_case, monkeypatch):
    _, fake, record, actor = _partial_additions(db, sync_case, monkeypatch)
    invoice = db.get(Invoice, sync_case[1].id)
    invoice.updated_at += timedelta(minutes=1)
    db.commit(); db.rollback()
    first = _synchronize(db, record, actor, None, repair=True)
    assert first['repairable']
    assert _synchronize(db, record, actor, None, repair=True)['status'] == 'sync_done'
    assert len(fake['posts']) == 3


def test_same_total_quantity_shift_updates_original_and_preserves_reinspection(db, sync_case, monkeypatch):
    user, fake, record, actor = _partial_additions(db, sync_case, monkeypatch)
    _synchronize(db, record, actor, None, repair=True)
    assert _synchronize(db, record, actor, None, repair=True)['status'] == 'sync_done'
    invoice = db.get(Invoice, sync_case[1].id)
    old_ids = {str(row['order_record_id']): row['outbound_record_id'] for row in fake['outbound']['record_list']}
    inspection = ShippingInspection(outbound_record_id='OB001', status='submitted', created_by=user.id)
    db.add(inspection); db.flush()
    photo = ShippingInspectionPhoto(inspection_id=inspection.id, item_id=None, file_path='previous-whole-order.jpg')
    db.add(photo); db.flush()
    inspection_id, photo_id, invoice_id = inspection.id, photo.id, invoice.id
    for item in invoice.items:
        if item.xiaoman_unique_id in ('101', '102'):
            item.quantity = 3 if item.xiaoman_unique_id == '101' else 1
            item.total_price = item.price_per_piece * item.quantity
            row = next(row for row in fake['order']['product_list'] if str(row['unique_id']) == item.xiaoman_unique_id)
            row.update(count=item.quantity, cost_amount=float(item.total_price))
    _save_commercial_fixture(db, invoice, fake)
    db.rollback()
    result = followup._follow_existing(db, SimpleNamespace(id=invoice_id), actor,
                                       [fake['outbound']], force_authority=True)
    assert result['outbound_updated'] and result['category'] == 'inspection_recheck'
    assert sum(row['outbound_count'] for row in fake['outbound']['record_list']) == 8
    assert {str(row['order_record_id']): row['outbound_record_id'] for row in fake['outbound']['record_list']} == old_ids
    updated = {str(row['order_record_id']): row['outbound_count'] for row in fake['outbound']['record_list']}
    assert updated['101'] == 3 and updated['102'] == 1
    inspection = db.get(ShippingInspection, inspection_id)
    event = db.query(ShippingOperationEvent).filter_by(scope=state.SCOPE, request_id='OB001').one()
    assert inspection.status == 'draft' and inspection.edit_version == 1
    assert db.get(ShippingInspectionPhoto, photo_id) is not None
    assert photo_id in event.result['stale_media_ids']
    assert state.photo_requirements(event.result) == ['__whole__']
    assert not event.result.get('print_before_recheck')
