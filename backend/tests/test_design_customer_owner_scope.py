"""Booking search and submission use OKKI owners, never commission snapshots."""

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.auth.models import ArkRole, ArkUser, ArkUserExternalBinding, ArkUserRole
from app.commerce_transition.models import PlatformPolicy  # noqa: F401 - shared fixture FK target
from app.core.database import get_db
from app.core.time import beijing_today
from app.customer_media import router as media_router
from app.design import router as design_router
from app.design import request_service
from app.design.models import DesignScheduleRequest
from app.models.business import CustomerInfo
from app.models.customer import CustomerCommissionSnapshot
from tests.customer_media_support import set_grants


@pytest.fixture
def booking(db, monkeypatch):
    user = ArkUser(username="booking-owner", real_name="Booking Owner", password_hash="unused", is_active=True)
    db.add(user)
    db.flush()
    binding = ArkUserExternalBinding(
        ark_user_id=user.id, provider="okki", external_account_id="55411216",
        binding_status="active", is_primary=True,
    )
    db.add(binding)
    db.add_all([
        CustomerInfo(company_id="104825242721250", company_name="Tilly Gay", owner_user_ids=[55411216]),
        CustomerInfo(company_id="other-customer", company_name="Tilly Gay Other", owner_user_ids=[999]),
    ])
    db.commit()
    app = FastAPI()
    app.include_router(media_router.router, prefix="/media")
    app.include_router(design_router.router, prefix="/design")
    actor = {"sub": str(user.id), "roles": [], "permissions": ["design:write"]}
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_db] = lambda: db
    for name in ("_notify_audit_needed", "_notify_design_dept"):
        monkeypatch.setattr(design_router, name, lambda **_kwargs: None)
    # Production numbering uses a MySQL upsert; keep the real request write in SQLite.
    monkeypatch.setattr(request_service, "generate_request_no", lambda _db: "DR-OWNER-SCOPE-001")
    set_grants(db, user.id, ["design:write"])
    with TestClient(app) as client:
        yield client, user, binding, actor


def submit(client, customer_id="104825242721250"):
    tomorrow = (beijing_today() + timedelta(days=1)).isoformat()
    return client.post("/design/requests", json={
        "customer_id": customer_id, "customer_name": "Forged Customer",
        "salesperson_id": 9999, "salesperson_name": "Forged User",
        "shoot_type": "product", "expect_start_date": tomorrow, "expect_end_date": tomorrow,
    })


@pytest.mark.parametrize("extra", [
    [], ["customer_media:admin"], ["design:manage"],
    ["customer_media:admin", "customer_media_account:read_all", "customer_media:read_all"],
])
def test_owner_without_snapshot_can_search_and_submit_despite_action_grants(db, booking, extra):
    client, user, _, actor = booking
    actor["permissions"] += extra
    set_grants(db, user.id, actor["permissions"])
    assert db.query(CustomerCommissionSnapshot).count() == 0
    response = client.get("/media/customers", params={"search": "Tilly Gay"})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]] == ["104825242721250"]
    response = submit(client)
    assert response.status_code == 200, response.text
    row = db.get(DesignScheduleRequest, response.json()["data"]["id"])
    assert (row.customer_name, row.salesperson_id, row.salesperson_name) == ("Tilly Gay", user.id, user.real_name)
    assert db.query(CustomerCommissionSnapshot).count() == 0


@pytest.mark.parametrize("owners", [[999], [], None])
def test_stale_commission_snapshot_never_grants_booking_access(db, booking, owners):
    client, user, _, actor = booking
    actor["permissions"] += ["customer_media:admin", "customer_media_account:read_all"]
    set_grants(db, user.id, actor["permissions"])
    db.get(CustomerInfo, "104825242721250").owner_user_ids = owners
    db.add(CustomerCommissionSnapshot(
        customer_id="104825242721250", salesperson_id="55411216", is_current=True, source="manual",
    ))
    db.commit()
    assert client.get("/media/customers", params={"search": "Tilly Gay"}).json()["data"] == []
    assert submit(client).status_code == 403
    assert db.query(DesignScheduleRequest).count() == 0


def test_submit_rechecks_owner_after_search_and_uses_exact_id(db, booking):
    client, user, _, actor = booking
    actor["permissions"].append("customer_media:admin")
    set_grants(db, user.id, actor["permissions"])
    assert client.get("/media/customers", params={"search": "Tilly Gay"}).json()["data"]
    db.get(CustomerInfo, "104825242721250").owner_user_ids = [999]
    db.commit()
    for customer_id in ("104825242721250", "other-customer", "missing-customer"):
        assert submit(client, customer_id).status_code == 403
    assert db.query(DesignScheduleRequest).count() == 0


@pytest.mark.parametrize("binding_status", ["inactive", "missing"])
def test_missing_active_okki_binding_rejects_search_and_submit(db, booking, binding_status):
    client, _, binding, _ = booking
    if binding_status == "missing":
        db.delete(binding)
    else:
        binding.binding_status = binding_status
    db.commit()
    assert client.get("/media/customers", params={"search": "Tilly"}).status_code == 409
    assert submit(client).status_code == 409
    assert db.query(DesignScheduleRequest).count() == 0


def test_contact_name_search_keeps_owner_scope(db, booking):
    client, _, _, _ = booking
    for customer_id in ("104825242721250", "other-customer"):
        db.connection().exec_driver_sql(
            "INSERT INTO lsordertest.customer_contacts (company_id, name) VALUES (?, ?)",
            (customer_id, "Same Contact"),
        )
    db.commit()
    rows = client.get("/media/customers", params={"search": "Same Contact"}).json()["data"]
    assert [row["id"] for row in rows] == ["104825242721250"]


def test_super_admin_retains_explicit_all_customer_access(db, booking):
    client, user, binding, actor = booking
    role = ArkRole(name="super_admin", label="Super admin")
    db.add(role)
    db.flush()
    db.add(ArkUserRole(user_id=user.id, role_id=role.id))
    actor["roles"] = ["super_admin"]
    db.delete(binding)
    db.commit()
    rows = client.get("/media/customers", params={"search": "Tilly"}).json()["data"]
    assert {row["id"] for row in rows} == {"104825242721250", "other-customer"}
    assert submit(client, "other-customer").status_code == 200


def test_revoked_super_admin_token_cannot_submit_outside_current_owner_scope(db, booking):
    client, user, _, actor = booking
    role = ArkRole(name="super_admin", label="Super admin")
    db.add(role)
    db.flush()
    grant = ArkUserRole(user_id=user.id, role_id=role.id)
    db.add(grant)
    db.commit()
    actor["roles"] = ["super_admin"]
    assert len(client.get("/media/customers", params={"search": "Tilly"}).json()["data"]) == 2
    db.delete(grant)
    db.commit()
    rows = client.get("/media/customers", params={"search": "Tilly"}).json()["data"]
    assert [row["id"] for row in rows] == ["104825242721250"]
    assert submit(client, "other-customer").status_code == 403
    assert db.query(DesignScheduleRequest).count() == 0


def test_revoked_design_permission_rejects_submission_with_old_token(db, booking):
    client, user, _, actor = booking
    assert "design:write" in actor["permissions"]
    set_grants(db, user.id, [])
    assert client.get("/media/customers", params={"search": "Tilly"}).status_code == 403
    assert submit(client).status_code == 403
    assert db.query(DesignScheduleRequest).count() == 0
