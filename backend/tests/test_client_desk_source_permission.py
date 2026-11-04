"""Source-purpose permissions must preserve WhatsApp's body boundaries."""
import pytest

from app.whatsapp.access import require_body
from app.whatsapp.models import WhatsAppAccount
from tests.test_customer_workflow import _user, _grant_permission


def test_private_desk_does_not_borrow_customer_permission(db):
    user = _user(db, 98101)
    _grant_permission(db, user.id, 'customer:read')
    account = WhatsAppAccount(account_uid='desk_scope', ark_user_id=user.id,
        status='active', consent_state='active', crm_shared=True)
    db.add(account)
    db.flush()
    with pytest.raises(PermissionError):
        require_body(db, account, user.id, crm=True, purpose='client_desk')
    _grant_permission(db, user.id, 'client_desk:read')
    assert require_body(db, account, user.id, crm=True, purpose='client_desk')['sub'] == str(user.id)
    account.crm_shared = False
    with pytest.raises(PermissionError):
        require_body(db, account, user.id, crm=True, purpose='client_desk')


def test_private_desk_permission_does_not_grant_other_account_bodies(db):
    owner, reader = _user(db, 98102), _user(db, 98103)
    _grant_permission(db, reader.id, 'client_desk:read')
    account = WhatsAppAccount(account_uid='desk_other', ark_user_id=owner.id,
        status='active', consent_state='active', crm_shared=True)
    db.add(account)
    db.flush()
    with pytest.raises(PermissionError):
        require_body(db, account, reader.id, crm=True, purpose='client_desk')


def test_private_desk_body_purpose_cannot_disable_crm_gate(db):
    user = _user(db, 98104)
    _grant_permission(db, user.id, 'client_desk:read')
    account = WhatsAppAccount(account_uid='desk_no_crm', ark_user_id=user.id,
        status='active', consent_state='active', crm_shared=False)
    db.add(account)
    db.flush()
    with pytest.raises(PermissionError):
        require_body(db, account, user.id, purpose='client_desk')
