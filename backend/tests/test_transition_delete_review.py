"""Adversarial deletion boundaries; SQLite and explicit provider responses only."""
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.commerce_transition.models import SendingClaim, ClaimEvidence, InvoiceAuthority
from app.invoice.models import Invoice, OkkiOutboundTask
from app.shipping_inspection import outbound_delete_service as deletion, outbound_delete_client as remote, outbound_service
from app.shipping_inspection.models import ShippingOperationEvent
from tests.authority_helpers import seed_authority
from tests.test_outbound_delete import case, install_remove
from tests.test_shipping_inspection import outbound_scope_seed, product_display_source, _user


def test_revoked_live_delete_grant_never_creates_original_send(db, case):
    user, invoice, task, state = case
    seed_authority(db, user.id, 'shipping_inspection:delete', 'shipping_inspection:read_all')
    record = outbound_service.get_outbound_record(db, 'OB001')
    user.is_active = False
    db.commit()
    with pytest.raises(HTTPException) as denied:
        deletion.delete_outbound(db, record, user.id)
    assert denied.value.status_code == 403
    db.rollback()
    assert state['posts'] == 0 and db.query(SendingClaim).count() == 0
    assert db.get(OkkiOutboundTask, task.id).reason == 'created: OLD'
    assert db.get(Invoice, invoice.id).xiaoman_order_id == '123'


def test_owner_transfer_during_provider_capture_prevents_new_delete_claim(db, case, monkeypatch):
    user, invoice, task, state = case
    from app.auth.models import ArkUserRole
    # The shared fixture grants read_all for its other tests; this actor must
    # retain only ownership-scoped deletion for the transfer boundary.
    db.query(ArkUserRole).filter_by(user_id=user.id).delete(synchronize_session=False)
    seed_authority(db, user.id, 'shipping_inspection:delete')
    other = _user(db, 'new-delete-owner')
    other_id, actor_id, invoice_id = other.id, user.id, invoice.id
    db.commit()
    record = outbound_service.get_outbound_record(db, 'OB001')
    original_read = remote.read
    changed = []
    def reassign(token, identity):
        result = original_read(token, identity)
        if not changed:
            changed.append(True)
            db.get(Invoice, invoice_id).sales_user_id = other_id
            db.execute(text("UPDATE lsordertest.okki_orders SET user_id='9002' WHERE company_id='C1'"))
            db.commit()
        return result
    monkeypatch.setattr(remote, 'read', reassign)
    with pytest.raises(HTTPException) as hidden:
        deletion.delete_outbound(db, record, actor_id)
    assert hidden.value.status_code == 404
    db.rollback()
    assert changed == [True] and state['posts'] == 0
    assert db.query(SendingClaim).count() == 0
    assert db.get(OkkiOutboundTask, task.id).reason == 'created: OLD'


def test_late_delete_readback_survives_epoch_freeze_without_business_completion(db, case, monkeypatch):
    user, invoice, task, state = case
    seed_authority(db, user.id, 'shipping_inspection:delete', 'shipping_inspection:read_all')
    actor_id, invoice_id, task_id = user.id, invoice.id, task.id
    db.commit()
    record = outbound_service.get_outbound_record(db, 'OB001')
    posts = []
    def timeout_after_freeze(token, identity):
        assert not db.in_transaction()
        posts.append(identity)
        authority = db.get(InvoiceAuthority, invoice_id)
        authority.epoch += 1
        authority.state = 'frozen'
        db.commit()
        state['exists'] = False
        raise remote.DeleteRemoteError('Original response lost after deletion', uncertain=True)
    install_remove(monkeypatch, timeout_after_freeze)
    with pytest.raises(ValueError):
        deletion.delete_outbound(db, record, actor_id)
    db.rollback()
    original = db.query(SendingClaim).filter_by(invoice_id=invoice_id, operation='outbound_remove').one()
    assert posts == ['77']
    assert original.state == 'succeeded' and original.external_id == '77' and original.epoch == 1
    assert any(row.evidence.get('original_request_readback') for row in db.query(ClaimEvidence).filter_by(claim_id=original.id))
    event = db.query(ShippingOperationEvent).filter_by(scope=deletion.SCOPE, request_id='77').one()
    assert event.action == deletion.PENDING
    assert db.get(OkkiOutboundTask, task_id).reason == 'delete_pending:77'
    assert db.get(InvoiceAuthority, invoice_id).state == 'frozen'
