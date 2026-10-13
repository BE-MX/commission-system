"""Managed passwords use isolated tables; no mail or real customer writes."""
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context
from app.auth.utils import hash_password, verify_password
from app.portal import admin_service as admin, auth_service as auth, password_service as passwords
from app.portal.configuration import validate_configuration
from app.portal.errors import PortalError
from app.portal.models import Account, AuditEvent, CommandReceipt, Membership, OutboxEvent, PortalSession
from app.portal.schemas import AccountCreate, AccountPasswordUpdate, AccountUpdate, PasswordLogin

PASSWORD = '  Test-buyer-2026  '


def login(ctx, email='buyer@example.com', password=PASSWORD, before_complete=None):
    body = PasswordLogin(email=email, password=password)
    attempt = passwords.prepare_login(ctx.db, ctx.token, ctx.csrf, body, '127.0.0.1')
    ctx.db.commit()
    assert not ctx.db.in_transaction()
    matched = passwords.check_password(attempt, body)
    if before_complete:
        before_complete()
    result = passwords.complete_login(ctx.db, ctx.token, ctx.csrf, attempt, matched)
    ctx.db.commit()
    return result


def test_password_login_keeps_whitespace_and_creates_no_mail(auth_context):
    ctx = auth_context
    ctx.account.password_hash = hash_password(PASSWORD)
    ctx.db.commit()
    assert login(ctx, password=PASSWORD.strip()) is None
    principal, session, token = login(ctx)
    assert auth.authenticate(ctx.db, token)[0].account.id == principal.account.id
    assert session.token_hash != token and ctx.preauth.consumed_at
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    audit = str([e.safe_diff_json for e in ctx.db.scalars(select(AuditEvent))])
    assert PASSWORD not in audit and PASSWORD not in repr(PasswordLogin(email='buyer@example.com', password=PASSWORD))


@pytest.mark.parametrize('state', ['missing', 'disabled', 'unconfigured', 'member_disabled'])
def test_unavailable_accounts_use_dummy_and_uniform_failure(auth_context, state):
    ctx = auth_context
    ctx.account.password_hash = hash_password(PASSWORD)
    if state == 'disabled': ctx.account.status = 'disabled'
    if state == 'unconfigured': ctx.account.password_hash = None
    if state == 'member_disabled': ctx.member.status = 'disabled'
    ctx.db.commit()
    assert login(ctx, email='unknown@example.com' if state == 'missing' else 'buyer@example.com') is None
    assert ctx.db.scalar(select(func.count()).select_from(PortalSession)) == 0


@pytest.mark.parametrize('change', ['password', 'account_version', 'access', 'membership'])
def test_revocation_during_bcrypt_cannot_issue_session(auth_context, change):
    ctx = auth_context
    ctx.account.password_hash = hash_password(PASSWORD)
    ctx.db.commit()
    def revoke():
        if change == 'password': ctx.account.password_hash = hash_password('changed-password')
        if change == 'account_version': ctx.account.auth_version += 1
        if change == 'access': ctx.access.status = 'suspended'
        if change == 'membership': ctx.member.status = 'disabled'
        ctx.db.commit()
    assert login(ctx, before_complete=revoke) is None
    assert ctx.db.scalar(select(func.count()).select_from(PortalSession)) == 0


def test_attempt_debits_survive_failed_password(auth_context):
    ctx = auth_context
    for _ in range(10): assert login(ctx) is None
    with pytest.raises(PortalError) as error: login(ctx)
    assert error.value.status == 429


def test_create_is_scoped_replayable_and_has_no_secret_receipt(managed):
    ctx = managed
    body = AccountCreate(email='new@example.com', contact_name='New Buyer', password=PASSWORD)
    hashed, key = hash_password(PASSWORD), uuid4()
    first = passwords.create_account(ctx.db, 1, ctx.access.public_id, key, body, hashed)
    ctx.db.commit()
    second = passwords.create_account(ctx.db, 1, ctx.access.public_id, key, body, hash_password(PASSWORD))
    ctx.db.commit()
    assert first['id'] == second['id'] and second['replayed']
    row = ctx.db.scalar(select(Account).where(Account.public_id == first['id']))
    assert verify_password(PASSWORD, row.password_hash)
    receipt = ctx.db.scalar(select(CommandReceipt))
    assert PASSWORD not in str(receipt.result_reference_json) and hashed not in str(receipt.result_reference_json)
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    with pytest.raises(PortalError) as error:
        passwords.create_account(ctx.db, 2, ctx.access.public_id, key, body, hashed)
    assert error.value.status == 404
    ctx.db.rollback()
    changed = body.model_copy(update={'contact_name': 'Different Buyer'})
    with pytest.raises(PortalError) as error:
        passwords.create_account(ctx.db, 1, ctx.access.public_id, key, changed, hashed)
    assert error.value.code == 'IDEMPOTENCY_CONFLICT'


def test_explicit_password_and_activation_recovers_historical_invited_account(managed):
    ctx = managed
    ctx.account.status = ctx.member.status = 'invited'
    ctx.db.commit()
    version = ctx.member.version
    passwords.reset_password(ctx.db, 1, ctx.account.public_id, ctx.account.row_version,
        AccountPasswordUpdate(password=PASSWORD, reason='employee approved'), hash_password(PASSWORD))
    ctx.db.commit()
    assert ctx.account.status == ctx.member.status == 'invited'
    assert login(ctx) is None
    admin.update_account(ctx.db, 1, ctx.account.public_id, ctx.account.row_version,
        AccountUpdate(status='active', reason='employee approved'))
    ctx.db.commit()
    assert ctx.member.status == 'active' and ctx.member.version == version + 1
    assert login(ctx) is not None


def test_password_reset_revokes_sessions_and_denies_other_employee(managed):
    ctx = managed
    ctx.account.password_hash = hash_password(PASSWORD)
    ctx.db.commit()
    _, session, opaque = login(ctx)
    body = AccountPasswordUpdate(password='new-password-2026', reason='reset requested')
    with pytest.raises(PortalError) as error:
        passwords.password_target(ctx.db, 2, ctx.account.public_id, ctx.account.row_version)
    assert error.value.status == 404
    ctx.db.rollback()
    passwords.reset_password(ctx.db, 1, ctx.account.public_id, ctx.account.row_version, body,
        hash_password(body.password.get_secret_value()))
    ctx.db.commit()
    assert session.revoked_at is not None
    with pytest.raises(PortalError): auth.authenticate(ctx.db, opaque)


@pytest.mark.parametrize('password', ['short', 'x' * 65, '密' * 25, 12345678])
def test_password_limits_prevent_truncation(password):
    with pytest.raises(ValidationError): PasswordLogin(email='buyer@example.com', password=password)


def test_password_portal_needs_no_mail_keys():
    from test_contracts import config
    validate_configuration(config(PORTAL_MAIL_KEYS={}))
