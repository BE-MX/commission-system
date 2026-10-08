from app.portal.binding_review_service import context as binding_review_context
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Column, Table, select, func

from test_auth_service import auth_context, verify
from app.core.time import beijing_now
from app.portal import admin_service as admin, auth_service as auth
from app.portal.errors import PortalError
from app.portal.models import (Account, AuditEvent, AuthChallenge, CommandReceipt, Invitation,
                              Membership, OutboxEvent, PortalSession)
from app.portal.schemas import (AccountUpdate, ChallengeInput, CustomerUpdate, InvitationInput)
from app.portal.security import open_secret


@pytest.fixture
def portal_metadata(portal_metadata):
    from app.auth.models import ArkUser
    from app.customer.models import (CustomerAccount, CustomerAssignment, CustomerExternalIdentity,
        CustomerObjectOwnership, CustomerSourceRecord, CustomerContact, CustomerContactRelationship)
    for model in (CustomerAccount, CustomerAssignment, CustomerExternalIdentity, ArkUser,
                  CustomerObjectOwnership, CustomerSourceRecord, CustomerContact, CustomerContactRelationship):
        name = model.__tablename__
        if name not in portal_metadata.tables:
            Table(name, portal_metadata)
        table = portal_metadata.tables[name]
        for column in model.__table__.columns:
            if column.name not in table.c:
                table.append_column(Column(column.name, column.type, primary_key=column.primary_key,
                                           nullable=not column.primary_key))
    return portal_metadata


@pytest.fixture
def managed(auth_context, monkeypatch, portal_metadata):
    ctx = auth_context
    table = portal_metadata.tables["ark_customer_assignments"]
    ctx.db.execute(table.update().where(table.c.id == 1).values(customer_id=1, user_id=1,
        assignment_role="primary", assignment_status="active", effective_from=beijing_now() - timedelta(days=1)))
    ctx.db.commit()
    company = portal_metadata.tables["ark_customer_accounts"]
    ctx.db.execute(company.update().where(company.c.id == 1).values(display_name="Buyer Company"))
    ctx.db.commit()
    company = portal_metadata.tables["ark_customer_accounts"]
    ctx.db.execute(company.update().where(company.c.id == 1).values(record_status="active", identity_status="verified"))
    user = portal_metadata.tables["ark_users"]
    ctx.db.execute(user.update().where(user.c.id == 1).values(is_active=True))
    identity = portal_metadata.tables["ark_customer_external_identities"]
    ctx.db.execute(identity.update().where(identity.c.id == 1).values(customer_id=1, source_system="okki",
        source_account_key="okki:test", identifier_type="company_id", normalized_value="1",
        identity_strength="strong", cardinality="one_to_one", verification_status="verified", status="active"))
    ctx.db.commit()
    from app.customer.models import CustomerAssignment, CustomerExternalIdentity
    ctx.access.binding_fingerprint = admin.binding_fingerprint(1,
        ctx.db.get(CustomerExternalIdentity, 1), ctx.db.get(CustomerAssignment, 1))
    ctx.db.commit()
    ctx.settings.PORTAL_INVITATION_HOURS = 72
    ctx.settings.PORTAL_OKKI_NAMESPACE = "okki:test"
    monkeypatch.setattr(admin, "get_settings", lambda: ctx.settings)
    def employee(db, actor_id, permission):
        if actor_id == 3:
            raise PortalError("ACTION_FORBIDDEN", "Denied", 403)
        return {"id": actor_id, "roles": ["sales"], "permissions": {permission}}
    monkeypatch.setattr(admin, "employee_principal", employee)
    return ctx


def invitation_body(email="new@example.com"):
    return InvitationInput(email=email, contact_name="Buyer")


def test_invitation_is_encrypted_and_same_command_replays(managed):
    ctx = managed
    key = uuid4()
    first = admin.invite(ctx.db, 1, ctx.access.public_id, key, invitation_body())
    ctx.db.commit()
    second = admin.invite(ctx.db, 1, ctx.access.public_id, key, invitation_body("NEW@example.com"))
    ctx.db.commit()
    assert first["invitation_id"] == second["invitation_id"] and second["replayed"]
    assert ctx.db.scalar(select(func.count()).select_from(Invitation)) == 1
    assert ctx.db.scalar(select(func.count()).select_from(CommandReceipt)) == 1
    event = ctx.db.scalar(select(OutboxEvent))
    token = open_secret(ctx.settings.PORTAL_MAIL_KEYS["v1"], event.secret_envelope,
        event_key=event.event_key, purpose="activate", object_id=first["invitation_id"])
    assert len(token) >= 32 and token not in str(first) and token not in str(event.payload_json)
    assert "new@example.com" not in str(event.payload_json)
    with pytest.raises(PortalError) as error:
        admin.invite(ctx.db, 1, ctx.access.public_id, key, invitation_body("different@example.com"))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_invitation_then_otp_activates_exact_membership(managed):
    ctx = managed
    result = admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    event = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "invitation"))
    token = open_secret(ctx.settings.PORTAL_MAIL_KEYS["v1"], event.secret_envelope,
        event_key=event.event_key, purpose="activate", object_id=result["invitation_id"])
    invitation = ctx.db.scalar(select(Invitation))
    account = ctx.db.get(Account, invitation.account_id)
    assert account.status == "invited" and account.verified_at is None
    row = auth.challenge(ctx.db, auth.require_preauth(ctx.db, ctx.token, ctx.csrf),
        ChallengeInput(email="new@example.com", purpose="activate", invitation_token=token), "127.0.0.1")
    ctx.db.commit()
    event = ctx.db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "auth_code"))
    code = open_secret(ctx.settings.PORTAL_MAIL_KEYS["v1"], event.secret_envelope,
        event_key=event.event_key, purpose="activate", object_id=row.public_id)
    principal, session, opaque = verify(ctx, row, code)
    assert principal.account.id == account.id and account.status == "active" and account.verified_at
    assert invitation.consumed_at and principal.membership.status == "active"
    assert auth.authenticate(ctx.db, opaque)[0].access.id == ctx.access.id
    assert ctx.db.scalar(select(func.count()).select_from(PortalSession)) == 1


@pytest.mark.parametrize("actor,code", [(2, "RESOURCE_NOT_FOUND"), (3, "ACTION_FORBIDDEN")])
def test_invitation_requires_live_permission_and_owner_scope(managed, actor, code):
    ctx = managed
    with pytest.raises(PortalError) as error:
        admin.invite(ctx.db, actor, ctx.access.public_id, uuid4(), invitation_body())
    assert error.value.code == code
    assert ctx.db.scalar(select(func.count()).select_from(Invitation)) == 0


def test_replay_still_checks_current_employee_scope(managed):
    ctx = managed
    key = uuid4()
    admin.invite(ctx.db, 1, ctx.access.public_id, key, invitation_body())
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        admin.invite(ctx.db, 2, ctx.access.public_id, key, invitation_body())
    assert error.value.status == 404


def test_reinvite_revokes_old_link_without_duplicate_member(managed):
    ctx = managed
    first = admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    second = admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    old = ctx.db.scalar(select(Invitation).where(Invitation.public_id == first["invitation_id"]))
    assert old.revoked_at and old.row_version == 2
    assert first["invitation_id"] != second["invitation_id"]
    account = ctx.db.scalar(select(Account).where(Account.email_normalized == "new@example.com"))
    assert ctx.db.scalar(select(func.count()).select_from(Membership).where(Membership.account_id == account.id)) == 1


def test_admin_cannot_bypass_email_verification(managed):
    ctx = managed
    result = admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    invite = ctx.db.scalar(select(Invitation))
    account = ctx.db.get(Account, invite.account_id)
    with pytest.raises(PortalError) as error:
        admin.update_account(ctx.db, 1, account.public_id, account.row_version,
            AccountUpdate(status="active", reason="review"))
    assert error.value.code == "EMAIL_NOT_VERIFIED" and account.status == "invited"


def test_customer_suspend_bumps_version_and_rejects_stale_update(managed):
    ctx = managed
    version = ctx.access.row_version
    result = admin.update_customer(ctx.db, 1, ctx.access.public_id, version,
        CustomerUpdate(status="suspended", capabilities={"can_order": False, "can_view_price": True},
            catalog_item_ids=[], reason="temporary suspension"))
    ctx.db.commit()
    assert result["row_version"] == version + 1 and ctx.access.auth_version == 2
    with pytest.raises(PortalError) as error:
        admin.update_customer(ctx.db, 1, ctx.access.public_id, version,
            CustomerUpdate(status="enabled", capabilities={"can_order": False, "can_view_price": True},
                catalog_item_ids=[], reason="stale page"))
    assert error.value.code == "VERSION_CONFLICT" and ctx.access.status == "suspended"
    assert ctx.db.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_rollback_leaves_no_account_invite_outbox_or_receipt(managed):
    ctx = managed
    admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.rollback()
    for model in (Invitation, OutboxEvent, CommandReceipt, AuditEvent):
        assert ctx.db.scalar(select(func.count()).select_from(model)) == 0
    assert ctx.db.scalar(select(Account).where(Account.email_normalized == "new@example.com")) is None


def test_admin_http_scope_version_and_invite_replay(managed, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal import admin_router
    ctx = managed
    app = FastAPI()
    app.include_router(admin_router.router, prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    # Claims include stale super_admin. Only sub may enter service authorization.
    claims = {"sub": "2", "roles": ["super_admin"], "permissions": ["portal_access:admin"]}
    app.dependency_overrides[get_current_user] = lambda: claims
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/portal/admin/v1/customers/{ctx.access.public_id}/invitations"
            headers = {"Idempotency-Key": str(uuid4())}
            denied = await client.post(path, headers=headers, json=invitation_body().model_dump())
            assert denied.status_code == 404
            claims["sub"] = "1"
            missing = await client.post(path, json=invitation_body().model_dump())
            assert missing.status_code == 428
            first = await client.post(path, headers=headers, json=invitation_body().model_dump())
            second = await client.post(path, headers=headers, json=invitation_body().model_dump())
            assert first.status_code == 201 and second.status_code == 200
            assert first.json()["data"]["invitation_id"] == second.json()["data"]["invitation_id"]
            update_path = f"/api/portal/admin/v1/customers/{ctx.access.public_id}"
            body = {"status": "suspended", "capabilities": {"can_view_price": False, "can_order": False},
                    "catalog_item_ids": [], "reason": "review"}
            assert (await client.patch(update_path, json=body)).status_code == 428
            changed = await client.patch(update_path, json=body, headers={"If-Match": '"1"'})
            assert changed.status_code == 200
            stale = await client.patch(update_path, json=body, headers={"If-Match": '"1"'})
            assert stale.status_code == 409
            assert stale.headers["cache-control"] == "private, no-store"
    asyncio.run(scenario())


def test_account_disable_revokes_existing_session(managed):
    from test_auth_service import send_code
    ctx = managed
    row, code = send_code(ctx)
    _, session, token = verify(ctx, row, code)
    admin.update_account(ctx.db, 1, ctx.account.public_id, ctx.account.row_version,
                         AccountUpdate(status="disabled", reason="access removed"))
    ctx.db.commit()
    assert session.revoked_at is not None
    with pytest.raises(PortalError) as error:
        auth.authenticate(ctx.db, token)
    assert error.value.status == 401


def test_catalog_grant_cannot_cross_site(managed):
    from app.portal.models import CatalogItem, Site
    ctx = managed
    other = Site(code="other", name="Other", allowed_origin="https://other.example.com")
    ctx.db.add(other)
    ctx.db.flush()
    item = CatalogItem(site_id=other.id, product_kind="hair", source_namespace="okki:test",
        product_id="1", sku_id="1", standard_fingerprint="a"*64, standard_json={},
        display_name="Product", color_name="Black", status="published", inventory_unit="g",
        sale_unit="pack", conversion_factor="20")
    ctx.db.add(item)
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        admin.update_customer(ctx.db, 1, ctx.access.public_id, ctx.access.row_version,
            CustomerUpdate(status="enabled", capabilities={"can_order": True, "can_view_price": True},
                           catalog_item_ids=[item.public_id], reason="catalog"))
    assert error.value.status == 422
    assert ctx.access.row_version == 1


def test_invitation_cannot_rebind_email_to_another_company(managed, portal_metadata):
    from app.portal.models import CustomerAccess
    ctx = managed
    for name in ("ark_users", "ark_customer_accounts", "ark_customer_external_identities", "ark_customer_assignments"):
        ctx.db.execute(portal_metadata.tables[name].insert(), {"id": 2})
    table = portal_metadata.tables["ark_customer_assignments"]
    ctx.db.execute(table.update().where(table.c.id == 2).values(customer_id=2, user_id=1,
        assignment_role="primary", assignment_status="active", effective_from=beijing_now() - timedelta(days=1)))
    company = portal_metadata.tables["ark_customer_accounts"]
    ctx.db.execute(company.update().where(company.c.id == 2).values(record_status="active", identity_status="verified"))
    identity = portal_metadata.tables["ark_customer_external_identities"]
    ctx.db.execute(identity.update().where(identity.c.id == 2).values(customer_id=2, source_system="okki",
        source_account_key="okki:test", identifier_type="company_id", normalized_value="2",
        identity_strength="strong", cardinality="one_to_one", verification_status="verified", status="active"))
    from app.customer.models import CustomerAssignment, CustomerExternalIdentity
    fingerprint = admin.binding_fingerprint(2, ctx.db.get(CustomerExternalIdentity, 2), ctx.db.get(CustomerAssignment, 2))
    other = CustomerAccess(site_id=ctx.site.id, customer_id=2, okki_namespace="okki:test",
        okki_company_id="2", external_identity_id=2, binding_fingerprint=fingerprint,
        assignment_id=2, sales_user_id=1, status="enabled")
    ctx.db.add(other)
    ctx.db.commit()
    with pytest.raises(PortalError) as error:
        admin.invite(ctx.db, 1, other.public_id, uuid4(), invitation_body("buyer@example.com"))
    assert error.value.code == "ACCOUNT_BINDING_CONFLICT"
    assert ctx.member.access_id == ctx.access.id
    assert ctx.db.scalar(select(func.count()).select_from(Invitation)) == 0


def test_revoked_invitation_cannot_issue_activation_code(managed):
    ctx = managed
    result = admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    event = ctx.db.scalar(select(OutboxEvent))
    token = open_secret(ctx.settings.PORTAL_MAIL_KEYS["v1"], event.secret_envelope,
        event_key=event.event_key, purpose="activate", object_id=result["invitation_id"])
    admin.revoke_invitation(ctx.db, 1, result["invitation_id"], 1, "withdraw invitation")
    ctx.db.commit()
    row = auth.challenge(ctx.db, auth.require_preauth(ctx.db, ctx.token, ctx.csrf),
        ChallengeInput(email="new@example.com", purpose="activate", invitation_token=token), "127.0.0.1")
    ctx.db.commit()
    assert row.account_id is None
    assert ctx.db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type == "auth_code")) == 0


@pytest.mark.parametrize("operation", ["account", "invite", "access"])
def test_former_owner_cannot_manage_after_assignment_changes(managed, portal_metadata, operation):
    ctx = managed
    result = admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    table = portal_metadata.tables["ark_customer_assignments"]
    ctx.db.execute(table.update().where(table.c.id == 1).values(user_id=2))
    ctx.db.commit()
    # Even without the upstream hook's review_required flag, current ownership blocks it.
    with pytest.raises(PortalError) as error:
        if operation == "account":
            admin.update_account(ctx.db, 1, ctx.account.public_id, 1,
                                 AccountUpdate(status="disabled", reason="former owner"))
        elif operation == "invite":
            admin.revoke_invitation(ctx.db, 1, result["invitation_id"], 1, "former owner")
        else:
            admin.update_customer(ctx.db, 1, ctx.access.public_id, 1,
                CustomerUpdate(status="suspended", capabilities={"can_order": False, "can_view_price": False},
                               catalog_item_ids=[], reason="former owner"))
    assert error.value.status == 404
    assert ctx.account.status == "active" and ctx.access.status == "enabled"


def test_super_admin_cannot_erase_review_gate_through_suspend(managed, monkeypatch):
    ctx = managed
    monkeypatch.setattr(admin, "employee_principal", lambda db, actor_id, permission:
        {"id": actor_id, "roles": ["super_admin"], "permissions": []})
    ctx.access.status = "review_required"
    ctx.db.commit()
    for status in ("suspended", "enabled"):
        with pytest.raises(PortalError) as error:
            admin.update_customer(ctx.db, 1, ctx.access.public_id, 1,
                CustomerUpdate(status=status, capabilities={"can_order": False, "can_view_price": False},
                               catalog_item_ids=[], reason="review"))
        assert error.value.code == "IDENTITY_REVIEW_REQUIRED"
        assert ctx.access.status == "review_required"


def test_disabled_unverified_account_can_reenter_invitation_flow(managed):
    ctx = managed
    admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    account = ctx.db.scalar(select(Account).where(Account.email_normalized == "new@example.com"))
    admin.update_account(ctx.db, 1, account.public_id, 1, AccountUpdate(status="disabled", reason="pause"))
    ctx.db.commit()
    result = admin.update_account(ctx.db, 1, account.public_id, 2,
                                  AccountUpdate(status="invited", reason="resume invitation"))
    ctx.db.commit()
    assert result["requires_invitation"] and account.verified_at is None and account.status == "invited"
    result = admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    invitation = ctx.db.scalar(select(Invitation).where(Invitation.public_id == result["invitation_id"]))
    assert invitation.account_version == account.auth_version == 3
    assert ctx.db.scalar(select(func.count()).select_from(PortalSession)) == 0


def test_list_and_count_use_current_owner_and_literal_keyword(managed, portal_metadata):
    ctx = managed
    result = admin.list_customers(ctx.db, 1)
    assert result["total"] == 1 and result["items"][0]["company_display_name"] == "Buyer Company"
    assert admin.list_customers(ctx.db, 1, keyword="%") == {"items": [], "total": 0, "page": 1, "page_size": 20}
    table = portal_metadata.tables["ark_customer_assignments"]
    ctx.db.execute(table.update().where(table.c.id == 1).values(user_id=2))
    ctx.db.commit()
    assert admin.list_customers(ctx.db, 1)["total"] == 0
    assert admin.list_customers(ctx.db, 1)["items"] == []


def new_identity(ctx, metadata, *, customer_id=1):
    table = metadata.tables["ark_customer_external_identities"]
    ctx.db.execute(table.insert(), {"id": 2, "customer_id": customer_id, "source_system": "okki",
        "source_account_key": "okki:test", "identifier_type": "company_id", "normalized_value": "501",
        "identity_strength": "strong", "cardinality": "one_to_one", "verification_status": "verified",
        "status": "active"})
    ctx.db.commit()


def test_rebind_invalidates_credentials_without_rewriting_orders(managed, portal_metadata, monkeypatch):
    from app.portal.models import Quote, OrderRequest
    from app.portal.schemas import RebindInput
    from test_auth_service import send_code
    ctx = managed
    admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    row, code = send_code(ctx)
    _, session, _ = verify(ctx, row, code)
    quote = Quote(access_id=ctx.access.id, account_id=ctx.account.id, membership_id=ctx.member.id,
        expires_at=beijing_now() + timedelta(minutes=5), authority_versions_json={}, input_hash="a"*64,
        result_hash="b"*64, currency="USD", product_amount="10.00", lines_json=[],
        delivery_json={}, payment_terms_snapshot={})
    old_quote = Quote(access_id=ctx.access.id, account_id=ctx.account.id, membership_id=ctx.member.id,
        expires_at=beijing_now() + timedelta(minutes=5), authority_versions_json={}, input_hash="c"*64,
        result_hash="d"*64, currency="USD", product_amount="10.00", lines_json=[],
        delivery_json={}, payment_terms_snapshot={}, status="consumed")
    ctx.db.add_all([quote, old_quote])
    ctx.db.flush()
    order = OrderRequest(access_id=ctx.access.id, account_id=ctx.account.id, customer_id_snapshot=1,
        okki_company_id_snapshot="1", sales_user_id_snapshot=1, servicing_user_id=1,
        public_no="POR-REBIND", idempotency_key=str(uuid4()), client_payload_hash="e"*64,
        quote_id=old_quote.id, submitted_at=beijing_now())
    ctx.db.add(order)
    ctx.access.status = "review_required"
    ctx.db.commit()
    new_identity(ctx, portal_metadata)
    monkeypatch.setattr(admin, "employee_principal", lambda db, actor_id, permission:
        {"id": actor_id, "roles": ["super_admin"], "permissions": []})
    result = admin.rebind_identity(ctx.db, 1, ctx.access.public_id, 1,
                                   RebindInput(review_fingerprint=binding_review_context(ctx.db, 1, ctx.access.public_id)["review_fingerprint"], identity_id="2", reason="verified replacement"))
    ctx.db.commit()
    assert result["requires_enable"] and result["status"] == "suspended" and result["expired_quotes"] == 1
    assert ctx.access.okki_company_id == "501" and ctx.access.customer_id == 1
    assert ctx.access.auth_version == 2 and session.revoked_at is not None
    assert quote.status == "expired" and old_quote.status == "consumed"
    assert ctx.db.scalar(select(Invitation)).revoked_at is not None
    assert order.okki_company_id_snapshot == "1" and order.sales_user_id_snapshot == 1
    assert order.status == "submitted" and order.row_version == 1
    admin.update_customer(ctx.db, 1, ctx.access.public_id, 2,
        CustomerUpdate(status="enabled", capabilities={"can_view_price": True, "can_order": True},
                       catalog_item_ids=[], reason="reviewed access"))
    ctx.db.commit()
    assert ctx.access.status == "enabled"


def test_rebind_cannot_follow_identity_into_other_company(managed, portal_metadata):
    from app.portal.schemas import RebindInput
    ctx = managed
    new_identity(ctx, portal_metadata, customer_id=2)
    with pytest.raises(PortalError) as error:
        admin.rebind_identity(ctx.db, 1, ctx.access.public_id, 1,
                              RebindInput(review_fingerprint=binding_review_context(ctx.db, 1, ctx.access.public_id)["review_fingerprint"], identity_id="2", reason="wrong company"))
    assert error.value.code == "IDENTITY_REVIEW_REQUIRED"
    assert ctx.access.okki_company_id == "1" and ctx.access.auth_version == 1


def test_customer_detail_has_scoped_account_controls_without_secrets(managed):
    ctx = managed
    admin.invite(ctx.db, 1, ctx.access.public_id, uuid4(), invitation_body())
    ctx.db.commit()
    result = admin.customer_detail(ctx.db, 1, ctx.access.public_id, page_size=1)
    assert result["accounts"]["total"] == 2
    assert len(result["accounts"]["items"]) == 1
    assert result["accounts"]["items"][0]["email"] == "new@example.com"
    assert result["accounts"]["items"][0]["invitation"]["status"] == "pending"
    assert "token_hash" not in str(result) and "secret_envelope" not in str(result)
    with pytest.raises(PortalError) as error:
        admin.customer_detail(ctx.db, 2, ctx.access.public_id)
    assert error.value.status == 404
