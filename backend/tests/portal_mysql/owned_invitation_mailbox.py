"""Read only the actual invitation queued for this owned browser fixture.

No external mail delivery and no manufactured application response. Credential
values stay inside the broker response/process memory and are never reported.
"""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.time import beijing_now
from app.portal.models import Account, CustomerAccess, Invitation, Membership, OutboxEvent
from app.portal.security import open_secret, token_digest


def activated_login_allowed(db, shell, challenge):
    """Only the actually activated new onboarding member can read a login code."""
    c = shell.fixture
    if not hasattr(c, 'onboard_customer_id') or challenge is None:
        return False
    if (challenge.account_id != shell.invited_account_id or challenge.purpose != 'login'
        or challenge.invitation_id is not None):
        return False
    invitation = db.get(Invitation, shell.invited_invitation_id)
    if invitation is None or invitation.consumed_at is None or invitation.created_by != c.app.ctx.admin:
        return False
    access = db.get(CustomerAccess, invitation.access_id)
    account = db.get(Account, invitation.account_id)
    member = db.get(Membership, invitation.membership_id)
    original = db.get(CustomerAccess, c.app.ctx.access_id)
    return bool(access and account and member and original
        and access.site_id == original.site_id == invitation.site_id == member.site_id == challenge.site_id
        and access.customer_id == c.onboard_customer_id
        and access.assignment_id == c.onboard_assignment_id
        and access.external_identity_id == c.onboard_identity_id
        and access.sales_user_id == c.app.ctx.actor and access.status == 'enabled'
        and account.id == challenge.account_id == member.account_id
        and account.email_normalized == c.onboard_invited_email
        and account.status == 'active' and account.verified_at is not None
        and account.auth_version == challenge.issued_version
        and member.access_id == access.id and member.status == 'active')



def invitation_evidence(shell, identifier):
    try: public_id = str(UUID(identifier))
    except ValueError: return None
    c = shell.fixture
    with Session(c.app.ctx.engine) as db:
        original = db.get(CustomerAccess, c.app.ctx.access_id)
        if original is None: return None
        if hasattr(c, 'onboard_customer_id'):
            access = db.scalar(select(CustomerAccess).where(CustomerAccess.site_id == original.site_id,
                CustomerAccess.customer_id == c.onboard_customer_id,
                CustomerAccess.assignment_id == c.onboard_assignment_id,
                CustomerAccess.external_identity_id == c.onboard_identity_id,
                CustomerAccess.sales_user_id == c.app.ctx.actor))
            expected_email = c.onboard_invited_email
        else:
            access, expected_email = original, c.invited_email
        if access is None or access.status != 'enabled': return None
        invitation = db.scalar(select(Invitation).where(Invitation.public_id == public_id,
            Invitation.access_id == access.id, Invitation.created_by == c.app.ctx.admin))
        if invitation is None or access is None: return None
        account = db.get(Account, invitation.account_id)
        member = db.get(Membership, invitation.membership_id)
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == public_id,
            OutboxEvent.event_key == 'invitation:' + public_id, OutboxEvent.event_type == 'invitation'))
        if (account is None or member is None or event is None
            or invitation.site_id != access.site_id or member.site_id != access.site_id
            or member.account_id != account.id or member.access_id != access.id
            or account.email_normalized != expected_email or account.status != 'invited'
            or account.verified_at is not None or member.status != 'invited'
            or invitation.account_version != account.auth_version
            or invitation.membership_version != member.version
            or invitation.access_version != access.auth_version
            or invitation.consumed_at is not None or invitation.revoked_at is not None
            or invitation.expires_at <= beijing_now() or event.secret_envelope is None
            or event.secret_expires_at is None or event.secret_expires_at <= beijing_now()):
            return None
        token = open_secret(c.app.settings.PORTAL_MAIL_KEYS[event.secret_key_version],
            event.secret_envelope, event_key=event.event_key, purpose='activate', object_id=public_id)
        assert token_digest(token) == invitation.token_hash
        assert 'token' not in event.payload_json and event.payload_json == {'invitation_id': public_id}
        shell.invited_account_id = account.id
        shell.invited_invitation_id = invitation.id
        snapshot = tuple(tuple(db.execute(select(*model.__table__.columns).where(model.id == row.id)).one())
            for model, row in ((Account, account), (Membership, member), (Invitation, invitation)))
        shell.invitation_landing_snapshots.append(snapshot)
        return {'token': token, 'accountPublicId': account.public_id}
