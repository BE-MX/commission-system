from datetime import timedelta
from uuid import uuid4
import smtplib

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from test_auth_service import auth_context, send_code
from test_admin_service import managed, portal_metadata, invitation_body
from app.core.time import beijing_now
from app.portal import mail_worker as worker, admin_service as admin
from app.portal.models import OutboxEvent


@pytest.fixture
def mail_context(managed, monkeypatch):
    ctx = managed
    ctx.settings.PORTAL_MAIL_ENABLED = True
    monkeypatch.setattr(worker, "get_settings", lambda: ctx.settings)
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must never contact SMTP")
    monkeypatch.setattr(worker.smtplib, "SMTP_SSL", forbidden)
    ctx.factory = sessionmaker(bind=ctx.db.get_bind())
    return ctx


def queued(ctx):
    ctx.db.expire_all()
    return ctx.db.scalar(select(OutboxEvent))


def test_code_delivery_clears_secret_and_is_not_repeated(mail_context):
    ctx = mail_context
    _, code = send_code(ctx)
    ctx.db.commit()
    delivered = []
    def send(mail):
        assert not ctx.db.in_transaction()
        assert code in mail.body and mail.recipient == "buyer@example.com"
        assert code not in repr(mail)
        delivered.append(mail)
        return True
    assert worker.run_once(ctx.factory, send) == "sent"
    assert worker.run_once(ctx.factory, send) == "idle"
    row = queued(ctx)
    assert len(delivered) == 1 and row.secret_envelope is None
    assert row.lease_token is None and row.attempt_count == 1


def test_invitation_delivery_uses_fragment(mail_context):
    ctx = mail_context
    admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    messages = []
    assert worker.run_once(ctx.factory, lambda mail: messages.append(mail) or True) == "sent"
    assert messages[0].recipient == "new@example.com"
    assert "https://orders.example.com/activate#token=" in messages[0].body


@pytest.mark.parametrize("change", ["account", "member", "access", "challenge", "preauth"])
def test_revocation_before_delivery_cancels_without_smtp(mail_context, change):
    ctx = mail_context
    challenge, _ = send_code(ctx)
    if change == "account":
        ctx.account.auth_version += 1
    elif change == "member":
        ctx.member.version += 1
    elif change == "access":
        ctx.access.status = "suspended"
    elif change == "challenge":
        challenge.revoked_at = beijing_now()
    else:
        ctx.preauth.consumed_at = beijing_now()
    ctx.db.commit()
    assert worker.run_once(ctx.factory) == "cancelled"
    assert queued(ctx).secret_envelope is None


def test_expiry_cleanup_runs_when_mail_disabled(mail_context):
    ctx = mail_context
    send_code(ctx)
    row = queued(ctx)
    row.secret_expires_at = beijing_now() - timedelta(seconds=1)
    ctx.db.commit()
    ctx.settings.PORTAL_MAIL_ENABLED = False
    assert worker.run_once(ctx.factory) == "disabled"
    row = queued(ctx)
    assert row.status == "expired" and row.secret_envelope is None


def test_retry_backoff_hides_transport_details_and_stops(mail_context):
    ctx = mail_context
    send_code(ctx)
    ctx.db.commit()
    def fail(mail):
        raise smtplib.SMTPException("secret-password buyer@example.com")
    assert worker.run_once(ctx.factory, fail) == "pending"
    row = queued(ctx)
    assert row.last_error_code == "MAIL_TRANSPORT_FAILED"
    assert row.next_attempt_at > beijing_now() + timedelta(seconds=50)
    assert row.secret_envelope is not None
    row.attempt_count = 7
    row.next_attempt_at = beijing_now() - timedelta(seconds=1)
    ctx.db.commit()
    assert worker.run_once(ctx.factory, fail) == "dead"
    assert queued(ctx).secret_envelope is None


def test_expired_lease_reclaims_and_old_worker_cannot_finish(mail_context):
    ctx = mail_context
    send_code(ctx)
    first = worker.claim(ctx.db)
    ctx.db.commit()
    assert worker.claim(ctx.db) is None
    row = queued(ctx)
    row.lease_until = beijing_now() - timedelta(seconds=1)
    ctx.db.commit()
    second = worker.claim(ctx.db)
    ctx.db.commit()
    assert first[0] == second[0] and first[1] != second[1]
    assert worker.finish(ctx.db, *first, outcome="sent") == "lease_lost"
    assert worker.finish(ctx.db, *second, outcome="sent") == "sent"
    ctx.db.commit()


def test_disabled_feature_never_opens_database(mail_context):
    mail_context.settings.PORTAL_ENABLED = False
    def no_database():
        raise AssertionError("Disabled feature touched database")
    assert worker.run_once(no_database) == "disabled"


@pytest.mark.parametrize("expired,refused", [(False, False), (True, False), (False, True)])
def test_smtp_tls_recipient_expiry_and_refusal(mail_context, monkeypatch, expired, refused):
    ctx = mail_context
    ctx.settings.PORTAL_MAIL_SENDER = "portal@example.com"
    ctx.settings.PORTAL_SMTP_HOST = "smtp.example.com"
    ctx.settings.PORTAL_SMTP_PORT = 465
    ctx.settings.PORTAL_SMTP_USERNAME = "portal"
    ctx.settings.PORTAL_SMTP_PASSWORD = "dummy-test-password"
    calls = []
    class FakeSMTP:
        def __init__(self, host, port, *, timeout, context):
            assert (host, port, timeout) == ("smtp.example.com", 465, 15)
            assert context.check_hostname
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def login(self, username, password):
            assert (username, password) == ("portal", "dummy-test-password")
        def send_message(self, message):
            calls.append(message)
            return {"buyer@example.com": (550, b"refused")} if refused else {}
    monkeypatch.setattr(worker.smtplib, "SMTP_SSL", FakeSMTP)
    mail = worker.Mail("buyer@example.com", "Verification", "123456", "<test@example.com>",
        beijing_now() + timedelta(seconds=-1 if expired else 60))
    if refused:
        with pytest.raises(smtplib.SMTPException):
            worker.smtp_sender(mail)
    else:
        assert worker.smtp_sender(mail) is (not expired)
    assert len(calls) == (0 if expired else 1)
    if calls:
        assert calls[0]["To"] == "buyer@example.com"
        assert calls[0]["From"] == "portal@example.com"
        assert calls[0]["Message-ID"] == "<test@example.com>"
