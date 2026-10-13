"""Managed passwords, scoped authorization and lock-free password verification.

Caller commits rate debits before bcrypt, then rechecks all current authority.
Passwords never enter receipts, audit payloads, mail or response objects.
"""
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select

from app.auth.utils import hash_password, verify_password
from app.core.time import beijing_now
from app.portal import admin_service as admin, auth_service as auth
from app.portal.access_policy import customer_principal
from app.portal.domain import content_hash, normalize_email, require_version
from app.portal.errors import PortalError, reject
from app.portal.models import Account, AuditEvent, CommandReceipt, Membership, PortalSession
from app.portal.security import keyed_digest, new_token, token_digest

_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


@dataclass(frozen=True)
class LoginAttempt:
    account_id: int | None
    membership_id: int | None
    auth_version: int | None
    password_hash: str = field(repr=False)


def prepare_login(db, token, csrf, body, client_ip):
    preauth = auth.require_preauth(db, token, csrf)
    email = normalize_email(body.email)
    auth.debit(db, 'password-ip:' + client_ip, 100, 3600)
    auth.debit(db, 'password-email:' + email, 10, 900)
    account = db.scalar(select(Account).where(Account.email_normalized == email)
        .execution_options(populate_existing=True))
    member = db.scalar(select(Membership).where(Membership.account_id == account.id,
        Membership.site_id == preauth.site_id)) if account else None
    # Missing, disabled and unconfigured accounts all perform one bcrypt check.
    valid = account and member and account.status == 'active' and member.status == 'active' and account.password_hash
    return LoginAttempt(account.id if valid else None, member.id if valid else None,
        account.auth_version if valid else None, account.password_hash if valid else _DUMMY_HASH)


def check_password(attempt, body):
    return verify_password(body.password.get_secret_value(), attempt.password_hash)


def complete_login(db, token, csrf, attempt, matched):
    preauth = auth.require_preauth(db, token, csrf)
    principal = None
    if matched and attempt.account_id is not None:
        try:
            candidate = customer_principal(db, attempt.account_id, attempt.membership_id)
            if candidate.site.id == preauth.site_id and candidate.account.auth_version == attempt.auth_version and (
                    hmac.compare_digest(candidate.account.password_hash or '', attempt.password_hash)):
                principal = candidate
        except PortalError as error:
            if error.status >= 500:
                raise
    if principal is None:
        db.add(AuditEvent(actor_type='system', object_type='preauth', object_public_id=preauth.public_id,
            action='auth.password_failed', reason='', safe_diff_json={}, trace_id=preauth.public_id))
        return None
    settings = auth.get_settings()
    now = beijing_now()
    preauth.consumed_at = now
    token = new_token()
    session = PortalSession(account_id=principal.account.id, membership_id=principal.membership.id,
        account_version=principal.account.auth_version, membership_version=principal.membership.version,
        access_version=principal.access.auth_version, token_hash=token_digest(token),
        csrf_nonce=secrets.token_hex(32), csrf_key_version=settings.PORTAL_CSRF_KEY_VERSION,
        expires_at=now + timedelta(hours=settings.PORTAL_SESSION_HOURS),
        idle_expires_at=now + timedelta(minutes=settings.PORTAL_SESSION_IDLE_MINUTES))
    db.add(session)
    db.flush()
    db.add(AuditEvent(actor_type='customer', actor_id=principal.account.id, access_id=principal.access.id,
        object_type='session', object_public_id=session.public_id, action='auth.password_login',
        reason='', safe_diff_json={}, trace_id=preauth.public_id))
    return principal, session, token


def create_account(db, actor_id, public_id, command_key, body, password_hash):
    actor = admin.begin(db, actor_id)
    access = admin.scoped_access(db, public_id, actor)
    if access.status != 'enabled':
        reject('ACCESS_NOT_ENABLED', '请先启用客户门户授权。')
    admin.validate_binding(db, access)
    email = normalize_email(body.email)
    payload_hash = content_hash({'email': email, 'contact_name': body.contact_name.strip(),
        'password_digest': keyed_digest(admin.get_settings().PORTAL_AUTH_SECRET,
            'managed-account', body.password.get_secret_value())})
    receipt = db.scalar(select(CommandReceipt).where(CommandReceipt.action == 'account.create',
        CommandReceipt.object_public_id == access.public_id, CommandReceipt.command_key == str(command_key)))
    if receipt:
        if receipt.payload_hash != payload_hash:
            reject('IDEMPOTENCY_CONFLICT', '同一操作标识不能用于不同账号内容。')
        return {**receipt.result_reference_json, 'replayed': True}
    account = db.scalar(select(Account).where(Account.email_normalized == email))
    if account is not None:
        reject('ACCOUNT_ALREADY_EXISTS', '该邮箱已有采购账号，请在现有账号上设置密码或恢复访问。')
    account = Account(email_normalized=email, email_display=email, contact_name=body.contact_name.strip(),
        password_hash=password_hash, status='active')
    db.add(account)
    db.flush()
    member = Membership(account_id=account.id, site_id=access.site_id, access_id=access.id, status='active')
    db.add(member)
    db.flush()
    result = {'id': account.public_id, 'status': account.status, 'row_version': account.row_version}
    db.add(CommandReceipt(action='account.create', object_public_id=access.public_id, command_key=str(command_key),
        payload_hash=payload_hash, result_reference_json=result, first_actor_type='employee',
        first_actor_id=actor['id'], completed_at=beijing_now()))
    admin.audit(db, actor, access, account, 'account_created', changes={'status': account.status})
    db.flush()
    return {**result, 'replayed': False}


def password_target(db, actor_id, public_id, expected):
    """Short preflight and final check share the same live scope boundary."""
    actor = admin.begin(db, actor_id)
    account = db.scalar(select(Account).where(Account.public_id == str(public_id)).execution_options(populate_existing=True))
    if account is None:
        reject('RESOURCE_NOT_FOUND', '账号不存在或不在当前授权范围内。', 404)
    from app.portal.models import CustomerAccess
    bindings = db.scalars(select(CustomerAccess).join(Membership, Membership.access_id == CustomerAccess.id)
        .where(Membership.account_id == account.id)).all()
    if not bindings:
        reject('RESOURCE_NOT_FOUND', '账号不存在或不在当前授权范围内。', 404)
    for access in bindings:
        admin.scoped_access(db, access.public_id, actor)
    require_version(account.row_version, expected)
    return actor, account, bindings


def preflight_create(db, actor_id, public_id):
    actor = admin.begin(db, actor_id)
    access = admin.scoped_access(db, public_id, actor)
    if access.status != 'enabled':
        reject('ACCESS_NOT_ENABLED', '请先启用客户门户授权。')
    admin.validate_binding(db, access)


def reset_password(db, actor_id, public_id, expected, body, password_hash):
    actor, account, bindings = password_target(db, actor_id, public_id, expected)
    before = account.row_version
    account.password_hash = password_hash
    account.auth_version += 1
    account.row_version += 1
    admin.revoke_sessions(db, account_id=account.id)
    admin.audit(db, actor, bindings[0], account, 'account_password_reset', before=before, reason=body.reason)
    db.flush()
    return {'id': account.public_id, 'status': account.status, 'row_version': account.row_version}
