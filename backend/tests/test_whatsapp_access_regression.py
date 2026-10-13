import pytest

from app.whatsapp import service
from app.whatsapp.models import WhatsAppAccount
from tests.test_customer_workflow import _user, _grant_permission


def test_admin_cannot_read_other_account_bodies(db):
    owner = _user(db, 9101)
    admin = _user(db, 9102)
    _grant_permission(db, admin.id, 'whatsapp:read')
    _grant_permission(db, admin.id, 'whatsapp:admin')
    account = WhatsAppAccount(account_uid='wa_privacy', ark_user_id=owner.id, status='active')
    db.add(account)
    db.flush()
    with pytest.raises(PermissionError):
        service.list_messages(db, account.account_uid, {'sub': str(admin.id), 'permissions': ['whatsapp:admin'], 'roles': ['super_admin']}, 1, 20)


def test_disabled_owner_cannot_read_with_valid_jwt(db):
    owner = _user(db, 9103)
    _grant_permission(db, owner.id, 'whatsapp:read')
    owner.is_active = False
    account = WhatsAppAccount(account_uid='wa_disabled', ark_user_id=owner.id, status='active')
    db.add(account)
    db.flush()
    with pytest.raises(PermissionError):
        service.list_messages(db, account.account_uid, {'sub': str(owner.id), 'permissions': ['whatsapp:read'], 'roles': []}, 1, 20)
