"""Customer image invitation schemas and customer-scope tests."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.auth.models import ArkPermission, ArkRole, ArkUserExternalBinding
from app.auth.service import seed_role_permissions
from app.customer_image.models import (
    CustomerImageOptionValue,
    CustomerImageProduct,
    CustomerImageProductAsset,
    CustomerImageProductOption,
)
from app.customer_image.schemas import CustomerImageInviteCreate, CustomerImageProductUpsert
from app.customer_image.service import (
    OKKI_BINDING_REQUIRED_MESSAGE,
    CustomerScopeConflictError,
    list_available_customers,
    validate_public_requirement,
    create_product,
    list_product_options,
    publish_product,
    replace_product_options,
    update_product,
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

    assert list_available_customers(db, 7, False, "Owned") == [
        {"id": "c1", "name": "Owned Customer", "country": "US", "origin": "OKKI"}
    ]


def test_salesperson_customer_list_deduplicates_inconsistent_current_snapshots(db):
    _seed_customer(db, "c1", "Owned Customer")
    _bind_okki(db, 7, "1007")
    _snapshot(db, "c1", "1007", current=True)
    _snapshot(db, "c1", "1007", current=True)
    db.flush()

    assert [row["id"] for row in list_available_customers(db, 7, False, "Owned")] == ["c1"]


def test_admin_searches_all_customers_without_okki_binding(db):
    _seed_customer(db, "c1", "Alpha Hair")
    _seed_customer(db, "c2", "Beta Hair")
    db.flush()

    rows = list_available_customers(db, 99, True, "beta")

    assert [row["id"] for row in rows] == ["c2"]


def test_invite_customer_lookup_is_exact_and_not_limited_by_autocomplete(db):
    from app.customer_image.service import _customer_for_invite

    for index in range(21):
        customer_id = f"CUST-{index:02d}"
        _seed_customer(db, customer_id, f"A Customer {index:02d}")
        _snapshot(db, customer_id, "1007")
    _seed_customer(db, "CUST", "Z Target Customer")
    _snapshot(db, "CUST", "1007")
    db.flush()

    assert _customer_for_invite(db, "CUST", 99, True) == ("Z Target Customer", "1007")


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
        list_available_customers(db, 7, False, "Customer")

    assert exc_info.value.status_code == 409
    assert str(exc_info.value) == OKKI_BINDING_REQUIRED_MESSAGE


def test_non_admin_uses_active_non_primary_binding_when_no_primary_exists(db):
    _seed_customer(db, "c1", "Owned Customer")
    _bind_okki(db, 7, "1007", is_primary=False)
    _snapshot(db, "c1", "1007")
    db.flush()

    assert [row["id"] for row in list_available_customers(db, 7, False, "Owned")] == ["c1"]


def test_non_admin_skips_invalid_primary_and_uses_first_numeric_binding(db):
    _seed_customer(db, "c1", "Fallback Customer")
    _bind_okki(db, 7, "not-numeric", is_primary=True)
    _bind_okki(db, 7, "1007", is_primary=False)
    _snapshot(db, "c1", "1007")
    db.flush()

    assert [row["id"] for row in list_available_customers(db, 7, False, "Fallback")] == ["c1"]


def test_non_admin_prefers_numeric_primary_over_other_numeric_binding(db):
    _seed_customer(db, "primary", "Primary Customer")
    _seed_customer(db, "secondary", "Secondary Customer")
    _bind_okki(db, 7, "1008", is_primary=False)
    _bind_okki(db, 7, "1007", is_primary=True)
    _snapshot(db, "primary", "1007")
    _snapshot(db, "secondary", "1008")
    db.flush()

    assert [row["id"] for row in list_available_customers(db, 7, False, "Primary")] == ["primary"]


def test_invite_create_schema_enforces_products_future_expiry_and_quota():
    now = datetime.now(UTC).replace(tzinfo=None)
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


def test_invite_create_normalizes_iso_z_expiry_to_utc_naive():
    parsed = CustomerImageInviteCreate(
        customer_id="CUST001",
        product_ids=[1],
        expires_at="2099-01-01T08:00:00Z",
        quota_total=1,
    )

    assert parsed.expires_at == datetime(2099, 1, 1, 8, 0)
    assert parsed.expires_at.tzinfo is None

    offset = parsed.model_copy(update={
        "expires_at": datetime(2099, 1, 1, 16, 0, tzinfo=timezone(timedelta(hours=8)))
    })
    reparsed = CustomerImageInviteCreate.model_validate(offset.model_dump())
    assert reparsed.expires_at == datetime(2099, 1, 1, 8, 0)


def test_public_requirement_has_hard_ceiling_of_500_characters():
    from app.customer_image.schemas import CustomerImageGenerationCreate

    CustomerImageGenerationCreate(
        product_id=1, config_version=1, request_id="r1", selections={}, requirement="x" * 500
    )
    with pytest.raises(ValidationError):
        CustomerImageGenerationCreate(
            product_id=1, config_version=1, request_id="r1", selections={}, requirement="x" * 501
        )


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


def _product_payload(**overrides):
    payload = {
        "name": "Lace Wig",
        "category": "wig",
        "description": "Product template",
        "fixed_prompt": "Keep the logo exact",
        "output_prompt": "Create a catalog image",
        "sort": 10,
        "options": [
            {
                "key": "length",
                "label": "Length",
                "control_type": "single_choice",
                "required": True,
                "default_value": "18",
                "values": [
                    {"value": "18", "label": "18 inch", "prompt_fragment": "18 inch hair"},
                    {"value": "20", "label": "20 inch", "prompt_fragment": "20 inch hair", "is_active": False},
                ],
            },
            {
                "key": "color",
                "label": "Color",
                "control_type": "color",
                "default_value": "natural",
                "values": [
                    {
                        "value": "natural",
                        "label": "Natural black",
                        "prompt_fragment": "natural black hair",
                        "color_hex": "#1A1A1A",
                    }
                ],
            },
            {
                "key": "add_logo",
                "label": "Add logo",
                "control_type": "boolean",
                "default_value": "true",
                "values": [
                    {"value": "true", "label": "Yes", "prompt_fragment": "show the logo"},
                    {"value": "false", "label": "No", "prompt_fragment": "omit the logo"},
                ],
            },
        ],
    }
    payload.update(overrides)
    return CustomerImageProductUpsert(**payload)


def test_create_product_persists_supported_options_and_filters_inactive_values(db):
    product = create_product(db, admin_id=1, payload=_product_payload())

    assert product.config_version == 1
    options = list_product_options(db, product.id)
    assert [value.value for value in options[0].values] == ["18"]


@pytest.mark.parametrize(
    "patch",
    [
        {"options": [{"key": "x", "label": "X", "control_type": "text", "values": []}]},
        {"options": [{"key": "dup", "label": "A", "control_type": "single_choice", "values": [{"value": "a", "label": "A", "prompt_fragment": "a"}]}, {"key": "dup", "label": "B", "control_type": "single_choice", "values": [{"value": "b", "label": "B", "prompt_fragment": "b"}]}]},
        {"options": [{"key": "x", "label": "X", "control_type": "single_choice", "default_value": "missing", "values": [{"value": "a", "label": "A", "prompt_fragment": "a"}]}]},
        {"options": [{"key": "x", "label": "X", "control_type": "color", "values": [{"value": "a", "label": "A", "prompt_fragment": "a", "color_hex": "red"}]}]},
        {"options": [{"key": "x", "label": "X", "control_type": "single_choice", "values": [{"value": "a", "label": "A", "prompt_fragment": " "}]}]},
        {"options": [{"key": "x", "label": "X", "control_type": "boolean", "values": [{"value": "yes", "label": "Yes", "prompt_fragment": "yes"}]}]},
    ],
)
def test_product_schema_rejects_invalid_option_contracts(patch):
    with pytest.raises(ValidationError):
        _product_payload(**patch)


def test_publish_requires_current_cover_and_reference(db):
    product = create_product(db, admin_id=1, payload=_product_payload())
    with pytest.raises(ValueError, match="cover.*reference"):
        publish_product(db, product.id)

    db.add_all([
        CustomerImageProductAsset(product_id=product.id, role="cover", storage_path="1/customer-product/c.jpg", mime_type="image/jpeg", file_size=1, width=1, height=1, sha256="a" * 64),
        CustomerImageProductAsset(product_id=product.id, role="reference", storage_path="1/customer-product/r.jpg", mime_type="image/jpeg", file_size=1, width=1, height=1, sha256="b" * 64),
    ])
    db.commit()

    published = publish_product(db, product.id)
    assert published.is_published is True


def test_product_prompt_and_option_update_increments_config_version_once(db):
    product = create_product(db, admin_id=1, payload=_product_payload())

    updated = update_product(
        db,
        product.id,
        _product_payload(fixed_prompt="Keep logo and packaging exact", options=[]),
    )

    assert updated.fixed_prompt == "Keep logo and packaging exact"
    assert updated.config_version == 2
    assert db.query(CustomerImageProductOption).filter_by(product_id=product.id).count() == 0
    assert db.query(CustomerImageOptionValue).count() == 0


def test_product_list_eager_loads_inactive_values_for_admin_only(db):
    from app.customer_image.service import list_products

    product = create_product(db, admin_id=1, payload=_product_payload())
    admin_product = list_products(db, include_inactive=True)[0]
    assert [value.value for value in admin_product.options[0].values] == ["18", "20"]

    reader_product = list_products(db, include_inactive=False)[0]
    assert [value.value for value in reader_product.options[0].values] == ["18"]
    assert admin_product.id == reader_product.id == product.id


def test_admin_read_update_round_trip_preserves_inactive_values(db):
    from app.customer_image.service import list_products

    product = create_product(db, admin_id=1, payload=_product_payload())
    loaded = list_products(db, include_inactive=True)[0]
    payload = CustomerImageProductUpsert(
        name=loaded.name,
        category=loaded.category,
        description=loaded.description,
        fixed_prompt=loaded.fixed_prompt,
        output_prompt=loaded.output_prompt,
        sort=loaded.sort,
        options=[
            {
                "key": option.key,
                "label": option.label,
                "control_type": option.control_type,
                "required": option.required,
                "default_value": option.default_value,
                "sort": option.sort,
                "values": [
                    {
                        "value": value.value,
                        "label": value.label,
                        "prompt_fragment": value.prompt_fragment,
                        "color_hex": value.color_hex,
                        "pantone_code": value.pantone_code,
                        "sort": value.sort,
                        "is_active": value.is_active,
                    }
                    for value in option.values
                ],
            }
            for option in loaded.options
        ],
    )

    update_product(db, product.id, payload)

    values = db.query(CustomerImageOptionValue).order_by(CustomerImageOptionValue.id).all()
    assert [(value.value, value.is_active) for value in values[:2]] == [("18", True), ("20", False)]
