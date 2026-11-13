"""Explicit resync recovery: isolated SQLite + supplier stubs, no live writes."""
from copy import deepcopy
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.invoice import deleted_outbound_recovery as recovery, order_sync_execution as orders
from app.invoice import linked_sync_service as linked, legacy_sending
from app.invoice.models import Invoice, OkkiOutboundTask
from app.shipping_inspection import outbound_facts as facts, outbound_service
from app.shipping_inspection.models import ShippingOperationEvent, ShippingInspection, ShippingInspectionPhoto
from tests.test_outbound_invoice_sync import (
    sync_case, case, outbound_scope_seed, product_display_source, _partial_additions,
)


@pytest.fixture
def deleted(db, sync_case, monkeypatch):
    user, fake, record, actor = _partial_additions(db, sync_case, monkeypatch)
    invoice_id = sync_case[1].id
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN status INTEGER DEFAULT 1'))
    outbound_service._columns_cache.clear()
    db.commit()
    monkeypatch.setattr(facts, 'expired', lambda _: True)
    monkeypatch.setattr(recovery.outbound_delete_client, 'observe', lambda *_: {'detail': deepcopy(fake['outbound']), 'active': False})
    monkeypatch.setattr(recovery.linked_outbound_service, 'find_related', lambda *_: [])
    monkeypatch.setattr(recovery.okki_client, 'ensure_access_token', lambda *_: 'fake-token')
    db.rollback()
    return invoice_id, actor, fake


def event(db):
    return db.query(ShippingOperationEvent).filter_by(scope='outbound-invoice-sync', request_id='OB001').one()


def run(db, deleted, **kwargs):
    db.rollback()
    return recovery.before_sync(db, deleted[0], deleted[1], **kwargs)


def test_resync_recovers_deleted_accepted_target_before_order_preparation(db, deleted, monkeypatch):
    class StopBeforeOrderPost(Exception):
        pass
    def prepare(*_args, **_kwargs):
        assert event(db).action == 'sync_failed'
        assert db.query(OkkiOutboundTask).one().reason == 'deleted:77'
        raise StopBeforeOrderPost()
    monkeypatch.setattr(orders, 'prepare', prepare)
    with pytest.raises(StopBeforeOrderPost):
        orders.run(db, deleted[0], deleted[1])
    # A failed/newly interrupted invoice push must not enqueue regeneration.
    assert db.query(OkkiOutboundTask).one().status == 'skipped'
    assert len(deleted[2]['posts']) == 1


def test_deleted_target_retires_facts_atomically_without_rewriting_claims_or_photos(db, deleted):
    original = db.query(ShippingOperationEvent).order_by(ShippingOperationEvent.id).all()
    immutable = {r.id: recovery.row_state(r) for r in original if r.scope in facts.SCOPES}
    attempt = facts.load(db, event(db))
    key = 'legacy:outbound-sync:' + attempt.nonce
    claim = recovery.row_state(legacy_sending.find(db, key))
    inspection = ShippingInspection(outbound_record_id='OB001', status='submitted', created_by=int(deleted[1]['sub']))
    db.add(inspection); db.flush()
    photo = ShippingInspectionPhoto(inspection_id=inspection.id, file_path='old-proof.jpg')
    db.add(photo); db.commit()
    inspection_id, photo_id = inspection.id, photo.id
    assert run(db, deleted) == {'outbound_invoice_id': '77', 'deleted': True}
    assert not facts.unresolved(db, 'OB001')
    assert event(db).action == 'sync_failed'
    finish = facts.get(db, facts.FINISH, attempt.nonce)
    assert finish.result['resolution'] == 'accepted_then_remote_deleted'
    assert 'not_sent' not in finish.result
    assert recovery.row_state(legacy_sending.find(db, key)) == claim
    assert all(recovery.row_state(db.get(ShippingOperationEvent, identity)) == before for identity, before in immutable.items())
    assert db.get(ShippingInspection, inspection_id).status == 'submitted'
    assert db.get(ShippingInspectionPhoto, photo_id).file_path == 'old-proof.jpg'
    assert outbound_service.get_outbound_record(db, 'OB001') is None
    tombstone = db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').one()
    assert tombstone.outbound_record_id == 'OB001' and tombstone.request_id == '77'
    assert db.query(OkkiOutboundTask).one().status == 'skipped'
    assert len(deleted[2]['posts']) == 1


def test_existing_tombstone_is_idempotent_and_keeps_generation_time(db, deleted):
    run(db, deleted)
    before = recovery.row_state(db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').one())
    assert run(db, deleted) is None
    assert recovery.row_state(db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').one()) == before


def test_done_task_without_sync_attempt_can_recover_changed_invoice(db, sync_case, monkeypatch):
    user, invoice, item, fake = sync_case
    identity, actor_id = invoice.id, user.id
    invoice.sync_status = 'not_synced'
    item.quantity = 9
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN status INTEGER DEFAULT 1'))
    db.commit(); outbound_service._columns_cache.clear()
    monkeypatch.setattr(recovery.outbound_delete_client, 'observe', lambda *_: {'detail': None, 'active': False})
    monkeypatch.setattr(recovery.linked_outbound_service, 'find_related', lambda *_: [])
    db.rollback()
    result = recovery.before_sync(db, identity, {'sub': str(actor_id)})
    assert result['deleted']
    assert db.get(Invoice, identity).sync_status == 'not_synced'
    assert db.query(OkkiOutboundTask).one().status == 'skipped'


@pytest.mark.parametrize('condition', ['active', 'young', 'unknown', 'other_outbound', 'mixed', 'duplicate', 'invalid_detail', 'event_drift', 'invoice_drift'])
def test_unsafe_evidence_never_retires_or_rebuilds(db, deleted, monkeypatch, condition):
    if condition == 'active':
        monkeypatch.setattr(recovery.outbound_delete_client, 'observe', lambda *_: {'detail': deepcopy(deleted[2]['outbound']), 'active': True})
    elif condition == 'young':
        monkeypatch.setattr(facts, 'expired', lambda _: False)
    elif condition == 'unknown':
        # Change only the provider observation accessor; immutable stored facts stay intact.
        original = facts.get
        from types import SimpleNamespace
        monkeypatch.setattr(facts, 'get', lambda db, scope, key, **kw: SimpleNamespace(result={'result_class':'unknown'})
                            if scope == facts.FACT else original(db, scope, key, **kw))
    elif condition == 'other_outbound':
        monkeypatch.setattr(recovery.linked_outbound_service, 'find_related', lambda *_: [{'outbound_invoice_id': 99}])
    elif condition == 'mixed':
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id=NULL WHERE id=(SELECT MIN(id) FROM lsordertest.okki_outbound_record_items WHERE outbound_invoice_id='77')"))
        db.commit()
    elif condition == 'duplicate':
        db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_invoice_id='88',company_id='101' WHERE id='OB002'"))
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_invoice_id='88',order_id='123' WHERE outbound_record_id='OB002'"))
        db.commit()
    else:
        calls = []
        def read(*_):
            if condition == 'invalid_detail':
                raise recovery.outbound_delete_client.DeleteRemoteError('supplier unavailable')
            if not calls:
                calls.append(True)
                if condition == 'event_drift':
                    event(db).result = {'message': 'changed concurrently'}
                else:
                    db.get(Invoice, deleted[0]).remark = 'changed concurrently'
                db.commit()
            return {'detail': None, 'active': False}
        monkeypatch.setattr(recovery.outbound_delete_client, 'observe', read)
    if condition in {'active', 'mixed', 'duplicate'}:
        assert run(db, deleted) is None
    else:
        with pytest.raises(HTTPException):
            run(db, deleted)
    assert event(db).action == 'sync_uncertain'
    assert db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').count() == 0
    assert db.query(ShippingOperationEvent).filter_by(scope=facts.FINISH).count() == 0
    assert db.query(OkkiOutboundTask).one().status == 'done'


@pytest.mark.parametrize('change', ['shipped', 'mixed', 'customer', 'changed_again'])
def test_soft_deleted_detail_must_still_prove_pending_single_order(db, deleted, monkeypatch, change):
    detail = deepcopy(deleted[2]['outbound'])
    if change == 'shipped':
        detail['status'] = 2
    elif change == 'mixed':
        detail['record_list'][0]['order_id'] = 999
    elif change == 'customer':
        detail['company_info']['id'] = '999'
    calls = []
    def observe(*_):
        result = deepcopy(detail)
        if calls and change == 'changed_again':
            result['remark'] = 'changed after scan'
        calls.append(True)
        return {'detail': result, 'active': False}
    monkeypatch.setattr(recovery.outbound_delete_client, 'observe', observe)
    with pytest.raises(HTTPException):
        run(db, deleted)
    assert event(db).action == 'sync_uncertain'
    assert db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').count() == 0
    assert len(deleted[2]['posts']) == 1


@pytest.mark.parametrize('layout', ['split', 'mixed', 'shipped'])
def test_ineligible_existing_outbounds_do_not_block_normal_order_push(db, sync_case, monkeypatch, layout):
    user, invoice, _, fake = sync_case
    identity, actor = invoice.id, {'sub': str(user.id)}
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN status INTEGER DEFAULT 1'))
    if layout in {'split', 'shipped'}:
        db.execute(text("UPDATE lsordertest.okki_outbound_records SET outbound_invoice_id='88',company_id='101' WHERE id='OB002'"))
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET outbound_invoice_id='88',order_id='123' WHERE outbound_record_id='OB002'"))
    if layout == 'shipped':
        db.execute(text('UPDATE lsordertest.okki_outbound_records SET status=2'))
    if layout == 'mixed':
        db.execute(text("UPDATE lsordertest.okki_outbound_record_items SET order_id='999' WHERE id=(SELECT MIN(id) FROM lsordertest.okki_outbound_record_items WHERE outbound_invoice_id='77')"))
    db.commit(); outbound_service._columns_cache.clear()
    class Prepared(Exception):
        pass
    def prepare(*_, **__):
        raise Prepared()
    monkeypatch.setattr(orders, 'prepare', prepare)
    with pytest.raises(Prepared):
        orders.run(db, identity, actor)
    assert db.query(ShippingOperationEvent).count() == 0


def test_commit_failure_rolls_back_finishes_tombstone_and_task(db, deleted, monkeypatch):
    original = db.commit
    def commit():
        if db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').first():
            from sqlalchemy.exc import OperationalError
            raise OperationalError('simulated', {}, Exception('commit failed'))
        original()
    monkeypatch.setattr(db, 'commit', commit)
    with pytest.raises(HTTPException):
        run(db, deleted)
    assert event(db).action == 'sync_uncertain'
    assert db.query(ShippingOperationEvent).filter_by(scope=facts.FINISH).count() == 0
    assert db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').count() == 0
    assert db.query(OkkiOutboundTask).one().status == 'done'


def test_python_worker_accepts_real_local_mirror_id_and_same_second_new_generation(db, deleted, monkeypatch):
    from app.invoice import outbound_worker as worker, outbound_followup_execution as followup
    from app.invoice.models import InvoiceSyncLog
    import json
    run(db, deleted)
    deletion = db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').one()
    # DATETIME second precision: causal successful-log ordering must survive.
    stamp = deletion.created_at.replace(microsecond=0)
    deletion.created_at = stamp
    invoice = db.get(Invoice, deleted[0]); invoice.outbound_auto_requested = 1
    log = InvoiceSyncLog(invoice_id=invoice.id, action='update', success=1,
                         response_body=json.dumps({'order_id':123}), created_at=stamp)
    db.add(log); db.flush()
    db.commit()
    assert followup.deletion_precedes_sync(deletion, log)
    monkeypatch.setattr(worker.get_settings(), 'OKKI_OUTBOUND_AUTO_ENABLED', True)
    monkeypatch.setattr(followup, 'evidence', lambda *_: ([], []))
    db.rollback()
    assert followup.run(db, deleted[0], deleted[1])['status'] == 'pending'
    task = db.query(OkkiOutboundTask).one()
    assert task.reason == f'regenerate:{log.id}'
    # A later successful audit entry must not replace the actual order generation.
    db.add(InvoiceSyncLog(invoice_id=deleted[0], action='outbound_followup', success=1))
    db.commit()
    db.rollback()
    db.info['outbound_manual_actor'] = int(deleted[1]['sub'])
    try:
        result = worker.local(db, deleted[0])
        assert result[-1]['regeneration'] is True
        assert result[-1]['deleted_outbound_id'] == '77'
    finally:
        db.rollback(); db.info.pop('outbound_manual_actor', None)


@pytest.mark.parametrize('value', [None, {}, False])
def test_incomplete_related_list_does_not_prove_absence(db, deleted, monkeypatch, value):
    monkeypatch.setattr(recovery.linked_outbound_service, 'find_related', lambda *_: value)
    with pytest.raises(HTTPException):
        run(db, deleted)
    assert event(db).action == 'sync_uncertain'
    assert db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').count() == 0


@pytest.mark.parametrize('stale', [True, False])
def test_saved_editor_checks_current_authority_and_version_before_recovery(db, deleted, monkeypatch, stale):
    from types import SimpleNamespace
    from tests.authority_helpers import seed_authority
    actor_id = int(deleted[1]['sub'])
    seed_authority(db, actor_id, 'invoice:sync', 'invoice:write', 'invoice:read_all')
    version = linked.edit_version(db.get(Invoice, deleted[0]))
    body = SimpleNamespace(expected_version='0'*64 if stale else version,
                           request_key='new-save-key', model_dump_json=lambda:'{}')
    reads=[]
    original = recovery.evidence
    monkeypatch.setattr(recovery, 'evidence', lambda *args: (reads.append(True), original(*args))[1])
    if stale:
        with pytest.raises(HTTPException):
            run(db, deleted, body=body)
        assert reads == []
        assert event(db).action == 'sync_uncertain'
    else:
        assert run(db, deleted, body=body)['deleted']


def test_authority_revocation_during_read_leaves_all_original_state(db, deleted, monkeypatch):
    from app.auth.models import ArkUser
    original = recovery.evidence
    def evidence(*args):
        result = original(*args)
        db.get(ArkUser, int(deleted[1]['sub'])).is_active = False
        db.commit()
        return result
    monkeypatch.setattr(recovery, 'evidence', evidence)
    with pytest.raises(HTTPException) as error:
        run(db, deleted)
    assert error.value.status_code == 403
    assert event(db).action == 'sync_uncertain'
    assert db.query(ShippingOperationEvent).filter_by(scope='outbound-delete').count() == 0


def test_real_preflight_preserves_active_linked_task_guidance(db, deleted):
    invoice = db.get(Invoice, deleted[0])
    invoice.linked_sync_id = 'active-existing-operation'
    db.commit(); db.rollback()
    with pytest.raises(HTTPException) as error:
        orders.run(db, deleted[0], deleted[1])
    assert error.value.status_code == 409
    assert error.value.headers['X-Ark-Linked-Sync'] == 'pending'
    assert error.value.headers['X-Ark-Linked-Sync-Id'] == 'active-existing-operation'
    assert event(db).action == 'sync_uncertain'


def test_failed_delete_audit_keeps_live_outbound_on_normal_sync_path(db, sync_case, monkeypatch):
    user, invoice, _, fake = sync_case
    identity, actor = invoice.id, {'sub': str(user.id)}
    db.execute(text('ALTER TABLE lsordertest.okki_outbound_records ADD COLUMN status INTEGER DEFAULT 1'))
    deletion = ShippingOperationEvent(scope='outbound-delete', request_id='77',
        outbound_record_id='OB001', action='delete_failed', source='test', login_user_id=user.id,
        operator_user_id=user.id, operator_name='Test', login_name='Test',
        payload={'outbound_invoice_id': '77'}, result={'message': 'locked'})
    db.add(deletion); db.commit(); outbound_service._columns_cache.clear()
    before = recovery.row_state(deletion)
    monkeypatch.setattr(recovery.outbound_delete_client, 'observe',
        lambda *_: {'detail': deepcopy(fake['outbound']), 'active': True})
    class Prepared(Exception):
        pass
    def prepare(*_, **__):
        raise Prepared()
    monkeypatch.setattr(orders, 'prepare', prepare)
    db.rollback()
    with pytest.raises(Prepared):
        orders.run(db, identity, actor)
    assert recovery.row_state(deletion) == before
    assert db.query(OkkiOutboundTask).one().status == 'done'
