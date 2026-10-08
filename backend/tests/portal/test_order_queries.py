from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_orders import submission, quoting, priced_catalog, catalog, managed, portal_metadata, auth_context, submit
from test_auth_service import send_code, verify
from app.core.time import beijing_now
from app.portal import order_queries as service, admin_service, auth_service
from app.portal.errors import PortalError
from app.portal.models import Account, CustomerAccess, HistoryGrant, Membership, OrderRequest


@pytest.fixture
def submitted(submission, portal_metadata):
    ctx, key, body = submission
    result = submit(ctx, key, body)
    ctx.db.execute(portal_metadata.tables["ark_users"].insert(), {"id": 2, "is_active": True})
    ctx.db.commit()
    return ctx, result


def second_account(ctx, *, access=None):
    account = Account(email_normalized="another@example.com", email_display="another@example.com", contact_name="Another", status="active")
    ctx.db.add(account)
    ctx.db.flush()
    ctx.db.add(Membership(site_id=ctx.site.id, account_id=account.id, access_id=(access or ctx.access).id, status="active"))
    ctx.db.commit()
    ctx.preauth, ctx.token, ctx.csrf = auth_service.bootstrap(ctx.db, "127.0.0.2")
    ctx.db.commit()
    challenge, code = send_code(ctx, "another@example.com")
    return verify(ctx, challenge, code)[2]


def test_customer_list_detail_delivery_and_history_are_whitelisted(submitted):
    ctx, order = submitted
    page = service.customer_list(ctx.db, ctx.session_token)
    assert page["total"] == 1 and page["items"][0]["product_amount"] == "81.00"
    detail = service.customer_detail(ctx.db, ctx.session_token, order["request_id"])
    assert detail["delivery"]["address_line1"] == "10 Example Street"
    assert detail["items"][0]["quantity"] == 3
    assert detail["customer_safe_timeline"][0]["event"] == "order.submitted"
    assert not any(key in str(detail) for key in ("standard_json", "price_fingerprint", "inventory_snapshot", "servicing_user_id", "actor_id"))
    assert service.customer_list(ctx.db, ctx.session_token, status="cancelled")["total"] == 0
    assert service.customer_list(ctx.db, ctx.session_token, page=2, page_size=1)["items"] == []


def test_price_revocation_crops_both_list_and_nested_detail(submitted):
    ctx, order = submitted
    ctx.access.can_order = ctx.access.can_view_price = False
    ctx.db.commit()
    page = service.customer_list(ctx.db, ctx.session_token)
    detail = service.customer_detail(ctx.db, ctx.session_token, order["request_id"])
    forbidden = ("unit_price", "line_amount", "discount_amount", "product_amount", "total_amount", "currency", "fees", "payment_terms_snapshot")
    assert not any(key in str(page) or key in str(detail) for key in forbidden)
    assert detail["status"] == "submitted" and detail["items"][0]["quantity"] == 3


def test_same_company_authorized_member_shares_orders(submitted):
    ctx, order = submitted
    token = second_account(ctx)
    assert service.customer_list(ctx.db, token)["total"] == 1
    assert service.customer_detail(ctx.db, token, order["request_id"])["request_id"] == order["request_id"]


def test_other_company_cannot_count_or_read_order(submitted, portal_metadata):
    ctx, order = submitted
    ctx.db.execute(portal_metadata.tables["ark_customer_accounts"].insert(), {"id": 2})
    access = CustomerAccess(site_id=ctx.site.id, customer_id=2, okki_namespace="okki:test", okki_company_id="2",
        external_identity_id=1, binding_fingerprint="b"*64, assignment_id=1, sales_user_id=1,
        status="enabled", can_view_price=True, can_order=True)
    ctx.db.add(access)
    ctx.db.commit()
    token = second_account(ctx, access=access)
    assert service.customer_list(ctx.db, token)["total"] == 0
    for identifier in (order["request_id"], uuid4()):
        with pytest.raises(PortalError) as caught:
            service.customer_detail(ctx.db, token, identifier)
        assert caught.value.status == 404


def test_employee_scope_filters_count_and_detail(submitted):
    ctx, order = submitted
    assert service.employee_list(ctx.db, 1)["total"] == 1
    assert service.employee_list(ctx.db, 2)["total"] == 0
    with pytest.raises(PortalError) as caught:
        service.employee_detail(ctx.db, 2, order["request_id"])
    assert caught.value.status == 404
    with pytest.raises(PortalError) as caught:
        service.employee_list(ctx.db, 3)
    assert caught.value.status == 403


def test_employee_current_assignment_not_historical_snapshot_controls_scope(submitted, portal_metadata):
    ctx, order = submitted
    table = portal_metadata.tables["ark_customer_assignments"]
    ctx.db.execute(table.update().where(table.c.id==1).values(user_id=2))
    ctx.db.commit()
    assert service.employee_list(ctx.db, 1)["total"] == 0
    assert service.employee_list(ctx.db, 2)["total"] == 0  # Requires explicit portal handoff too.


def test_explicit_order_history_grant_is_read_only_scoped_and_revocable(submitted):
    ctx, order = submitted
    row = ctx.db.scalar(select(OrderRequest))
    grant = HistoryGrant(access_id=ctx.access.id, grantee_user_id=2, scope="order", order_request_id=row.id,
        reason="approved handoff", expires_at=beijing_now()+timedelta(days=1), created_by=1)
    ctx.db.add(grant)
    ctx.db.commit()
    assert service.employee_list(ctx.db, 2)["total"] == 1
    assert service.employee_detail(ctx.db, 2, order["request_id"])["available_actions"] == []
    grant.revoked_at = beijing_now()
    ctx.db.commit()
    assert service.employee_list(ctx.db, 2)["total"] == 0


def test_expired_history_grant_does_not_grant_access(submitted):
    ctx, _ = submitted
    ctx.db.add(HistoryGrant(access_id=ctx.access.id, grantee_user_id=2, scope="order",
        order_request_id=ctx.db.scalar(select(OrderRequest)).id, reason="expired",
        expires_at=beijing_now()-timedelta(seconds=1), created_by=1))
    ctx.db.commit()
    assert service.employee_list(ctx.db, 2)["total"] == 0


def test_read_all_is_explicit_and_does_not_supply_actions(submitted, monkeypatch):
    ctx, order = submitted
    def employee(db, actor_id, permission):
        assert permission == "portal_order:read"
        return {"id": actor_id, "roles": ["sales"], "permissions": {permission, "portal_order:read_all"}}
    monkeypatch.setattr(admin_service, "employee_principal", employee)
    assert service.employee_list(ctx.db, 2)["total"] == 1
    assert service.employee_detail(ctx.db, 2, order["request_id"])["available_actions"] == []


def test_history_scope_does_not_expand_to_later_or_same_second_requests(submitted):
    ctx, _ = submitted
    row = ctx.db.scalar(select(OrderRequest))
    grant = HistoryGrant(access_id=ctx.access.id, grantee_user_id=2, scope="request_history",
        reason="historical records only", expires_at=beijing_now()+timedelta(days=1), created_by=1,
        created_at=row.created_at)
    ctx.db.add(grant)
    ctx.db.commit()
    assert service.employee_list(ctx.db, 2)["total"] == 0
    grant.created_at = row.created_at + timedelta(seconds=1)
    ctx.db.commit()
    assert service.employee_list(ctx.db, 2)["total"] == 1


def test_both_order_http_surfaces_enforce_scope_and_pagination(submitted, monkeypatch):
    import asyncio
    import httpx
    from fastapi import FastAPI
    from app.auth.dependencies import get_current_user
    from app.core.database import get_db
    from app.portal import router as customer_http, admin_router
    ctx, order = submitted
    ctx.settings.PORTAL_TRUSTED_PROXY_IPS = ["127.0.0.1"]
    monkeypatch.setattr(customer_http, "get_settings", lambda: ctx.settings)
    app = FastAPI()
    app.include_router(customer_http.router, prefix="/api/portal/v1")
    app.include_router(admin_router.router, prefix="/api/portal/admin/v1")
    app.dependency_overrides[get_db] = lambda: ctx.db
    employee = {"sub": "1"}
    app.dependency_overrides[get_current_user] = lambda: employee

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ctx.settings.PORTAL_ORIGIN,
                                     headers={"X-Real-IP": "203.0.113.1"}) as client:
            customer = "/api/portal/v1/orders"
            admin = "/api/portal/admin/v1/orders"
            assert (await client.get(customer)).status_code == 401
            client.cookies.set("__Host-portal_session", ctx.session_token)
            response = await client.get(customer)
            assert response.json()["data"]["total"] == 1 and response.headers["cache-control"] == "no-store"
            assert (await client.get(customer+"/"+order["request_id"])).status_code == 200
            assert (await client.get(customer, params={"status": "all"})).status_code == 422
            assert (await client.get(admin, params={"page_size": 101})).status_code == 422
            assert (await client.get(admin)).json()["data"]["total"] == 1
            employee["sub"] = "2"
            assert (await client.get(admin)).json()["data"]["total"] == 0
            assert (await client.get(admin+"/"+order["request_id"])).status_code == 404
    asyncio.run(scenario())
