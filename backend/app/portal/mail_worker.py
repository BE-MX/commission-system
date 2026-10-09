"""Leased, at-least-once auth mail delivery. SMTP never runs inside a DB transaction."""
import hmac
import secrets
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage

from cryptography.exceptions import InvalidTag
from sqlalchemy import and_, or_, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.time import beijing_now
from app.portal.access_policy import customer_principal
from app.portal.auth_service import _code_digest, _valid_invitation, enabled_site
from app.portal.authority import lock_authority
from app.portal.domain import normalize_email
from app.portal.errors import PortalError
from app.portal.models import AuthChallenge, Invitation, Membership, OutboxEvent, PreauthSession
from app.portal.security import open_secret, token_digest


AUTH_EVENTS = {"invitation", "auth_code"}
MAX_ATTEMPTS = 8
LEASE_SECONDS = 120
RETRY_MINUTES = (1, 5, 15, 60, 120, 240, 360, 360)


@dataclass(frozen=True)
class Mail:
    recipient: str = field(repr=False)
    subject: str
    body: str = field(repr=False)
    message_id: str
    valid_until: datetime


def close_event(row, status, error=None):
    row.status = status
    row.last_error_code = error
    row.secret_envelope = None
    row.secret_key_version = None
    row.lease_token = None
    row.lease_until = None


def cleanup_expired(db):
    lock_authority(db, force=True)
    rows = db.scalars(select(OutboxEvent).where(OutboxEvent.secret_envelope.is_not(None),
        OutboxEvent.secret_expires_at <= beijing_now()).order_by(OutboxEvent.id).limit(100)).all()
    for row in rows:
        close_event(row, "expired", "SECRET_EXPIRED")
    return len(rows)


def claim(db):
    lock_authority(db, force=True)
    now = beijing_now()
    row = db.scalar(select(OutboxEvent).where(OutboxEvent.event_type.in_(AUTH_EVENTS), or_(
        and_(OutboxEvent.status == "pending", OutboxEvent.next_attempt_at <= now),
        and_(OutboxEvent.status == "sending", OutboxEvent.lease_until <= now)))
        .order_by(OutboxEvent.next_attempt_at, OutboxEvent.id).limit(1).with_for_update())
    if row is None:
        return None
    if row.attempt_count >= MAX_ATTEMPTS:
        close_event(row, "dead", "ATTEMPTS_EXHAUSTED")
        return None
    row.status = "sending"
    row.attempt_count += 1
    row.lease_token = secrets.token_hex(32)
    row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    db.flush()
    return row.public_id, row.lease_token


def leased_event(db, public_id, lease):
    lock_authority(db, force=True)
    row = db.scalar(select(OutboxEvent).where(OutboxEvent.public_id == public_id)
                    .execution_options(populate_existing=True))
    if row is None or row.status != "sending" or row.lease_token != lease or row.lease_until is None or row.lease_until <= beijing_now():
        return None
    return row


def prepare(db, public_id, lease):
    row = leased_event(db, public_id, lease)
    if row is None:
        return None
    now = beijing_now()
    if row.secret_envelope is None or row.secret_expires_at is None or row.secret_expires_at <= now:
        close_event(row, "expired", "SECRET_EXPIRED")
        return None
    settings = get_settings()
    try:
        site = enabled_site(db)
        if row.event_type == "invitation":
            invitation = db.scalar(select(Invitation).where(Invitation.public_id == row.aggregate_public_id))
            if invitation is None:
                close_event(row, "cancelled", "AUTHORIZATION_CHANGED")
                return None
            principal = customer_principal(db, invitation.account_id, invitation.membership_id, activating=True)
            if principal.site.id != site.id or not _valid_invitation(invitation, principal):
                close_event(row, "cancelled", "AUTHORIZATION_CHANGED")
                return None
            token = open_secret(settings.PORTAL_MAIL_KEYS.get(row.secret_key_version, ""), row.secret_envelope,
                event_key=row.event_key, purpose="activate", object_id=invitation.public_id)
            if not hmac.compare_digest(token_digest(token), invitation.token_hash):
                close_event(row, "cancelled", "SECRET_BINDING_INVALID")
                return None
            # Fragment keeps the invitation capability out of access logs and Referer.
            link = site.allowed_origin + "/activate#token=" + token
            text = "You have been invited to LeShine. Open this link to verify your email and activate access:\n\n" + link
            subject = "Your LeShine customer portal invitation"
            until = min(row.secret_expires_at, invitation.expires_at)
        elif row.event_type == "auth_code":
            challenge = db.scalar(select(AuthChallenge).where(AuthChallenge.public_id == row.aggregate_public_id))
            if challenge is None or challenge.account_id is None or challenge.consumed_at or challenge.revoked_at or challenge.attempts >= 5 or challenge.expires_at <= now:
                close_event(row, "cancelled", "AUTHORIZATION_CHANGED")
                return None
            member = db.scalar(select(Membership).where(Membership.account_id == challenge.account_id,
                                                        Membership.site_id == challenge.site_id))
            preauth = db.get(PreauthSession, challenge.preauth_id)
            if member is None or preauth is None or preauth.consumed_at or preauth.expires_at <= now:
                close_event(row, "cancelled", "AUTHORIZATION_CHANGED")
                return None
            principal = customer_principal(db, challenge.account_id, member.id, activating=challenge.purpose == "activate")
            if principal.site.id != site.id:
                close_event(row, "cancelled", "AUTHORIZATION_CHANGED")
                return None
            if challenge.purpose == "activate" and not _valid_invitation(db.get(Invitation, challenge.invitation_id), principal):
                close_event(row, "cancelled", "AUTHORIZATION_CHANGED")
                return None
            code = open_secret(settings.PORTAL_MAIL_KEYS.get(row.secret_key_version, ""), row.secret_envelope,
                event_key=row.event_key, purpose=challenge.purpose, object_id=challenge.public_id)
            expected = _code_digest(challenge.public_id, code, challenge.email_key_hash, challenge.purpose, principal)
            if not hmac.compare_digest(expected, challenge.code_hmac):
                close_event(row, "cancelled", "AUTHORIZATION_CHANGED")
                return None
            text = "Your LeShine verification code is: " + code + "\n\nDo not share this code. If you did not request it, ignore this email."
            subject = "Your LeShine verification code"
            until = min(row.secret_expires_at, challenge.expires_at, preauth.expires_at)
        else:
            close_event(row, "dead", "UNSUPPORTED_AUTH_EVENT")
            return None
    except PortalError as error:
        if error.status >= 500:
            raise
        close_event(row, "cancelled", "AUTHORIZATION_CHANGED")
        return None
    return Mail(principal.account.email_normalized, subject, text,
                f"<portal-{row.public_id}@leshine.invalid>", min(until, row.lease_until))


def finish(db, public_id, lease, *, outcome, error=None):
    row = leased_event(db, public_id, lease)
    if row is None:
        return "lease_lost"
    if outcome in {"sent", "cancelled"}:
        close_event(row, outcome, error)
    elif row.secret_expires_at is None or row.secret_expires_at <= beijing_now():
        close_event(row, "expired", "SECRET_EXPIRED")
    elif row.attempt_count >= MAX_ATTEMPTS:
        close_event(row, "dead", error)
    else:
        row.status = "pending"
        row.last_error_code = error
        row.next_attempt_at = beijing_now() + timedelta(minutes=RETRY_MINUTES[row.attempt_count - 1])
        row.lease_token = None
        row.lease_until = None
    return row.status


def smtp_sender(mail):
    settings = get_settings()
    sender = normalize_email(settings.PORTAL_MAIL_SENDER)
    if not settings.PORTAL_SMTP_HOST:
        raise ValueError("Portal SMTP host is not configured")
    message = EmailMessage()
    message["From"], message["To"] = sender, normalize_email(mail.recipient)
    message["Subject"], message["Message-ID"] = mail.subject, mail.message_id
    message.set_content(mail.body)
    with smtplib.SMTP_SSL(settings.PORTAL_SMTP_HOST, settings.PORTAL_SMTP_PORT,
                         timeout=15, context=ssl.create_default_context()) as smtp:
        if settings.PORTAL_SMTP_USERNAME:
            smtp.login(settings.PORTAL_SMTP_USERNAME, settings.PORTAL_SMTP_PASSWORD)
        if mail.valid_until <= beijing_now():
            return False
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPException("Portal recipient was not accepted")
    return True


def run_once(session_factory=SessionLocal, sender=None):
    settings = get_settings()
    if not settings.PORTAL_ENABLED:
        return "disabled"
    with session_factory() as db:
        cleanup_expired(db)
        leased = claim(db) if settings.PORTAL_MAIL_ENABLED else None
        db.commit()
    if not settings.PORTAL_MAIL_ENABLED:
        return "disabled"
    if leased is None:
        return "idle"
    public_id, lease = leased
    try:
        with session_factory() as db:
            mail = prepare(db, public_id, lease)
            db.commit()
        if mail is None:
            return "cancelled"
        # No Session remains open and no authority lock is held during network I/O.
        delivered = (sender or smtp_sender)(mail)
        outcome, error = ("sent", None) if delivered is True else ("cancelled", "EXPIRED_BEFORE_SEND")
    except (InvalidTag, UnicodeDecodeError, ValueError):
        outcome, error = "retry", "MAIL_CONFIGURATION_OR_SECRET_INVALID"
    except PortalError:
        outcome, error = "retry", "AUTHORITY_UNAVAILABLE"
    except (smtplib.SMTPException, OSError):
        # SMTP exceptions may include recipient, credentials or server transcripts.
        outcome, error = "retry", "MAIL_TRANSPORT_FAILED"
    with session_factory() as db:
        status = finish(db, public_id, lease, outcome=outcome, error=error)
        db.commit()
    return status
