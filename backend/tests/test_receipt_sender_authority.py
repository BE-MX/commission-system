"""The real legacy delivery must recheck its original human at claim time."""
import httpx
import pytest
from sqlalchemy import select
from app.auth.models import ArkUser, ArkUserRole, ArkRolePermission
from app.commerce_transition.models import SendingClaim
from app.invoice import okki_client
from app.invoice.models import Invoice
from app.receipt import attachments, remote, sync_service
from app.receipt.models import Receipt, ReceiptAttempt
from tests.authority_helpers import seed_authority
from tests.test_commerce_legacy_transition_sending import ready, receipt


@pytest.fixture
def delivery(db, ready, monkeypatch):
    actor = ready.created_by
    prior_roles=set(db.scalars(select(ArkUserRole.role_id).where(ArkUserRole.user_id==actor)))
    seed_authority(db, actor, 'receipt:write')
    db.query(ArkUserRole).filter(ArkUserRole.user_id==actor,ArkUserRole.role_id.in_(prior_roles)).delete(synchronize_session=False)
    ready.sales_user_id = actor
    db.commit()
    identity = receipt(db, ready.id, 'live-sender-proof')
    monkeypatch.setattr(remote,'order_snapshot',lambda db,invoice:{'rows':[],'exchange_rate':1,'invoice_binding':remote.invoice_binding(invoice)})
    monkeypatch.setattr(remote,'receipt_types',lambda db:['T/T'])
    monkeypatch.setattr(remote,'read',lambda *a,**k:[])
    monkeypatch.setattr(attachments,'bind',lambda *a,**k:None)
    monkeypatch.setattr(okki_client,'ensure_access_token',lambda *a,**k:'isolated')
    monkeypatch.setattr(sync_service,'refresh_accepted',lambda *a:None)
    posts=[]
    def post(*args,**kwargs):
        assert not db.in_transaction()
        posts.append(kwargs.get('json'))
        return httpx.Response(200,json={'code':200,'data':{'cash_collection_id':701,'cash_collection_no':'HK701'}})
    monkeypatch.setattr(httpx,'post',post)
    return identity, actor, posts


@pytest.mark.parametrize('change', ['inactive', 'permission', 'scope'])
def test_revoked_original_sender_cannot_create_receipt_claim(db, delivery, change):
    identity, actor, posts = delivery
    row = db.get(Receipt,identity)
    if change=='inactive':
        db.get(ArkUser,actor).is_active=False
    elif change=='permission':
        roles=select(ArkUserRole.role_id).where(ArkUserRole.user_id==actor)
        db.query(ArkRolePermission).filter(ArkRolePermission.role_id.in_(roles)).delete(synchronize_session=False)
    else:
        db.get(Invoice,row.invoice_id).sales_user_id=None
    db.commit()
    sync_service.deliver(db,identity)
    assert posts==[]
    assert db.scalar(select(SendingClaim.id).where(SendingClaim.operation=='receipt_push')) is None
    assert db.get(Receipt,identity).xiaoman_receipt_id is None


def test_revocation_during_provider_preparation_is_checked_with_original_claim(db, delivery, monkeypatch):
    identity, actor, posts = delivery
    original_types=remote.receipt_types
    def types(db):
        result=original_types(db)
        db.get(ArkUser,actor).is_active=False
        db.commit()
        return result
    monkeypatch.setattr(remote,'receipt_types',types)
    sync_service.deliver(db,identity)
    assert posts==[]
    assert db.scalar(select(SendingClaim.id).where(SendingClaim.operation=='receipt_push')) is None


def test_late_original_success_survives_sender_revocation_and_never_reposts(db, delivery, monkeypatch):
    identity, actor, posts=delivery
    original=httpx.post
    def after_provider(*args,**kwargs):
        result=original(*args,**kwargs)
        db.get(ArkUser,actor).is_active=False
        db.commit()
        return result
    monkeypatch.setattr(httpx,'post',after_provider)
    sync_service.deliver(db,identity)
    assert len(posts)==1
    assert db.get(Receipt,identity).xiaoman_receipt_id=='701'
    assert db.scalar(select(ReceiptAttempt.remote_id).where(ReceiptAttempt.receipt_id==identity))=='701'
    claim=db.scalar(select(SendingClaim).where(SendingClaim.operation=='receipt_push'))
    assert claim.state=='succeeded' and claim.external_id=='701'
    sync_service.deliver(db,identity)
    assert len(posts)==1


@pytest.mark.parametrize('state', ['uncertain', 'syncing', 'synced'])
def test_non_pending_receipt_never_reacquires_new_send_authority(db, delivery, state):
    identity, actor, posts=delivery
    row=db.get(Receipt,identity)
    row.sync_status=state
    db.get(ArkUser,actor).is_active=False
    db.commit()
    sync_service.deliver(db,identity)
    assert posts==[] and db.get(Receipt,identity).sync_status==state
    assert db.scalar(select(SendingClaim.id).where(SendingClaim.operation=='receipt_push')) is None
