"""Email verification and revocable sessions. Caller owns commit/rollback.

Failed verification returns None: its attempt debit MUST commit before HTTP 401.
No email or external I/O occurs in these transactions.
"""

import hmac
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.time import beijing_now
from app.portal.access_policy import customer_principal
from app.portal.authority import lock_authority
from app.portal.domain import normalize_email
from app.portal.errors import PortalError, reject
from app.portal.models import (Account, AuditEvent, AuthChallenge, Invitation, Membership,
    OutboxEvent, PortalSession, PreauthSession, RateBucket, Site)
from app.portal.security import csrf_token, keyed_digest, new_token, seal_secret, token_digest, verify_csrf


def require_enabled():
    if not get_settings().PORTAL_ENABLED:
        reject("SERVICE_UNAVAILABLE", "The customer portal is not available yet.", 503)
    return get_settings()


def enabled_site(db):
    settings = require_enabled()
    site = db.scalar(select(Site).where(Site.code == settings.PORTAL_SITE_CODE,
                      Site.status == "enabled").execution_options(populate_existing=True))
    if site is None or site.allowed_origin != settings.PORTAL_ORIGIN:
        reject("SERVICE_UNAVAILABLE", "The customer portal is not available yet.", 503)
    return site


def _csrf(row):
    return csrf_token(get_settings().PORTAL_CSRF_KEYS.get(row.csrf_key_version, ""), row.public_id, row.csrf_nonce)


def debit(db, key, limit, seconds):
    """All callers hold the shared authority row: inserts and increments serialize."""
    now = beijing_now()
    window = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window += timedelta(seconds=int((now - window).total_seconds()) // seconds * seconds)
    digest = keyed_digest(get_settings().PORTAL_OTP_SECRET, "rate", key)
    row = db.get(RateBucket, (digest, window), populate_existing=True)
    if row is None:
        row = RateBucket(scope_key_hash=digest, window_start=window, count=0,
                         expires_at=window + timedelta(seconds=seconds))
        db.add(row)
    if row.count >= limit:
        reject("RATE_LIMITED", "Please wait before trying again.", 429)
    row.count += 1
    db.flush()


def bootstrap(db, client_ip):
    require_enabled()
    lock_authority(db, force=True)
    site = enabled_site(db)
    debit(db, "bootstrap:" + client_ip, 60, 3600)
    token = new_token()
    row = PreauthSession(site_id=site.id, token_hash=token_digest(token),
        csrf_nonce=secrets.token_hex(32), csrf_key_version=get_settings().PORTAL_CSRF_KEY_VERSION,
        expires_at=beijing_now() + timedelta(minutes=10))
    db.add(row)
    db.flush()
    return row, token, _csrf(row)


def require_preauth(db, token, csrf):
    require_enabled()
    lock_authority(db, force=True)
    site = enabled_site(db)
    row = db.scalar(select(PreauthSession).where(PreauthSession.token_hash == token_digest(token or ""))
                    .execution_options(populate_existing=True))
    if row is None or row.site_id != site.id or row.consumed_at is not None or row.expires_at <= beijing_now():
        reject("AUTH_FAILED", "Refresh the sign-in page and try again.", 401)
    verify_csrf(get_settings().PORTAL_CSRF_KEYS.get(row.csrf_key_version, ""), row.public_id, row.csrf_nonce, csrf)
    return row


def _valid_invitation(invitation, principal):
    return invitation is not None and invitation.account_id == principal.account.id and (
        invitation.membership_id == principal.membership.id and invitation.access_id == principal.access.id
        and invitation.account_version == principal.account.auth_version
        and invitation.membership_version == principal.membership.version
        and invitation.access_version == principal.access.auth_version
        and invitation.revoked_at is None and invitation.consumed_at is None
        and invitation.expires_at > beijing_now())


def _code_digest(public_id, code, email_key, purpose, principal):
    binding = (principal.account.id, principal.membership.id, principal.access.id,
               principal.account.auth_version, principal.membership.version,
               principal.access.auth_version) if principal else (0, 0, 0, 0, 0, 0)
    return keyed_digest(get_settings().PORTAL_OTP_SECRET, public_id, code, email_key,
                        purpose, *(str(value) for value in binding))


def challenge(db, preauth, body, client_ip):
    settings = get_settings()
    email = normalize_email(body.email)
    debit(db, "send-ip:" + client_ip, 30, 3600)
    debit(db, "send-email:" + email, 5, 3600)
    email_key = keyed_digest(settings.PORTAL_OTP_SECRET, "email", email)
    recent = db.scalar(select(AuthChallenge).where(AuthChallenge.email_key_hash == email_key)
                       .order_by(AuthChallenge.created_at.desc(), AuthChallenge.id.desc()).limit(1))
    if recent and recent.created_at > beijing_now() - timedelta(seconds=60):
        reject("RATE_LIMITED", "Please wait before requesting another code.", 429)
    account = db.scalar(select(Account).where(Account.email_normalized == email))
    member = db.scalar(select(Membership).where(Membership.account_id == account.id,
                        Membership.site_id == preauth.site_id)) if account else None
    invitation, principal = None, None
    if member:
        try:
            principal = customer_principal(db, account.id, member.id, activating=body.purpose == "activate")
        except PortalError as error:
            # Deliberately uniform challenge responses for unavailable accounts.
            if error.status >= 500:
                raise
            principal = None
    if principal and body.purpose == "activate":
        invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_digest(body.invitation_token)))
        if not _valid_invitation(invitation, principal):
            principal, invitation = None, None
    old = db.scalars(select(AuthChallenge).where(AuthChallenge.email_key_hash == email_key,
        AuthChallenge.purpose == body.purpose, AuthChallenge.consumed_at.is_(None), AuthChallenge.revoked_at.is_(None))).all()
    for record in old:
        record.revoked_at = beijing_now()
    code, public_id = f"{secrets.randbelow(1000000):06}", str(uuid4())
    row = AuthChallenge(public_id=public_id, site_id=preauth.site_id, preauth_id=preauth.id,
        account_id=account.id if principal else None, invitation_id=invitation.id if invitation else None,
        purpose=body.purpose, email_key_hash=email_key, issued_version=account.auth_version if principal else 0,
        code_hmac=_code_digest(public_id, code, email_key, body.purpose, principal),
        expires_at=beijing_now() + timedelta(minutes=settings.PORTAL_OTP_MINUTES))
    db.add(row)
    db.flush()
    if principal:
        event_key = "otp:" + public_id
        envelope = seal_secret(settings.PORTAL_MAIL_KEYS[settings.PORTAL_MAIL_KEY_VERSION], code,
                               event_key=event_key, purpose=body.purpose, object_id=public_id)
        db.add(OutboxEvent(event_key=event_key, event_type="auth_code", aggregate_public_id=public_id,
            payload_json={"challenge_id": public_id}, secret_envelope=envelope,
            secret_key_version=settings.PORTAL_MAIL_KEY_VERSION, secret_expires_at=row.expires_at,
            next_attempt_at=beijing_now()))
    return row


def verify(db, preauth, body, client_ip):
    result = _verify(db, preauth, body, client_ip)
    principal, session = (result[0], result[1]) if result else (None, None)
    db.add(AuditEvent(actor_type="customer" if result else "system",
        actor_id=principal.account.id if result else None,
        access_id=principal.access.id if result else None,
        object_type="session" if result else "preauth",
        object_public_id=session.public_id if result else preauth.public_id,
        action="auth.verified" if result else "auth.verify_failed",
        reason="", safe_diff_json={}, trace_id=preauth.public_id))
    return result


def _verify(db, preauth, body, client_ip):
    settings = get_settings()
    debit(db, "verify-ip:" + client_ip, 100, 3600)
    row = db.scalar(select(AuthChallenge).where(AuthChallenge.public_id == str(body.challenge_id))
                    .execution_options(populate_existing=True))
    if row is None or row.preauth_id != preauth.id or row.site_id != preauth.site_id:
        return None
    if row.consumed_at or row.revoked_at or row.expires_at <= beijing_now() or row.attempts >= 5:
        return None
    row.attempts += 1
    if row.account_id is None:
        return None
    member = db.scalar(select(Membership).where(Membership.account_id == row.account_id,
                                               Membership.site_id == row.site_id))
    if member is None:
        return None
    try:
        principal = customer_principal(db, row.account_id, member.id, activating=row.purpose == "activate")
    except PortalError as error:
        if error.status >= 500:
            raise
        return None
    expected = _code_digest(row.public_id, body.code, row.email_key_hash, row.purpose, principal)
    if not hmac.compare_digest(expected, row.code_hmac) or principal.account.auth_version != row.issued_version:
        return None
    if row.purpose == "activate":
        invitation = db.get(Invitation, row.invitation_id, populate_existing=True)
        if not _valid_invitation(invitation, principal):
            return None
        invitation.consumed_at = beijing_now()
        principal.account.status = "active"
        principal.account.verified_at = beijing_now()
        principal.membership.status = "active"
    row.consumed_at = preauth.consumed_at = beijing_now()
    token = new_token()
    session = PortalSession(account_id=principal.account.id, membership_id=principal.membership.id,
        account_version=principal.account.auth_version, membership_version=principal.membership.version,
        access_version=principal.access.auth_version, token_hash=token_digest(token),
        csrf_nonce=secrets.token_hex(32), csrf_key_version=settings.PORTAL_CSRF_KEY_VERSION,
        expires_at=beijing_now() + timedelta(hours=settings.PORTAL_SESSION_HOURS),
        idle_expires_at=beijing_now() + timedelta(minutes=settings.PORTAL_SESSION_IDLE_MINUTES))
    db.add(session)
    db.flush()
    return principal, session, token


def logout(db, principal, session):
    session.revoked_at = beijing_now()
    db.add(AuditEvent(actor_type="customer", actor_id=principal.account.id,
        access_id=principal.access.id, object_type="session", object_public_id=session.public_id,
        action="auth.logout", reason="", safe_diff_json={}, trace_id=str(uuid4())))


def authenticate(db, token, *, csrf=None, write=False):
    require_enabled()
    lock_authority(db, force=True)
    site = enabled_site(db)
    session = db.scalar(select(PortalSession).where(PortalSession.token_hash == token_digest(token or ""))
                        .execution_options(populate_existing=True))
    now = beijing_now()
    if session is None or session.revoked_at or min(session.expires_at, session.idle_expires_at) <= now:
        reject("AUTH_REQUIRED", "Please sign in again.", 401)
    principal = customer_principal(db, session.account_id, session.membership_id)
    if principal.site.id != site.id or (session.account_version, session.membership_version, session.access_version) != (
        principal.account.auth_version, principal.membership.version, principal.access.auth_version):
        reject("SESSION_REVOKED", "Please sign in again.", 401)
    if write:
        verify_csrf(get_settings().PORTAL_CSRF_KEYS.get(session.csrf_key_version, ""), session.public_id, session.csrf_nonce, csrf)
    session.idle_expires_at = min(session.expires_at, now + timedelta(minutes=get_settings().PORTAL_SESSION_IDLE_MINUTES))
    return principal, session


def session_view(principal, session):
    from app.portal.contact_service import contact_view
    return {"me": {"account_public_id": principal.account.public_id,
        "contact_display_name": principal.account.contact_name,
        "company_display_name": principal.company_display_name,
        "sales_contact": contact_view(principal),
        "currency": principal.site.currency, "language": principal.site.language},
        "capabilities": {"view_catalog": True, "view_price": principal.access.can_view_price,
                         "place_order": principal.access.can_order and principal.access.can_view_price},
        "csrf_token": _csrf(session)}
