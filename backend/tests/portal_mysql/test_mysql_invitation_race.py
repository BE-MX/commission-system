"""Invitation ownership and expiration are rechecked during real MySQL activation."""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.portal import admin_service, auth_service as auth
from app.portal.models import Account, AuditEvent, CustomerAccess, Invitation, Membership, OutboxEvent, PortalSession
from app.portal.schemas import ChallengeInput, InvitationInput
from app.portal.security import open_secret
from test_mysql_services import compete
from test_mysql_otp_race import verify


def invite(ctx, db):
    email = uuid4().hex + '@example.test'
    access = db.get(CustomerAccess, ctx.access_id)
    result = admin_service.invite(db, ctx.admin, access.public_id, uuid4(),
        InvitationInput(email=email, contact_name='Invited buyer'))
    db.commit()
    row = db.scalar(select(Invitation).where(Invitation.public_id == result['invitation_id']))
    event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == row.public_id))
    token = open_secret(auth.get_settings().PORTAL_MAIL_KEYS[event.secret_key_version],
        event.secret_envelope, event_key=event.event_key, purpose='activate', object_id=row.public_id)
    return SimpleNamespace(identifier=row.id, account_id=row.account_id,
        member_id=row.membership_id, email=email, token=token)


def challenge(db, invitation, *, token=None):
    preauth, opaque, csrf = auth.bootstrap(db, '127.0.0.1')
    db.commit()
    row = auth.challenge(db, auth.require_preauth(db, opaque, csrf),
        ChallengeInput(email=invitation.email, purpose='activate',
            invitation_token=token or invitation.token), '127.0.0.1')
    db.commit()
    event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == row.public_id))
    code = None if event is None else open_secret(auth.get_settings().PORTAL_MAIL_KEYS[event.secret_key_version],
        event.secret_envelope, event_key=event.event_key, purpose='activate', object_id=row.public_id)
    return SimpleNamespace(token=opaque, csrf=csrf, public_id=row.public_id, code=code,
        preauth_public_id=preauth.public_id)


@pytest.mark.parametrize('expire_before_verify', [False, True])
def test_invitation_activation_competes_and_rechecks_expiry(trade, monkeypatch, expire_before_verify):
    with Session(trade.engine) as db:
        invited = invite(trade, db)
        attempt = challenge(db, invited)
        assert attempt.code is not None
        assert db.get(Account, invited.account_id).status == 'invited'
        if expire_before_verify:
            now = auth.beijing_now()
            db.get(Invitation, invited.identifier).expires_at = now + timedelta(seconds=1)
            db.commit()
            monkeypatch.setattr(auth, 'beijing_now', lambda: now + timedelta(seconds=2))
    action = lambda db: verify(db, attempt, attempt.code)
    first, second = compete(trade, action, action)
    if expire_before_verify:
        assert first == second == {'accepted': False}
    else:
        assert first == {'accepted': True}
        assert second == {'error': 'AUTH_FAILED', 'status': 401}
    with Session(trade.engine) as db:
        row = db.get(Invitation, invited.identifier)
        account = db.get(Account, invited.account_id)
        member = db.get(Membership, invited.member_id)
        assert (row.consumed_at is not None) is (not expire_before_verify)
        assert account.status == ('invited' if expire_before_verify else 'active')
        assert (account.verified_at is not None) is (not expire_before_verify)
        assert member.status == ('invited' if expire_before_verify else 'active')
        assert db.scalar(select(func.count()).select_from(PortalSession).where(
            PortalSession.account_id == invited.account_id)) == int(not expire_before_verify)
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.trace_id == attempt.preauth_public_id,
            AuditEvent.action == 'auth.verified')) == int(not expire_before_verify)


def test_forwarded_invitation_cannot_activate_other_invited_email(trade):
    with Session(trade.engine) as db:
        owner = invite(trade, db)
        other = invite(trade, db)
        attempt = challenge(db, other, token=owner.token)
        assert attempt.code is None
        assert verify(db, attempt, '000000') == {'accepted': False}
        db.commit()
        for invited in (owner, other):
            assert db.get(Invitation, invited.identifier).consumed_at is None
            assert db.get(Account, invited.account_id).status == 'invited'
            assert db.get(Account, invited.account_id).verified_at is None
            assert db.get(Membership, invited.member_id).status == 'invited'
            assert db.scalar(select(func.count()).select_from(PortalSession).where(
                PortalSession.account_id == invited.account_id)) == 0
