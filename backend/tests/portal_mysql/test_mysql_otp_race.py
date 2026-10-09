"""OTP consumption and failed-attempt accounting across real MySQL transactions."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.portal import auth_service as auth
from app.portal.errors import PortalError
from app.portal.models import Account, AuditEvent, AuthChallenge, OutboxEvent, PortalSession
from app.portal.schemas import ChallengeInput, VerifyInput
from app.portal.security import open_secret
from test_mysql_services import compete


def issue(ctx, monkeypatch):
    # Respect the resend window after trade's initial login; no rate-limit bypass.
    now = beijing_now() + timedelta(seconds=61)
    monkeypatch.setattr(auth, 'beijing_now', lambda: now)
    with Session(ctx.engine) as db:
        email = db.get(Account, ctx.account_id).email_normalized
        preauth, token, csrf = auth.bootstrap(db, '127.0.0.1')
        db.commit()
        challenge = auth.challenge(db, auth.require_preauth(db, token, csrf),
            ChallengeInput(email=email, purpose='login'), '127.0.0.1')
        db.commit()
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == challenge.public_id))
        code = open_secret(auth.get_settings().PORTAL_MAIL_KEYS[event.secret_key_version],
            event.secret_envelope, event_key=event.event_key, purpose='login', object_id=challenge.public_id)
        baseline = session_count(db, ctx)
        return SimpleNamespace(token=token, csrf=csrf, public_id=challenge.public_id,
            identifier=challenge.id, preauth_public_id=preauth.public_id, code=code, baseline=baseline)


def session_count(db, ctx):
    return db.scalar(select(func.count()).select_from(PortalSession).where(PortalSession.account_id == ctx.account_id))


def verify(db, attempt, code):
    result = auth.verify(db, auth.require_preauth(db, attempt.token, attempt.csrf),
        VerifyInput(challenge_id=attempt.public_id, code=code), '127.0.0.1')
    # Like the HTTP route, None is committed so failed debits are not rolled back.
    return {'accepted': result is not None}


@pytest.mark.parametrize('commit_first', [True, False])
def test_same_otp_has_one_committed_session_and_rollback_is_retryable(trade, monkeypatch, commit_first):
    attempt = issue(trade, monkeypatch)
    action = lambda db: verify(db, attempt, attempt.code)
    first, second = compete(trade, action, action,
        finalize=lambda db: db.commit() if commit_first else db.rollback())
    assert first == {'accepted': True}
    assert second == ({'error': 'AUTH_FAILED', 'status': 401} if commit_first else {'accepted': True})
    with Session(trade.engine) as db:
        challenge = db.get(AuthChallenge, attempt.identifier)
        assert challenge.consumed_at is not None and challenge.attempts == 1
        assert session_count(db, trade) == attempt.baseline + 1
        audits = db.scalars(select(AuditEvent).where(AuditEvent.trace_id == attempt.preauth_public_id,
            AuditEvent.action == 'auth.verified')).all()
        assert len(audits) == 1
        with pytest.raises(PortalError) as caught:
            action(db)
        assert caught.value.status == 401
        db.rollback()


def test_concurrent_wrong_codes_persist_each_attempt_and_exhaustion(trade, monkeypatch):
    attempt = issue(trade, monkeypatch)
    wrong = '000001' if attempt.code != '000001' else '000002'
    action = lambda db: verify(db, attempt, wrong)
    first, second = compete(trade, action, action)
    assert first == second == {'accepted': False}
    with Session(trade.engine) as db:
        assert db.get(AuthChallenge, attempt.identifier).attempts == 2
        failures = db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.trace_id == attempt.preauth_public_id, AuditEvent.action == 'auth.verify_failed'))
        assert failures == 2
        assert session_count(db, trade) == attempt.baseline
        db.rollback()
        for expected in range(3, 6):
            assert action(db) == {'accepted': False}
            db.commit()
            assert db.get(AuthChallenge, attempt.identifier).attempts == expected
            db.rollback()
        assert verify(db, attempt, attempt.code) == {'accepted': False}
        db.commit()
        assert db.get(AuthChallenge, attempt.identifier).attempts == 5
        assert session_count(db, trade) == attempt.baseline


def test_expired_otp_never_creates_session_under_competition(trade, monkeypatch):
    attempt = issue(trade, monkeypatch)
    with Session(trade.engine) as db:
        expires = db.get(AuthChallenge, attempt.identifier).expires_at
    monkeypatch.setattr(auth, 'beijing_now', lambda: expires + timedelta(seconds=1))
    action = lambda db: verify(db, attempt, attempt.code)
    first, second = compete(trade, action, action)
    assert first == second == {'accepted': False}
    with Session(trade.engine) as db:
        challenge = db.get(AuthChallenge, attempt.identifier)
        assert challenge.consumed_at is None and challenge.attempts == 0
        assert session_count(db, trade) == attempt.baseline
