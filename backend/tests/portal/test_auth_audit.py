import json

from sqlalchemy import select

from test_auth_service import auth_context, send_code, verify
from app.portal import auth_service as auth
from app.portal.models import AuditEvent, PortalSession
from app.portal.schemas import VerifyInput


def test_verify_outcomes_audited_without_credentials(auth_context):
    ctx = auth_context
    challenge, code = send_code(ctx)
    wrong = "000001" if code != "000001" else "000002"
    assert verify(ctx, challenge, wrong) is None
    principal, session, token = verify(ctx, challenge, code)
    rows = ctx.db.scalars(select(AuditEvent).order_by(AuditEvent.id)).all()
    assert [row.action for row in rows] == ["auth.verify_failed", "auth.verified"]
    assert rows[0].actor_id is None and rows[0].access_id is None
    assert rows[0].object_public_id == ctx.preauth.public_id
    assert rows[1].actor_id == ctx.account.id and rows[1].access_id == ctx.access.id
    assert rows[1].object_public_id == session.public_id
    assert all(row.trace_id == ctx.preauth.public_id for row in rows)
    serialized = json.dumps([{column.name: str(getattr(row, column.name)) for column in AuditEvent.__table__.columns}
                             for row in rows])
    for secret in (code, wrong, token, ctx.token, ctx.csrf, ctx.account.email_normalized, "127.0.0.1"):
        assert secret not in serialized


def test_login_audit_and_session_rollback_together(auth_context):
    ctx = auth_context
    challenge, code = send_code(ctx)
    preauth = auth.require_preauth(ctx.db, ctx.token, ctx.csrf)
    assert auth.verify(ctx.db, preauth, VerifyInput(challenge_id=challenge.public_id, code=code), "127.0.0.1")
    ctx.db.flush()
    ctx.db.rollback()
    assert ctx.db.scalar(select(AuditEvent)) is None
    assert ctx.db.scalar(select(PortalSession)) is None
    assert ctx.preauth.consumed_at is None and challenge.consumed_at is None


def test_logout_audit_and_revocation_share_transaction(auth_context):
    ctx = auth_context
    challenge, code = send_code(ctx)
    principal, session, token = verify(ctx, challenge, code)
    auth.logout(ctx.db, principal, session)
    ctx.db.flush()
    ctx.db.rollback()
    assert session.revoked_at is None
    assert ctx.db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.logout")) is None
    principal, session = auth.authenticate(ctx.db, token)
    auth.logout(ctx.db, principal, session)
    ctx.db.commit()
    assert session.revoked_at is not None
    row = ctx.db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.logout"))
    assert row.object_public_id == session.public_id
