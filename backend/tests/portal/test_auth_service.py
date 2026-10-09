"""Service transactions with real portal tables, mocked upstream binding only.

These tests do not establish MySQL concurrency or the upstream identity adapter.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, func

from app.core.time import beijing_now
from app.portal import access_policy, auth_service as auth
from app.portal.errors import PortalError
from app.portal.models import (Account, AuthorityBarrier, AuthChallenge, CustomerAccess,
    Membership, OutboxEvent, PortalSession, RateBucket, Site)
from app.portal.schemas import ChallengeInput, VerifyInput
from app.portal.security import open_secret


@pytest.fixture
def auth_context(portal_db, portal_metadata, monkeypatch):
    settings = SimpleNamespace(PORTAL_ENABLED=True, PORTAL_SITE_CODE="leshine",
        PORTAL_ORIGIN="https://orders.example.com", PORTAL_OTP_SECRET="o"*32,
        PORTAL_CSRF_KEYS={"v1": "c"*32}, PORTAL_CSRF_KEY_VERSION="v1",
        PORTAL_MAIL_KEYS={"v1": "ab"*32}, PORTAL_MAIL_KEY_VERSION="v1",
        PORTAL_OTP_MINUTES=5, PORTAL_SESSION_HOURS=12, PORTAL_SESSION_IDLE_MINUTES=30)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(access_policy, "validate_binding", lambda db, access: SimpleNamespace(display_name="Buyer Company"))
    db = portal_db
    for name in ("ark_users", "ark_customer_accounts", "ark_customer_external_identities", "ark_customer_assignments"):
        db.execute(portal_metadata.tables[name].insert(), {"id": 1})
    site = Site(code="leshine", name="LeShine", status="enabled", allowed_origin=settings.PORTAL_ORIGIN)
    account = Account(email_normalized="buyer@example.com", email_display="buyer@example.com",
                      contact_name="Buyer", status="active")
    db.add_all([site, account, AuthorityBarrier(code="authority")])
    db.flush()
    access = CustomerAccess(site_id=site.id, customer_id=1, okki_namespace="okki:test",
        okki_company_id="1", external_identity_id=1, binding_fingerprint="a"*64,
        assignment_id=1, sales_user_id=1, status="enabled", can_order=True, can_view_price=True)
    db.add(access)
    db.flush()
    member = Membership(site_id=site.id, account_id=account.id, access_id=access.id, status="active")
    db.add(member)
    db.commit()
    preauth, token, csrf = auth.bootstrap(db, "127.0.0.1")
    db.commit()
    return SimpleNamespace(db=db, settings=settings, site=site, account=account, access=access,
                           member=member, preauth=preauth, token=token, csrf=csrf)


def send_code(ctx, email="buyer@example.com"):
    preauth = auth.require_preauth(ctx.db, ctx.token, ctx.csrf)
    row = auth.challenge(ctx.db, preauth, ChallengeInput(email=email, purpose="login"), "127.0.0.1")
    ctx.db.commit()
    event = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == row.public_id))
    code = None if event is None else open_secret(ctx.settings.PORTAL_MAIL_KEYS["v1"], event.secret_envelope,
        event_key=event.event_key, purpose="login", object_id=row.public_id)
    return row, code


def verify(ctx, row, code):
    preauth = auth.require_preauth(ctx.db, ctx.token, ctx.csrf)
    result = auth.verify(ctx.db, preauth, VerifyInput(challenge_id=row.public_id, code=code), "127.0.0.1")
    ctx.db.commit()
    return result


def test_disabled_portal_never_queries_database(monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(PORTAL_ENABLED=False))
    class NoDatabase:
        def __getattr__(self, name):
            raise AssertionError("Disabled portal accessed the database")
    for operation in (lambda: auth.bootstrap(NoDatabase(), "127.0.0.1"),
                      lambda: auth.require_preauth(NoDatabase(), "bad", "bad"),
                      lambda: auth.authenticate(NoDatabase(), "bad")):
        with pytest.raises(PortalError) as error:
            operation()
        assert error.value.status == 503


def test_login_consumes_preauth_and_issues_opaque_session(auth_context):
    ctx = auth_context
    row, code = send_code(ctx)
    principal, session, token = verify(ctx, row, code)
    assert token != session.token_hash
    assert row.consumed_at and ctx.preauth.consumed_at
    assert session.account_id == ctx.account.id
    assert auth.authenticate(ctx.db, token)[0].account.id == principal.account.id
    with pytest.raises(PortalError) as error:
        auth.require_preauth(ctx.db, ctx.token, ctx.csrf)
    assert error.value.status == 401
    assert ctx.db.scalar(select(func.count()).select_from(PortalSession)) == 1


def test_wrong_codes_are_persisted_and_fifth_attempt_exhausts(auth_context):
    ctx = auth_context
    row, code = send_code(ctx)
    wrong = "000001" if code != "000001" else "000002"
    for expected in range(1, 6):
        assert verify(ctx, row, wrong) is None
        ctx.db.expire_all()
        assert ctx.db.get(AuthChallenge, row.id).attempts == expected
    assert verify(ctx, row, code) is None
    assert ctx.db.scalar(select(func.count()).select_from(PortalSession)) == 0


def test_unknown_account_receives_challenge_without_mail(auth_context):
    ctx = auth_context
    row, code = send_code(ctx, "unknown@example.com")
    assert row.public_id and row.account_id is None and code is None
    assert verify(ctx, row, "000000") is None
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent)) == 0


@pytest.mark.parametrize("change", ["account", "membership", "access", "suspend", "expire"])
def test_session_rechecks_revocations(auth_context, change):
    ctx = auth_context
    row, code = send_code(ctx)
    _, session, token = verify(ctx, row, code)
    if change == "account":
        ctx.account.auth_version += 1
    elif change == "membership":
        ctx.member.version += 1
    elif change == "access":
        ctx.access.auth_version += 1
    elif change == "suspend":
        ctx.access.status = "suspended"
    else:
        session.idle_expires_at = beijing_now() - timedelta(seconds=1)
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        auth.authenticate(ctx.db, token)
    assert error.value.status == 401


@pytest.mark.parametrize("scope", ["account", "membership", "access"])
def test_revocation_between_issue_and_verify(auth_context, scope):
    ctx = auth_context
    row, code = send_code(ctx)
    target = {"account": ctx.account, "membership": ctx.member, "access": ctx.access}[scope]
    if scope == "membership":
        target.version += 1
    else:
        target.auth_version += 1
    ctx.db.commit()
    assert verify(ctx, row, code) is None


def test_challenge_bound_to_preauth_session(auth_context):
    ctx = auth_context
    row, code = send_code(ctx)
    other, _, _ = auth.bootstrap(ctx.db, "127.0.0.2")
    result = auth.verify(ctx.db, other, VerifyInput(challenge_id=row.public_id, code=code), "127.0.0.2")
    ctx.db.commit()
    assert result is None and row.attempts == 0
    assert verify(ctx, row, code) is not None


def test_csrf_rejected_before_challenge_or_session_touch(auth_context):
    ctx = auth_context
    with pytest.raises(PortalError) as error:
        auth.require_preauth(ctx.db, ctx.token, "wrong")
    assert error.value.status == 403
    row, code = send_code(ctx)
    _, session, token = verify(ctx, row, code)
    previous = session.idle_expires_at
    with pytest.raises(PortalError) as error:
        auth.authenticate(ctx.db, token, write=True, csrf="wrong")
    assert error.value.status == 403 and session.idle_expires_at == previous


def test_email_resend_rate_survives_new_preauth(auth_context):
    ctx = auth_context
    row, _ = send_code(ctx)
    # Advance the challenge timestamp only; the shared hourly send budget remains.
    for _ in range(4):
        row.created_at = beijing_now() - timedelta(seconds=61)
        ctx.db.commit()
        ctx.preauth, ctx.token, ctx.csrf = auth.bootstrap(ctx.db, "127.0.0.1")
        ctx.db.commit()
        row, _ = send_code(ctx, "BUYER@example.com")
    row.created_at = beijing_now() - timedelta(seconds=61)
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        send_code(ctx)
    assert error.value.status == 429


def test_http_auth_boundaries_and_failed_attempt_commit(auth_context, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.portal import router as http

    ctx = auth_context
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(http, "get_settings", lambda: ctx.settings)
    app = FastAPI()
    app.include_router(http.router, prefix="/api/portal/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 30000)),
                base_url="https://orders.example.com", headers={"X-Real-IP": "203.0.113.1"}) as client:
            boot = await client.get("/api/portal/v1/auth/bootstrap")
            assert boot.status_code == 200
            assert "HttpOnly" in boot.headers["set-cookie"] and "Secure" in boot.headers["set-cookie"]
            assert "Domain=" not in boot.headers["set-cookie"]
            assert boot.headers["cache-control"] == "no-store"
            headers = {"Origin": ctx.settings.PORTAL_ORIGIN,
                       "X-Portal-CSRF": boot.json()["data"]["csrf_token"]}
            denied = await client.post("/api/portal/v1/auth/challenges", json={"email": "buyer@example.com", "purpose": "login"})
            assert denied.status_code == 403
            invalid = await client.post("/api/portal/v1/auth/verify", headers=headers,
                                       json={"challenge_id": "bad", "code": "SECRET"})
            assert invalid.status_code == 422 and "SECRET" not in invalid.text
            issued = await client.post("/api/portal/v1/auth/challenges", headers=headers,
                                       json={"email": "buyer@example.com", "purpose": "login"})
            assert issued.status_code == 202 and issued.json()["code"] == 202
            challenge_id = issued.json()["data"]["challenge_id"]
            event = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_public_id == challenge_id))
            code = open_secret(ctx.settings.PORTAL_MAIL_KEYS["v1"], event.secret_envelope,
                event_key=event.event_key, purpose="login", object_id=challenge_id)
            wrong = "000001" if code != "000001" else "000002"
            failed = await client.post("/api/portal/v1/auth/verify", headers=headers,
                                      json={"challenge_id": challenge_id, "code": wrong})
            assert failed.status_code == 401 and failed.json()["data"]["error_code"] == "AUTH_FAILED"
            ctx.db.expire_all()
            challenge = ctx.db.scalar(select(AuthChallenge).where(AuthChallenge.public_id == challenge_id))
            assert challenge.attempts == 1
            verified = await client.post("/api/portal/v1/auth/verify", headers=headers,
                                        json={"challenge_id": challenge_id, "code": code})
            assert verified.status_code == 200
            assert "__Host-portal_session" in client.cookies
            assert "__Host-portal_preauth" not in client.cookies
            snapshot = await client.get("/api/portal/v1/session")
            assert snapshot.status_code == 200
            assert "okki_company_id" not in snapshot.text
            assert "sales_user_id" not in snapshot.text
            denied = await client.post("/api/portal/v1/auth/logout", headers=headers, json={})
            assert denied.status_code == 403  # Preauth CSRF cannot authorize session writes.
            headers["X-Portal-CSRF"] = verified.json()["data"]["csrf_token"]
            signed_out = await client.post("/api/portal/v1/auth/logout", headers=headers, json={})
            assert signed_out.status_code == 200
            assert "__Host-portal_session" not in client.cookies
            assert (await client.get("/api/portal/v1/session")).status_code == 401
            assert (await client.post("/api/portal/v1/auth/logout", headers=headers, json={})).status_code == 200
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("198.51.100.2", 30000)),
                base_url="https://orders.example.com") as outsider:
            denied = await outsider.get("/api/portal/v1/auth/bootstrap", headers={"X-Real-IP": "127.0.0.1"})
            assert denied.status_code == 403
    asyncio.run(scenario())


def test_otp_rejects_rebinding_to_equal_version_access(auth_context, portal_metadata):
    ctx = auth_context
    row, code = send_code(ctx)
    for name in ("ark_users", "ark_customer_accounts", "ark_customer_external_identities", "ark_customer_assignments"):
        ctx.db.execute(portal_metadata.tables[name].insert(), {"id": 2})
    other = CustomerAccess(site_id=ctx.site.id, customer_id=2, okki_namespace="okki:test",
        okki_company_id="2", external_identity_id=2, binding_fingerprint="b"*64,
        assignment_id=2, sales_user_id=2, status="enabled", can_order=True, can_view_price=True)
    ctx.db.add(other)
    ctx.db.flush()
    assert other.auth_version == ctx.access.auth_version
    ctx.member.access_id = other.id
    ctx.db.commit()
    assert verify(ctx, row, code) is None
