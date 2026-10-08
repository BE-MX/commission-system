from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import select, func

from test_admin_service import managed, portal_metadata
from test_auth_service import auth_context, send_code, verify
from app.portal import site_service as site, auth_service as auth
from app.portal.models import AuditEvent, Site
from app.portal.schemas import SiteUpdate, SitePolicy
from app.portal.errors import PortalError


@pytest.fixture
def configured(managed, monkeypatch):
    monkeypatch.setattr(site, "get_settings", lambda: managed.settings)
    return managed


def settings_body(status="enabled", label="Payment before shipment"):
    return SiteUpdate(name="LeShine", status=status, reason="approved policy",
        policy={"quote_valid_minutes": 15, "proposal_valid_hours": [24, 48],
            "payment_terms": [{"code": "prepaid", "display_text": label, "deposit_percent": "100.00"}],
            "default_payment_term_code": "prepaid"})


def test_initial_settings_create_is_conditional_and_whitelisted(configured):
    ctx = configured
    ctx.settings.PORTAL_SITE_CODE = "new-site"
    before = site.read_settings(ctx.db, 1)
    assert before["configured"] is False and before["row_version"] == 0
    result = site.update_settings(ctx.db, 1, 0, settings_body("disabled"))
    ctx.db.commit()
    assert result["configured"] and result["row_version"] == 1
    assert result["origin"] == ctx.settings.PORTAL_ORIGIN and result["currency"] == "USD"
    assert "PORTAL_OTP_SECRET" not in str(result) and "smtp" not in str(result).lower()
    with pytest.raises(PortalError) as error:
        site.update_settings(ctx.db, 1, 0, settings_body("disabled"))
    assert error.value.code == "VERSION_CONFLICT"
    assert ctx.db.scalar(select(func.count()).select_from(Site).where(Site.code == "new-site")) == 1


def test_site_close_then_reopen_does_not_revive_sessions_or_preauth(configured):
    ctx = configured
    row, code = send_code(ctx)
    _, session, token = verify(ctx, row, code)
    preauth, pretoken, csrf = auth.bootstrap(ctx.db, "127.0.0.2")
    ctx.db.commit()
    site.update_settings(ctx.db, 1, 1, settings_body("disabled"))
    ctx.db.commit()
    assert session.revoked_at is not None and preauth.consumed_at is not None
    site.update_settings(ctx.db, 1, 2, settings_body("enabled"))
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        auth.authenticate(ctx.db, token)
    assert error.value.status == 401
    with pytest.raises(PortalError) as error:
        auth.require_preauth(ctx.db, pretoken, csrf)
    assert error.value.status == 401


def test_policy_version_changes_only_with_policy(configured):
    ctx = configured
    first = site.update_settings(ctx.db, 1, 1, settings_body())
    ctx.db.commit()
    second = site.update_settings(ctx.db, 1, 2, settings_body())
    ctx.db.commit()
    assert first["policy_version"] == second["policy_version"] == 2
    old = deepcopy(ctx.site.policy_json)
    third = site.update_settings(ctx.db, 1, 3, settings_body(label="Payment due before dispatch"))
    ctx.db.commit()
    assert third["policy_version"] == 3
    assert old["payment_terms"][0]["display_text"] == "Payment before shipment"
    with pytest.raises(PortalError) as error:
        site.update_settings(ctx.db, 1, 2, settings_body())
    assert error.value.code == "VERSION_CONFLICT"


def test_settings_cannot_edit_origin_secret_or_currency():
    values = settings_body().model_dump()
    for field, value in (("allowed_origin", "https://attacker.example"), ("otp_secret", "key"), ("currency", "EUR")):
        with pytest.raises(ValidationError):
            SiteUpdate.model_validate({**values, field: value})


@pytest.mark.parametrize("bad_policy", [
    {"payment_terms": []},
    {"proposal_valid_hours": [24, 24]},
    {"default_payment_term_code": "unknown"},
    {"payment_terms": [{"code": "prepaid", "display_text": "Bad\nTerms", "deposit_percent": "100.00"}]},
    {"payment_terms": [{"code": "prepaid", "display_text": "Terms", "deposit_percent": "100.01"}]},
])
def test_invalid_or_missing_payment_terms_cannot_enable(bad_policy):
    values = settings_body().model_dump()
    values["policy"].update(bad_policy)
    with pytest.raises(ValidationError):
        SiteUpdate.model_validate(values)


def test_rollback_keeps_prior_site_and_audit(configured):
    ctx = configured
    old = (ctx.site.status, ctx.site.row_version, deepcopy(ctx.site.policy_json))
    site.update_settings(ctx.db, 1, 1, settings_body("disabled"))
    ctx.db.rollback()
    assert (ctx.site.status, ctx.site.row_version, ctx.site.policy_json) == old
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_settings_http_supports_initial_version_and_rejects_stale_form(configured):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal.admin_router import router
    ctx = configured
    ctx.settings.PORTAL_SITE_CODE = "new-site"
    app = FastAPI()
    app.include_router(router, prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1"}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/api/portal/admin/v1/settings"
            result = await client.get(url)
            assert result.status_code == 200 and result.json()["data"]["row_version"] == 0
            body = settings_body("disabled").model_dump()
            assert (await client.patch(url, json=body)).status_code == 428
            created = await client.patch(url, json=body, headers={"If-Match": '"0"'})
            assert created.status_code == 200 and created.json()["data"]["row_version"] == 1
            stale = await client.patch(url, json=body, headers={"If-Match": '"0"'})
            assert stale.status_code == 409
            private = await client.patch(url, json={**body, "smtp_password": "DO-NOT-ECHO"}, headers={"If-Match": '"1"'})
            assert private.status_code == 422 and "DO-NOT-ECHO" not in private.text
    asyncio.run(scenario())
