"""Sales scopes are independent from action grants and enforced beyond lists."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import ArkPermission, ArkRole, ArkRolePermission, ArkUserExternalBinding
from app.auth.service import seed_role_permissions
from app.core.database import get_db
from app.customer_media import service
from app.customer_media.router import router
from app.models.customer import CustomerCommissionSnapshot
from tests.customer_media_support import set_grants
from tests.test_customer_media import _add_customer, _seed_workflow, _payload


@pytest.fixture
def scope_data(db):
    owner, other, request, task = _seed_workflow(db)
    batch = service.get_or_create_batch(db, task.id, _payload(other, "customer_media:write"))
    batch.status = "pending_review"
    for customer_id, salesperson in [("CUST-MEDIA-1", "1007"), ("CUST-MEDIA-2", "1008")]:
        _add_customer(db, customer_id, customer_id)
        db.add(CustomerCommissionSnapshot(customer_id=customer_id, salesperson_id=salesperson, is_current=True, source="auto"))
        service.create_portal_account(db, _payload(owner, "customer_media:admin", "customer_media_account:read_all"), customer_id, f"{customer_id}@example.com", "TestPassword123")
    db.add_all([
        ArkUserExternalBinding(ark_user_id=owner.id, provider="okki", external_account_id="1007", binding_status="active", is_primary=True),
        ArkUserExternalBinding(ark_user_id=other.id, provider="okki", external_account_id="1008", binding_status="active", is_primary=True),
    ])
    db.commit()
    return owner, other, batch


@pytest.mark.parametrize("extra", [None, "customer_media:admin", "customer_media:read_all", "customer_media_portal:read_all", "customer_media_account:read_all"])
def test_three_read_all_scopes_are_independent(db, scope_data, extra):
    owner, other, batch = scope_data
    actor = _payload(other, "customer_media:read", "customer_media_portal:read", "customer_media_account:read", *([extra] if extra else []))
    reviews = service.list_reviews(db, actor)
    assert [r.id for r in reviews] == ([batch.id] if extra == "customer_media:read_all" else [])
    portals = service.list_sales_portal_customers(db, actor)
    assert {r["customer_id"] for r in portals} == ({"CUST-MEDIA-1", "CUST-MEDIA-2"} if extra == "customer_media_portal:read_all" else {"CUST-MEDIA-2"})
    accounts = service.list_portal_accounts(db, actor)
    assert {r.customer_id for r in accounts} == ({"CUST-MEDIA-1", "CUST-MEDIA-2"} if extra == "customer_media_account:read_all" else {"CUST-MEDIA-2"})
    assert service.list_reviews(db, _payload(owner, "customer_media:read"))[0].id == batch.id


def test_view_all_reviews_does_not_grant_review_or_tag_mutation(db, scope_data):
    owner, other, batch = scope_data
    actor = _payload(other, "customer_media:read", "customer_media:read_all")
    assert service.authorize_batch_reader(db, actor, batch.id).id == batch.id
    for action in ("approve", "request_changes"):
        with pytest.raises(service.CustomerMediaForbidden):
            service.review_batch(db, batch.id, actor, action, "review", batch.lock_version)
    with pytest.raises(service.CustomerMediaForbidden):
        service.update_asset_tags(db, batch.id, 123, actor, [])
    with pytest.raises(service.CustomerMediaForbidden):
        service.authorize_batch_reviewer(db, actor, batch.id)
    with pytest.raises(service.CustomerMediaNotFound):
        service.authorize_batch_reader(db, _payload(other, "customer_media:admin"), batch.id)


def test_account_id_and_creation_are_scoped_and_transfer_takes_effect(db, scope_data):
    owner, other, batch = scope_data
    actor = _payload(other, "customer_media:admin")
    own = service.list_portal_accounts(db, actor)[0]
    foreign = service.list_portal_accounts(db, _payload(owner, "customer_media:admin"))[0]
    assert [r["id"] for r in service.list_account_customers(db, actor, "CUST")] == [own.customer_id]
    assert service.list_portal_accounts(db, actor, foreign.login_email) == []
    with pytest.raises(service.CustomerMediaNotFound):
        service.update_portal_account(db, actor, foreign.id, password="NewPassword123")
    with pytest.raises(service.CustomerMediaForbidden):
        service.create_portal_account(db, actor, foreign.customer_id, "new@example.com", "NewPassword123")
    with pytest.raises(service.CustomerMediaNotFound):
        service.sales_portal_customer_detail(db, actor, foreign.customer_id)
    service.update_portal_account(db, actor, own.id, active=False)
    current = db.query(CustomerCommissionSnapshot).filter_by(customer_id=own.customer_id, is_current=True).one()
    current.is_current = False
    db.add(CustomerCommissionSnapshot(customer_id=own.customer_id, salesperson_id="1007", is_current=True, source="auto"))
    db.commit()
    assert service.list_portal_accounts(db, actor) == []
    assert service.list_sales_portal_customers(db, actor) == []
    with pytest.raises(service.CustomerMediaNotFound):
        service.update_portal_account(db, actor, own.id, active=True)


def test_missing_binding_fails_closed_but_super_admin_can_read(db, scope_data):
    owner, other, batch = scope_data
    db.query(ArkUserExternalBinding).filter_by(ark_user_id=other.id).delete()
    db.commit()
    for method in (service.list_portal_accounts, service.list_sales_portal_customers):
        with pytest.raises(service.CustomerMediaConflict, match="绑定 OKKI"):
            method(db, _payload(other, "customer_media:admin"))
        assert len(method(db, {**_payload(other), "roles": ["super_admin"]})) == 2


def test_http_uses_live_grants_and_revocation_not_stale_jwt(db, scope_data):
    owner, other, batch = scope_data
    stale = _payload(other, "customer_media:admin", "customer_media:read_all", "customer_media_portal:read_all", "customer_media_account:read_all")
    app = FastAPI()
    app.include_router(router, prefix="/media")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: stale
    reads = ["customer_media:read", "customer_media_portal:read", "customer_media_account:read"]
    set_grants(db, other.id, reads + ["customer_media:read_all", "customer_media_account:read_all"])
    with TestClient(app) as client:
        reviews = client.get("/media/reviews").json()["data"]
        assert reviews[0]["can_review"] is False
        assert client.get(f"/media/batches/{batch.id}/customer-tags").status_code == 200
        assert client.post(f"/media/batches/{batch.id}/review", json={"action": "approve", "lock_version": batch.lock_version}).status_code == 403
        assert len(client.get("/media/portal-accounts").json()["data"]) == 2
        assert client.patch("/media/portal-accounts/1", json={"is_active": False}).status_code == 403
        set_grants(db, other.id, reads)
        assert client.get("/media/reviews").json()["data"] == []
        assert client.get(f"/media/batches/{batch.id}/customer-tags").status_code == 404
        assert len(client.get("/media/portal-accounts").json()["data"]) == 1
        assert client.get("/media/sales-portal/customers/CUST-MEDIA-1").status_code == 404
        set_grants(db, other.id, ["customer_media:read_all", "customer_media_account:read_all"])
        for path in ("reviews", "portal-accounts", "sales-portal/customers"):
            assert client.get(f"/media/{path}").status_code == 403


def test_seed_registers_page_and_independent_data_permissions(db):
    seed_role_permissions(db)
    kinds = {p.code: p.kind for p in db.query(ArkPermission).all()}
    assert kinds["customer_media_account:read"] == "page"
    for code in ("customer_media:read_all", "customer_media_portal:read_all", "customer_media_account:read_all"):
        assert kinds[code] == "data"


def test_admin_read_all_revocation_survives_seed(db):
    admin = ArkRole(name="admin", label="Admin")
    db.add(admin)
    db.commit()
    seed_role_permissions(db)
    codes = ["customer_media:read_all", "customer_media_portal:read_all", "customer_media_account:read_all"]
    permissions = db.query(ArkPermission).filter(ArkPermission.code.in_(codes)).all()
    for permission in permissions:
        assert db.query(ArkRolePermission).filter_by(role_id=admin.id, permission_id=permission.id).count() == 0
        db.add(ArkRolePermission(role_id=admin.id, permission_id=permission.id))
    db.commit()
    db.query(ArkRolePermission).filter(ArkRolePermission.role_id == admin.id, ArkRolePermission.permission_id.in_([p.id for p in permissions])).delete()
    db.commit()
    seed_role_permissions(db)
    for permission in permissions:
        assert db.query(ArkRolePermission).filter_by(role_id=admin.id, permission_id=permission.id).count() == 0


def test_admin_cannot_bypass_scope_via_task_or_booking_tags(db, scope_data):
    owner, other, batch = scope_data
    # Assigned designers retain their legitimate task access; remove the assignment here.
    other.email = "different@example.com"
    db.commit()
    actor = _payload(other, "customer_media:admin")
    with pytest.raises(service.CustomerMediaForbidden):
        service.get_or_create_batch(db, batch.task_id, actor)
    with pytest.raises(service.CustomerMediaForbidden):
        service.validate_customer_access(db, actor, batch.customer_id)
    assert [row["id"] for row in service.list_customers(db, actor, "CUST")] == ["CUST-MEDIA-2"]
    assert service.get_or_create_batch(db, batch.task_id, _payload(owner, "customer_media:admin")).id == batch.id
    assert service.get_or_create_batch(db, batch.task_id, _payload(other, "customer_media:admin", "customer_media:read_all")).id == batch.id


def test_account_read_only_permission_reaches_navigation_without_other_pages(db, scope_data):
    from fastapi import HTTPException
    from app.system.navigation_access import validate_additions
    owner, other, batch = scope_data
    set_grants(db, other.id, ["customer_media_account:read"])
    validate_additions(db, other.id, [], ["CustomerMediaAccounts"])
    for key in ("CustomerMediaReview", "CustomerMediaPortalPreview"):
        with pytest.raises(HTTPException) as exc:
            validate_additions(db, other.id, [], [key])
        assert exc.value.status_code == 403


def test_cross_owner_admin_actions_require_matching_scope(db, scope_data):
    owner, other, batch = scope_data
    batch.status = "published"
    db.commit()
    with pytest.raises(service.CustomerMediaForbidden):
        service.unpublish_batch(db, batch.id, _payload(other, "customer_media:admin"), None)
    assert service.unpublish_batch(db, batch.id, _payload(other, "customer_media:admin", "customer_media:read_all"), None).status == "unpublished"
    account = service.list_portal_accounts(db, _payload(owner, "customer_media_account:read"))[0]
    updated = service.update_portal_account(db, _payload(other, "customer_media:admin", "customer_media_account:read_all"), account.id, active=False)
    assert updated.is_active is False


def test_account_customer_search_preserves_contact_matching_and_country(db, scope_data):
    owner, other, batch = scope_data
    db.connection().exec_driver_sql("INSERT INTO lsordertest.customer_contacts (company_id, name) VALUES ('CUST-MEDIA-1', 'Shared contact'), ('CUST-MEDIA-2', 'Shared contact')")
    db.connection().exec_driver_sql("UPDATE lsordertest.customer_info SET country_name = 'US' WHERE company_id = 'CUST-MEDIA-2'")
    db.commit()
    rows = service.list_account_customers(db, _payload(other, "customer_media:admin"), "Shared contact")
    assert [(row["id"], row["country"]) for row in rows] == [("CUST-MEDIA-2", "US")]


def test_admin_customer_tag_delete_checks_affected_tasks(db):
    from tests.test_customer_media_tags import _make_dim, _seed_batch_with_asset
    from app.customer_media.models import CustomerMediaAssetTag
    dim, values = _make_dim(db, "scope", "Scope", values=["Photo"])
    owner, designer, outsider, batch, asset = _seed_batch_with_asset(db)
    db.add(CustomerMediaAssetTag(asset_id=asset.id, dimension_id=dim.id, tag_value_id=values[0].id))
    db.commit()
    with pytest.raises(service.CustomerMediaForbidden):
        service.delete_customer_tag_value(db, batch.customer_id, values[0].id, _payload(outsider, "customer_media:admin"), confirm_associated=True, task_id=batch.task_id)
    assert service.customer_tag_asset_count(db, batch.customer_id, values[0].id) == 1
