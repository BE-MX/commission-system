"""Customer image invitation schemas and customer-scope tests."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.auth.models import ArkPermission, ArkRole, ArkUserExternalBinding
from app.auth.service import seed_role_permissions
from app.customer_image.schemas import CustomerImageInviteCreate
from app.customer_image.service import (
    OKKI_BINDING_REQUIRED_MESSAGE,
    CustomerScopeConflictError,
    list_available_customers,
    validate_public_requirement,
)
from app.models.customer import CustomerCommissionSnapshot


def _seed_customer(db, customer_id, name, country="CN", origin="OKKI"):
    db.execute(
        text(
            "INSERT INTO lsordertest.customer_info "
            "(company_id, company_name, country_name, origin_name) "
            "VALUES (:id, :name, :country, :origin)"
        ),
        {"id": customer_id, "name": name, "country": country, "origin": origin},
    )


def _bind_okki(db, user_id, external_id, **overrides):
    db.add(ArkUserExternalBinding(
        ark_user_id=user_id,
        provider="okki",
        external_account_id=external_id,
        binding_status=overrides.get("binding_status", "active"),
        is_primary=overrides.get("is_primary", True),
        deleted_at=overrides.get("deleted_at"),
    ))


def _snapshot(db, customer_id, salesperson_id, current=True):
    db.add(CustomerCommissionSnapshot(
        customer_id=customer_id,
        salesperson_id=salesperson_id,
        is_current=current,
        source="auto",
    ))


def test_salesperson_only_lists_current_owned_customers(db):
    _seed_customer(db, "c1", "Owned Customer", "US", "OKKI")
    _seed_customer(db, "c2", "Other Customer")
    _seed_customer(db, "c3", "Former Customer")
    _bind_okki(db, 7, "1007")
    _snapshot(db, "c1", "1007", current=True)
    _snapshot(db, "c2", "1008", current=True)
    _snapshot(db, "c3", "1007", current=False)
    db.flush()

    assert list_available_customers(db, 7, False, "") == [
        {"id": "c1", "name": "Owned Customer", "country": "US", "origin": "OKKI"}
    ]


def test_salesperson_customer_list_deduplicates_inconsistent_current_snapshots(db):
    _seed_customer(db, "c1", "Owned Customer")
    _bind_okki(db, 7, "1007")
    _snapshot(db, "c1", "1007", current=True)
    _snapshot(db, "c1", "1007", current=True)
    db.flush()

    assert [row["id"] for row in list_available_customers(db, 7, False, "")] == ["c1"]


def test_admin_searches_all_customers_without_okki_binding(db):
    _seed_customer(db, "c1", "Alpha Hair")
    _seed_customer(db, "c2", "Beta Hair")
    db.flush()

    rows = list_available_customers(db, 99, True, "beta")

    assert [row["id"] for row in rows] == ["c2"]


@pytest.mark.parametrize(
    ("external_id", "binding_status", "is_primary"),
    [(None, None, None), ("not-numeric", "active", True), ("1007", "inactive", True)],
)
def test_non_admin_without_active_numeric_okki_binding_gets_actionable_conflict(
    db, external_id, binding_status, is_primary
):
    if external_id is not None:
        _bind_okki(db, 7, external_id, binding_status=binding_status, is_primary=is_primary)
        db.flush()

    with pytest.raises(CustomerScopeConflictError) as exc_info:
        list_available_customers(db, 7, False, "")

    assert exc_info.value.status_code == 409
    assert str(exc_info.value) == OKKI_BINDING_REQUIRED_MESSAGE


def test_non_admin_uses_active_non_primary_binding_when_no_primary_exists(db):
    _seed_customer(db, "c1", "Owned Customer")
    _bind_okki(db, 7, "1007", is_primary=False)
    _snapshot(db, "c1", "1007")
    db.flush()

    assert [row["id"] for row in list_available_customers(db, 7, False, "")] == ["c1"]


def test_non_admin_skips_invalid_primary_and_uses_first_numeric_binding(db):
    _seed_customer(db, "c1", "Fallback Customer")
    _bind_okki(db, 7, "not-numeric", is_primary=True)
    _bind_okki(db, 7, "1007", is_primary=False)
    _snapshot(db, "c1", "1007")
    db.flush()

    assert [row["id"] for row in list_available_customers(db, 7, False, "")] == ["c1"]


def test_non_admin_prefers_numeric_primary_over_other_numeric_binding(db):
    _seed_customer(db, "primary", "Primary Customer")
    _seed_customer(db, "secondary", "Secondary Customer")
    _bind_okki(db, 7, "1008", is_primary=False)
    _bind_okki(db, 7, "1007", is_primary=True)
    _snapshot(db, "primary", "1007")
    _snapshot(db, "secondary", "1008")
    db.flush()

    assert [row["id"] for row in list_available_customers(db, 7, False, "")] == ["primary"]


def test_invite_create_schema_enforces_products_future_expiry_and_quota():
    now = datetime.now()
    valid = dict(customer_id=" CUST001 ", product_ids=[2, 1], expires_at=now + timedelta(days=1), quota_total=2)
    parsed = CustomerImageInviteCreate(**valid)
    assert parsed.customer_id == "CUST001"

    invalid_payloads = [
        {**valid, "customer_id": " "},
        {**valid, "product_ids": []},
        {**valid, "product_ids": [1, 1]},
        {**valid, "expires_at": now - timedelta(seconds=1)},
        {**valid, "quota_total": 0},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            CustomerImageInviteCreate(**payload)


def test_public_requirement_has_hard_ceiling_of_500_characters():
    from app.customer_image.schemas import CustomerImageGenerationCreate

    CustomerImageGenerationCreate(product_id=1, request_id="r1", selections={}, requirement="x" * 500)
    with pytest.raises(ValidationError):
        CustomerImageGenerationCreate(product_id=1, request_id="r1", selections={}, requirement="x" * 501)


def test_public_requirement_also_respects_runtime_setting():
    class Settings:
        CUSTOMER_IMAGE_MAX_REQUIREMENT_CHARS = 12

    assert validate_public_requirement(" x ", Settings()) == "x"
    with pytest.raises(ValueError, match="需求说明不能超过 12 字"):
        validate_public_requirement("x" * 13, Settings())


def test_customer_image_permission_seed_is_idempotent_with_stable_metadata(db):
    db.add(ArkRole(name="admin", label="Admin", is_system=True))
    db.commit()

    seed_role_permissions(db)
    seed_role_permissions(db)

    rows = db.query(ArkPermission).filter(ArkPermission.code.like("customer_image:%")).all()
    assert {(row.code, row.module, row.action, row.kind) for row in rows} == {
        ("customer_image:read", "customer_image", "read", "page"),
        ("customer_image:write", "customer_image", "write", "action"),
        ("customer_image:admin", "customer_image", "admin", "action"),
    }
