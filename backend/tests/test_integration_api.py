"""Public external-invoice resolution and read-only validation contracts."""

from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.auth.utils import hash_token
from app.core.database import get_db
from app.integration.models import IntegrationApp, InvoiceIngestRequest
from app.integration.router import router as integration_router
from app.invoice.models import Invoice, PriceColorType, StdPrice


TOKEN = "ark_live_external_invoice_contract_token"


def _seed_catalog(db) -> None:
    db.execute(text("""
        CREATE TABLE lsordertest.okki_products (
            product_id INTEGER PRIMARY KEY,
            product_no TEXT,
            product_name TEXT,
            model TEXT,
            color TEXT,
            size TEXT,
            unit TEXT,
            disable_flag INTEGER
        )
    """))
    db.execute(text("""
        CREATE TABLE lsordertest.okki_inventory (
            product_id INTEGER,
            sku_id INTEGER,
            disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT INTO lsordertest.customer_info
            (company_id, company_name, country_name, owner_user_ids)
        VALUES
            ('C001', 'Acme Global', 'US', '[]'),
            ('C002', 'Beta Buyer', 'GB', '[]'),
            ('C003', 'Space   Name Ltd', 'CA', '[]')
    """))
    db.execute(text("""
        INSERT INTO lsordertest.customer_contacts
            (id, company_id, name, email, tel, is_main)
        VALUES
            (1, 'C001', 'Alice', 'Buyer@Example.com', '+1 (555) 010-0200', 1),
            (2, 'C002', 'Bob', 'beta@example.com', '+44 20 7946 0958', 1)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_products
            (product_id, product_no, product_name, model, color, size, unit, disable_flag)
        VALUES
            (1, 'HAIR-001', 'Canonical Hair/16/Natural/20g', 'M1', 'Natural', '16', '20g', 0),
            (2, 'ACC-002', 'Canonical Clip', 'Clip-M', 'Black', '', '', 0)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
        VALUES (1, 1001, 0), (2, 2001, 0)
    """))
    db.add(StdPrice(
        product_kind="hair",
        series_grade="Canonical Hair",
        length="16",
        weight_unit="20g",
        color_type="solid",
        price=Decimal("10.0000"),
        currency="USD",
    ))
    db.add(PriceColorType(color_code="natural", color_type="solid"))

    sample_prices = [
        "19.6700", "24.1300", "28.4500", "31.2000",
        "33.5400", "37.8600", "38.1100",
    ]
    for offset, price in enumerate(sample_prices, start=1):
        product_id = 100 + offset
        sku_id = 5000 + offset
        db.execute(text("""
            INSERT INTO lsordertest.okki_products
                (product_id, product_no, product_name, model, color, size, unit, disable_flag)
            VALUES
                (:product_id, :product_no, :product_name, :model, :color, :size, :unit, 0)
        """), {
            "product_id": product_id,
            "product_no": f"WB-{offset}",
            "product_name": f"Workbook Hair {offset}/{14 + offset}/#{offset}B/20g",
            "model": f"WB-M{offset}",
            "color": f"#{offset}B",
            "size": str(14 + offset),
            "unit": "20g",
        })
        db.execute(text("""
            INSERT INTO lsordertest.okki_inventory (product_id, sku_id, disable_flag)
            VALUES (:product_id, :sku_id, 0)
        """), {"product_id": product_id, "sku_id": sku_id})
        db.add(StdPrice(
            product_kind="hair",
            series_grade=f"Workbook Hair {offset}",
            length=str(14 + offset),
            weight_unit="20g",
            color_type="solid",
            price=Decimal(price),
            currency="USD",
        ))
    db.commit()


@pytest.fixture
def api(db):
    permission = ArkPermission(
        id=8101,
        code="invoice:write",
        module="invoice",
        action="write",
        label="Invoice write",
    )
    role = ArkRole(id=8101, name="integration_writer", label="Integration writer")
    role.permissions = [permission]
    owner = ArkUser(
        id=8101,
        username="integration-owner",
        real_name="Integration Owner",
        password_hash="test",
        roles=[role],
    )
    db.add_all([
        owner,
        IntegrationApp(
            public_id="app_invoice_contract",
            name="Invoice contract test",
            owner_user_id=owner.id,
            token_hash=hash_token(TOKEN),
            token_suffix=TOKEN[-6:],
            scopes=["invoice:write"],
        ),
    ])
    db.commit()
    _seed_catalog(db)

    app = FastAPI()
    app.include_router(integration_router, prefix="/api/integrations")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, db


def _headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _line(*, product_id: int = 1, sku_id: int = 1001) -> dict:
    return {
        "external_line_id": "line-1",
        "product_kind": "hair",
        "catalog_ref": {"product_id": product_id, "sku_id": sku_id},
        "description": {
            "product_display": "Untrusted display",
            "model": "forged-model",
            "color": "forged-color",
            "length": "99",
            "unit": "999g",
        },
        "quantity": 2,
        "unit_price": "10.0000",
        "discount_amount": "0.00",
    }


def _submission() -> dict:
    return {
        "schema_version": "1.0",
        "external_order_id": "SITE:2026-0001",
        "order_type": "stock",
        "invoice_date": "2026-08-26",
        "currency": "usd",
        "customer": {
            "ark_customer_id": "C001",
            "name": "Untrusted customer name",
            "contact": {
                "name": "Order Contact",
                "email": "order-contact@example.com",
                "phone": "+1 555 123 4567",
            },
        },
        "delivery": {"address": "Warehouse 1", "express_channel": "DHL"},
        "fees": {
            "packaging_amount": "0.00",
            "packaging_quantity": 0,
            "shipping_amount": "0.00",
            "surcharge": {"name": "Handling", "amount": "0.00"},
        },
        "items": [_line()],
        "payment_term": None,
        "remark": None,
    }


def _issue(response) -> dict:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == 422
    assert body["message"] == "invoice validation failed"
    assert body["data"]["warnings"] == []
    return body["data"]["issues"][0]


def test_submission_rejects_top_level_and_nested_unknown_fields(api):
    client, _ = api
    for field, value in (
        ("sales_user_id", 999),
        ("invoice_no", "FORGED-001"),
        ("source", "external"),
    ):
        top_level = _submission()
        top_level[field] = value
        response = client.post(
            "/api/integrations/v1/invoices/validate", json=top_level, headers=_headers(),
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"][-1] == field

    nested = _submission()
    nested["customer"]["contact"]["secret_note"] = "must be rejected"
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=nested, headers=_headers(),
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "secret_note"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("external_order_id", "bad/order"),
        ("external_order_id", "x" * 65),
        ("invoice_date", "08/26/2026"),
        ("invoice_date", "2026-02-30"),
        ("currency", "US"),
        ("currency", "US12"),
    ],
)
def test_submission_rejects_invalid_external_id_date_and_currency(api, field, value):
    client, _ = api
    payload = _submission()
    payload[field] = value
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 422


def test_submission_normalizes_currency_and_accepts_exactly_200_items(api):
    client, _ = api
    payload = _submission()
    payload["currency"] = " usd "
    payload["items"] = [{**_line(), "external_line_id": str(index)} for index in range(200)]
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["currency"] == "USD"
    assert len(response.json()["data"]["items"]) == 200


def test_submission_rejects_201_items(api):
    client, _ = api
    payload = _submission()
    payload["items"] = [{**_line(), "external_line_id": str(index)} for index in range(201)]
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [("quantity", 0), ("quantity", -1), ("unit_price", "0"), ("unit_price", "-0.01"), ("discount_amount", "0.01")],
)
def test_line_rejects_quantity_price_and_positive_discount_boundaries(api, field, value):
    client, _ = api
    payload = _submission()
    payload["items"][0][field] = value
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("fees", "packaging_amount"), "-0.01"),
        (("fees", "packaging_quantity"), -1),
        (("fees", "shipping_amount"), "-0.01"),
        (("fees", "surcharge", "amount"), "-0.01"),
    ],
)
def test_submission_rejects_negative_fees(api, path, value):
    client, _ = api
    payload = _submission()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 422


def test_discount_cannot_make_line_total_negative(api):
    client, _ = api
    payload = _submission()
    payload["items"][0]["discount_amount"] = "-20.01"
    issue = _issue(client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    ))
    assert issue == {
        "code": "DISCOUNT_EXCEEDS_LINE",
        "field": "items[0].discount_amount",
        "message": "产品行折扣不能超过该行金额",
    }


@pytest.mark.parametrize(
    ("customer", "expected_id"),
    [
        ({"ark_customer_id": "C001"}, "C001"),
        ({"contact": {"email": " buyer@example.COM "}}, "C001"),
        ({"contact": {"phone": "1-555-010-0200"}}, "C001"),
        ({"name": "  SPACE name   LTD "}, "C003"),
    ],
)
def test_customer_resolves_by_id_email_phone_or_normalized_exact_name(api, customer, expected_id):
    client, _ = api
    response = client.post(
        "/api/integrations/v1/customers/resolve", json=customer, headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["customer"]["ark_customer_id"] == expected_id


def test_customer_id_uses_canonical_company_name_and_keeps_contact_snapshot(api):
    client, _ = api
    response = client.post(
        "/api/integrations/v1/customers/resolve",
        json={
            "ark_customer_id": "C001",
            "name": "Forged Company",
            "contact": {"name": "Snapshot Person", "email": "Snapshot@Example.com"},
        },
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    customer = response.json()["data"]["customer"]
    assert customer["name"] == "Acme Global"
    assert customer["contact"] == {
        "name": "Snapshot Person", "email": "Snapshot@Example.com", "phone": None,
    }


def test_customer_not_found_and_ambiguity_have_stable_business_codes(api):
    client, db = api
    not_found = _issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"name": "Missing Buyer"},
        headers=_headers(),
    ))
    assert not_found["code"] == "CUSTOMER_NOT_FOUND"
    assert not_found["field"] == "customer"

    db.execute(text("""
        INSERT INTO lsordertest.customer_contacts (id, company_id, name, email, tel, is_main)
        VALUES (10, 'C002', 'Duplicate', 'buyer@example.com', '+1 555 999 0000', 0)
    """))
    db.commit()
    ambiguous = _issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"contact": {"email": "buyer@example.com"}},
        headers=_headers(),
    ))
    assert ambiguous["code"] == "CUSTOMER_NOT_UNIQUE"
    assert ambiguous["field"] == "customer"

    db.execute(text("""
        INSERT INTO lsordertest.customer_info
            (company_id, company_name, country_name, owner_user_ids)
        VALUES ('C004', 'Beta   Buyer', 'AU', '[]')
    """))
    db.commit()
    ambiguous_name = _issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"name": " beta buyer "},
        headers=_headers(),
    ))
    assert ambiguous_name["code"] == "CUSTOMER_NOT_UNIQUE"
    assert ambiguous_name["field"] == "customer"


def test_customer_conflicting_email_and_phone_is_not_unique(api):
    client, _ = api
    issue = _issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"contact": {"email": "buyer@example.com", "phone": "+44 20 7946 0958"}},
        headers=_headers(),
    ))
    assert issue["code"] == "CUSTOMER_NOT_UNIQUE"
    assert issue["field"] == "customer"


def test_product_resolves_valid_pair_and_overwrites_forged_catalog_text(api):
    client, _ = api
    response = client.post(
        "/api/integrations/v1/products/resolve",
        json={
            "product_kind": "hair",
            "catalog_ref": {"product_id": 1, "sku_id": 1001},
            "description": _line()["description"],
        },
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["item"]
    assert item["catalog_ref"] == {"product_id": 1, "sku_id": 1001}
    assert item["description"] == {
        "product_name": "Canonical Hair/16/Natural/20g",
        "product_display": "Canonical Hair",
        "model": "M1",
        "color": "Natural",
        "length": "16",
        "unit": "20g",
    }


def test_product_rejects_invalid_pair_and_accessory_without_catalog_ref(api):
    client, _ = api
    invalid_pair = _issue(client.post(
        "/api/integrations/v1/products/resolve",
        json={"product_kind": "hair", "catalog_ref": {"product_id": 1, "sku_id": 9999}},
        headers=_headers(),
    ))
    assert invalid_pair["code"] == "PRODUCT_NOT_FOUND"
    assert invalid_pair["field"] == "catalog_ref"

    accessory = _issue(client.post(
        "/api/integrations/v1/products/resolve",
        json={"product_kind": "accessory", "description": {"model": "Clip-M", "color": "Black"}},
        headers=_headers(),
    ))
    assert accessory["code"] == "PRODUCT_CATALOG_REQUIRED"
    assert accessory["field"] == "catalog_ref"

    incomplete_pair = client.post(
        "/api/integrations/v1/products/resolve",
        json={"product_kind": "hair", "catalog_ref": {"product_id": 1}},
        headers=_headers(),
    )
    assert incomplete_pair.status_code == 422
    assert incomplete_pair.json()["detail"][0]["loc"][-1] == "sku_id"


def test_product_resolves_unique_four_dimensions(api):
    client, _ = api
    response = client.post(
        "/api/integrations/v1/products/resolve",
        json={
            "product_kind": "hair",
            "description": {"model": "M1", "color": "Natural", "length": "16", "unit": "20g"},
        },
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["item"]["catalog_ref"] == {"product_id": 1, "sku_id": 1001}


def test_product_reports_zero_multi_product_and_multi_sku_deterministically(api):
    client, db = api
    not_found = _issue(client.post(
        "/api/integrations/v1/products/resolve",
        json={
            "product_kind": "hair",
            "description": {"model": "NOPE", "color": "Natural", "length": "16", "unit": "20g"},
        },
        headers=_headers(),
    ))
    assert not_found["code"] == "PRODUCT_NOT_FOUND"

    db.execute(text("""
        INSERT INTO lsordertest.okki_products
            (product_id, product_no, product_name, model, color, size, unit, disable_flag)
        VALUES (9, 'HAIR-009', 'Duplicate Hair', 'M1', 'Natural', '16', '20g', 0)
    """))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES (9, 9009, 0)"))
    db.commit()
    multi_product = _issue(client.post(
        "/api/integrations/v1/products/resolve",
        json={
            "product_kind": "hair",
            "description": {"model": "M1", "color": "Natural", "length": "16", "unit": "20g"},
        },
        headers=_headers(),
    ))
    assert multi_product["code"] == "PRODUCT_NOT_UNIQUE"

    db.execute(text("DELETE FROM lsordertest.okki_products WHERE product_id = 9"))
    db.execute(text("DELETE FROM lsordertest.okki_inventory WHERE product_id = 9"))
    db.execute(text("INSERT INTO lsordertest.okki_inventory VALUES (1, 1010, 0)"))
    db.commit()
    multi_sku = _issue(client.post(
        "/api/integrations/v1/products/resolve",
        json={
            "product_kind": "hair",
            "description": {"model": "M1", "color": "Natural", "length": "16", "unit": "20g"},
        },
        headers=_headers(),
    ))
    assert multi_sku["code"] == "PRODUCT_NOT_UNIQUE"


def test_invoice_multiple_lines_reports_exact_failing_item_path(api):
    client, _ = api
    payload = _submission()
    payload["items"] = [_line(), {**_line(product_id=1, sku_id=9999), "external_line_id": "line-2"}]
    issue = _issue(client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    ))
    assert issue["code"] == "PRODUCT_NOT_FOUND"
    assert issue["field"] == "items[1].catalog_ref"


def test_validate_returns_canonical_snapshots_fixed_money_and_price_warning(api):
    client, _ = api
    payload = _submission()
    payload["items"][0]["unit_price"] = "11.2500"
    payload["items"][0]["discount_amount"] = "-0.50"
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["customer"]["name"] == "Acme Global"
    assert data["items"][0]["description"]["model"] == "M1"
    assert data["items"][0]["unit_price"] == "11.2500"
    assert data["items"][0]["standard_price"] == "10.0000"
    assert data["items"][0]["customer_price"] == "10.0000"
    assert data["items"][0]["total_price"] == "22.00"
    assert data["totals"] == {"product_amount": "22.00", "total_amount": "22.00"}
    assert data["warnings"][0]["code"] == "PRICE_DIFFERS_FROM_CURRENT"


def test_declared_totals_match_or_return_field_specific_mismatch(api):
    client, _ = api
    matching = _submission()
    matching["declared_totals"] = {"product_amount": "20.01", "total_amount": "20.00"}
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=matching, headers=_headers(),
    )
    assert response.status_code == 200, response.text

    mismatch = deepcopy(matching)
    mismatch["declared_totals"]["total_amount"] = "20.02"
    issue = _issue(client.post(
        "/api/integrations/v1/invoices/validate", json=mismatch, headers=_headers(),
    ))
    assert issue["code"] == "DECLARED_TOTAL_MISMATCH"
    assert issue["field"] == "declared_totals.total_amount"


def test_seven_line_workbook_sample_recalculates_server_totals_without_writes(api):
    client, db = api
    prices = ["19.6700", "24.1300", "28.4500", "31.2000", "33.5400", "37.8600", "38.1100"]
    payload = _submission()
    payload["external_order_id"] = "GW-MT9WQKPO"
    payload["items"] = [
        {
            "external_line_id": str(index),
            "product_kind": "hair",
            "catalog_ref": {"product_id": 100 + index, "sku_id": 5000 + index},
            "description": {
                "product_display": f"Workbook row {index}",
                "model": f"WB-M{index}",
                "color": f"#{index}B",
                "length": str(14 + index),
                "unit": "20g",
            },
            "quantity": 5,
            "unit_price": price,
            "discount_amount": "0.00",
        }
        for index, price in enumerate(prices, start=1)
    ]
    payload["fees"] = {
        "packaging_amount": "0.00",
        "packaging_quantity": 0,
        "shipping_amount": "53.00",
        "surcharge": {"name": "Handling Fee", "amount": "55.89"},
    }
    payload["declared_totals"] = {"product_amount": "1064.80", "total_amount": "1173.69"}

    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["totals"] == {
        "product_amount": "1064.80", "total_amount": "1173.69",
    }
    assert db.query(Invoice).count() == 0
    assert db.query(InvoiceIngestRequest).count() == 0


def test_public_endpoints_require_site_token_and_reject_jwt(api):
    client, _ = api
    paths_and_bodies = [
        ("/api/integrations/v1/customers/resolve", {"ark_customer_id": "C001"}),
        ("/api/integrations/v1/products/resolve", {"product_kind": "hair", "catalog_ref": {"product_id": 1, "sku_id": 1001}}),
        ("/api/integrations/v1/invoices/validate", _submission()),
    ]
    for path, body in paths_and_bodies:
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, json=body, headers=_headers("jwt-user-token")).status_code == 401


def test_full_application_registers_public_phase_one_paths():
    from app.routers import register_routers

    app = FastAPI()
    register_routers(app)
    paths = {route.path for route in app.routes}
    assert {
        "/api/integrations/v1/customers/resolve",
        "/api/integrations/v1/products/resolve",
        "/api/integrations/v1/invoices/validate",
    }.issubset(paths)
