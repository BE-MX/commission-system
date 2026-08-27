"""Public external-invoice resolution and read-only validation contracts."""

from copy import deepcopy
from decimal import Decimal
import json
import logging
import threading

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.auth.models import ArkPermission, ArkRole, ArkUser
from app.auth.utils import create_access_token, hash_token
from app.core.database import Base, get_db
from app.integration import service as integration_service
from app.integration.auth import SubmissionPrincipal
from app.integration.models import IntegrationApp, InvoiceIngestRequest
from app.integration.router import router as integration_router
from app.integration.schemas import InvoiceSubmission
from app.invoice.models import (
    CustomerPriceRule,
    Invoice,
    InvoiceItem,
    InvoiceSyncLog,
    PriceColorType,
    StdPrice,
)


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
        CREATE TABLE lsordertest.okki_product_skus (
            product_id INTEGER,
            sku_id INTEGER,
            disable_flag INTEGER
        )
    """))
    db.execute(text("""
        INSERT INTO lsordertest.customer_info
            (company_id, company_name, country_name, owner_user_ids)
        VALUES
            (1001, 'Acme Global', 'US', '[]'),
            (1002, 'Beta Buyer', 'GB', '[]'),
            (1003, 'Space   Name Ltd', 'CA', '[]')
    """))
    db.execute(text("""
        INSERT INTO lsordertest.customer_contacts
            (id, company_id, name, email, tel, is_main)
        VALUES
            (1, 1001, 'Alice', 'Buyer@Example.com', '+1 (555) 010-0200', 1),
            (2, 1002, 'Bob', 'beta@example.com', '+44 20 7946 0958', 1)
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
        VALUES (1, 1001, 0)
    """))
    db.execute(text("""
        INSERT INTO lsordertest.okki_product_skus (product_id, sku_id, disable_flag)
        VALUES (2, 2001, 0)
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


def _accessory_line() -> dict:
    return {
        "external_line_id": "accessory-1",
        "product_kind": "accessory",
        "catalog_ref": {"product_id": 2, "sku_id": 2001},
        "description": {"product_display": "forged", "model": "forged", "color": "forged"},
        "quantity": 2,
        "unit_price": "5.0000",
        "discount_amount": "0.00",
    }


def _seed_accessory_price(db, *, currency: str = "USD") -> None:
    db.add(StdPrice(
        product_kind="accessory",
        product_id=2,
        sku_id=2001,
        accessory_name="Canonical Clip",
        accessory_model="Clip-M",
        accessory_color="Black",
        price=Decimal("4.5000"),
        currency=currency,
    ))
    db.commit()


def _submission() -> dict:
    return {
        "schema_version": "1.0",
        "external_order_id": "SITE:2026-0001",
        "order_type": "stock",
        "invoice_date": "2026-08-26",
        "currency": "usd",
        "customer": {
            "ark_customer_id": "1001",
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


def _schema_issue(response) -> dict:
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == 422
    assert body["message"] == "invoice validation failed"
    assert body["data"]["warnings"] == []
    assert "detail" not in body
    issue = body["data"]["issues"][0]
    assert issue["code"] == "SCHEMA_INVALID"
    assert set(issue) == {"code", "field", "message"}
    return issue


def _assert_external_error(response, status_code: int, error_code: str) -> dict:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert body["code"] == status_code
    assert set(body) == {"code", "message", "data"}
    assert body["data"]["error_code"] == error_code
    assert body["data"]["action"]
    assert "detail" not in body
    return body


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
        issue = _schema_issue(response)
        assert issue["field"] == field

    nested = _submission()
    nested["customer"]["contact"]["secret_note"] = "must be rejected"
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=nested, headers=_headers(),
    )
    issue = _schema_issue(response)
    assert issue["field"] == "customer.contact.secret_note"


def test_schema_error_paths_cover_nested_type_and_boundary_failures(api):
    client, _ = api
    cases = [
        (("items", 0, "quantity"), True, "items[0].quantity"),
        (("items", 0, "unit_price"), "0.0000", "items[0].unit_price"),
        (("fees", "surcharge", "amount"), "-0.01", "fees.surcharge.amount"),
    ]
    for path, value, expected_field in cases:
        payload = _submission()
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        issue = _schema_issue(client.post(
            "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
        ))
        assert issue["field"] == expected_field


def test_customer_and_product_resolvers_use_the_same_schema_error_envelope(api):
    client, _ = api
    customer_issue = _schema_issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"contact": {"unknown": "must not leak"}},
        headers=_headers(),
    ))
    assert customer_issue["field"] == "contact.unknown"

    product_issue = _schema_issue(client.post(
        "/api/integrations/v1/products/resolve",
        json={"product_kind": "hair", "catalog_ref": {"product_id": 1}},
        headers=_headers(),
    ))
    assert product_issue["field"] == "catalog_ref.sku_id"


def test_schema_error_messages_are_stable_actionable_chinese(api):
    client, _ = api
    cases = []

    unknown = _submission()
    unknown["customer"]["contact"]["unknown"] = "must not leak"
    cases.append((unknown, "接口不接受该字段，请删除后重试"))

    missing = _submission()
    missing.pop("external_order_id")
    cases.append((missing, "必填字段缺失，请补充该字段"))

    boundary = _submission()
    boundary["items"][0]["quantity"] = 0
    cases.append((boundary, "数值必须大于接口规定的下限"))

    wrong_money_type = _submission()
    wrong_money_type["items"][0]["unit_price"] = 10.0
    cases.append((wrong_money_type, "金额必须使用 JSON 十进制字符串"))

    for payload, expected_message in cases:
        issue = _schema_issue(client.post(
            "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
        ))
        assert issue["message"] == expected_message
        assert not any(
            english in issue["message"]
            for english in ("Field required", "Extra inputs", "Input should", "Value error")
        )


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
    ("field", "value"),
    [
        ("unit_price", "1e1000"),
        ("unit_price", "10.00001"),
        ("discount_amount", "-0.001"),
    ],
)
def test_line_rejects_amounts_outside_internal_decimal_precision(api, field, value):
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
        (("items", 0, "unit_price"), 10.0),
        (("items", 0, "unit_price"), True),
        (("items", 0, "discount_amount"), -1),
        (("fees", "packaging_amount"), 1.25),
        (("fees", "shipping_amount"), 1),
        (("fees", "surcharge", "amount"), 1.5),
        (("declared_totals", "product_amount"), 20.0),
        (("declared_totals", "total_amount"), 20),
    ],
)
def test_money_fields_reject_json_numbers_and_booleans(api, path, value):
    client, _ = api
    payload = _submission()
    payload["declared_totals"] = {"product_amount": "20.00", "total_amount": "20.00"}
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    issue = _schema_issue(client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    ))
    expected = "".join(
        f"[{part}]" if isinstance(part, int) else (("." if index else "") + part)
        for index, part in enumerate(path)
    )
    assert issue["field"] == expected


def test_money_fields_accept_decimal_strings_and_omitted_defaults(api):
    client, _ = api
    payload = _submission()
    payload["items"][0]["unit_price"] = "10.0000"
    payload["items"][0]["discount_amount"] = "-0.00"
    payload["fees"] = {
        "packaging_amount": "0.00",
        "packaging_quantity": 0,
        "shipping_amount": "0.00",
        "surcharge": {"amount": "0.00"},
    }
    payload["declared_totals"] = {"product_amount": "20.00", "total_amount": "20.00"}
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 200, response.text

    omitted_defaults = _submission()
    omitted_defaults.pop("fees")
    omitted_defaults["items"][0].pop("discount_amount")
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=omitted_defaults, headers=_headers(),
    )
    assert response.status_code == 200, response.text


def test_line_rejects_calculated_total_outside_invoice_money_capacity(api):
    client, _ = api
    payload = _submission()
    payload["items"][0]["quantity"] = 2_000_000_000
    payload["items"][0]["unit_price"] = "99999999.9999"
    issue = _issue(client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    ))
    assert issue["code"] == "AMOUNT_OUT_OF_RANGE"
    assert issue["field"] == "items[0].total_price"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("items", 0, "quantity"), True),
        (("items", 0, "quantity"), 1.0),
        (("items", 0, "catalog_ref", "product_id"), True),
        (("fees", "packaging_quantity"), True),
    ],
)
def test_integer_contract_rejects_booleans_and_floats(api, path, value):
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
        ({"ark_customer_id": "1001"}, "1001"),
        ({"contact": {"email": " buyer@example.COM "}}, "1001"),
        ({"contact": {"phone": "1-555-010-0200"}}, "1001"),
        ({"name": "  SPACE name   LTD "}, "1003"),
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
            "ark_customer_id": "1001",
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


def test_customer_resolution_returns_one_canonical_customer_without_candidates(api):
    client, _ = api
    response = client.post(
        "/api/integrations/v1/customers/resolve",
        json={"name": "Acme Global"},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert set(data) == {"customer"}
    assert data["customer"] == {
        "ark_customer_id": "1001",
        "name": "Acme Global",
        "country_name": "US",
        "contact": {"name": None, "email": None, "phone": None},
    }


def test_customer_id_lookup_binds_numeric_id_without_casting_indexed_column(api):
    client, db = api
    statements: list[tuple[str, object]] = []

    def capture_statement(_conn, _cursor, statement, parameters, _context, _executemany):
        statements.append((statement, parameters))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = client.post(
            "/api/integrations/v1/customers/resolve",
            json={"ark_customer_id": "1001"},
            headers=_headers(),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)
    assert response.status_code == 200, response.text
    customer_queries = [(sql, params) for sql, params in statements if "customer_info" in sql]
    assert customer_queries
    sql, params = customer_queries[0]
    assert "CAST" not in sql.upper()
    assert "ci.company_id =" in sql
    assert "LIMIT 1" in sql
    assert params == (1001,)


def test_customer_lookup_queries_are_database_bounded_and_do_not_select_contact_pii(api):
    client, db = api
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        assert client.post(
            "/api/integrations/v1/customers/resolve",
            json={"contact": {"email": " buyer@example.COM "}},
            headers=_headers(),
        ).status_code == 200
        assert client.post(
            "/api/integrations/v1/customers/resolve",
            json={"contact": {"phone": "1-555-010-0200"}},
            headers=_headers(),
        ).status_code == 200
        assert client.post(
            "/api/integrations/v1/customers/resolve",
            json={"name": "  SPACE name   LTD "},
            headers=_headers(),
        ).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    contact_queries = [sql for sql in statements if "customer_contacts" in sql]
    assert contact_queries
    assert all("LIMIT 2" in sql for sql in contact_queries)
    for sql in contact_queries:
        projection = sql.upper().split("FROM", 1)[0]
        assert "CC.EMAIL" not in projection
        assert "CC.TEL" not in projection

    name_queries = [
        sql for sql in statements
        if "customer_info" in sql and "company_name" in sql.split("WHERE", 1)[-1]
    ]
    assert name_queries
    assert all("LIMIT 2" in sql for sql in name_queries)


def test_customer_id_rejects_non_numeric_external_values(api):
    client, _ = api
    issue = _schema_issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"ark_customer_id": "1001junk"},
        headers=_headers(),
    ))
    assert issue["field"] == "ark_customer_id"


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
        VALUES (10, 1002, 'Duplicate', 'buyer@example.com', '+1 555 999 0000', 0)
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
        VALUES (1004, 'Beta Buyer', 'AU', '[]')
    """))
    db.commit()
    ambiguous_name = _issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"name": " beta buyer "},
        headers=_headers(),
    ))
    assert ambiguous_name["code"] == "CUSTOMER_NOT_UNIQUE"
    assert ambiguous_name["field"] == "customer"


def test_customer_phone_raw_and_normalized_matches_are_both_considered(api):
    client, db = api
    db.execute(text("""
        INSERT INTO lsordertest.customer_contacts (id, company_id, name, email, tel, is_main)
        VALUES (10, 1002, 'Digits duplicate', NULL, '15550100200', 0)
    """))
    db.commit()

    issue = _issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"contact": {"phone": "+1 (555) 010-0200"}},
        headers=_headers(),
    ))
    assert issue["code"] == "CUSTOMER_NOT_UNIQUE"
    assert issue["field"] == "customer"


def test_customer_name_collapses_database_whitespace_before_ambiguity_check(api):
    client, db = api
    db.execute(text("""
        INSERT INTO lsordertest.customer_info
            (company_id, company_name, country_name, owner_user_ids)
        VALUES
            (1004, 'Whitespace   Collision', 'US', '[]'),
            (1005, 'Whitespace\tCollision', 'GB', '[]')
    """))
    db.commit()

    issue = _issue(client.post(
        "/api/integrations/v1/customers/resolve",
        json={"name": "  whitespace collision  "},
        headers=_headers(),
    ))
    assert issue["code"] == "CUSTOMER_NOT_UNIQUE"
    assert issue["field"] == "customer"


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


def test_accessory_resolves_only_from_active_accessory_sku_catalog(api):
    client, _ = api
    response = client.post(
        "/api/integrations/v1/products/resolve",
        json={
            "product_kind": "accessory",
            "catalog_ref": {"product_id": 2, "sku_id": 2001},
            "description": {"product_display": "forged", "model": "forged", "color": "forged"},
        },
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["item"]
    assert item["catalog_ref"] == {"product_id": 2, "sku_id": 2001}
    assert item["description"] == {
        "product_name": "Canonical Clip",
        "product_display": "Canonical Clip",
        "model": "Clip-M",
        "color": "Black",
        "length": "",
        "unit": "",
    }

    wrong_catalog = _issue(client.post(
        "/api/integrations/v1/products/resolve",
        json={"product_kind": "accessory", "catalog_ref": {"product_id": 1, "sku_id": 1001}},
        headers=_headers(),
    ))
    assert wrong_catalog["code"] == "PRODUCT_NOT_FOUND"


def test_invoice_validation_rejects_accessory_without_configured_price(api):
    client, _ = api
    payload = _submission()
    payload["items"] = [_accessory_line()]
    issue = _issue(client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    ))
    assert issue["code"] == "ACCESSORY_PRICE_NOT_CONFIGURED"
    assert issue["field"] == "items[0].catalog_ref"


def test_invoice_validation_rejects_accessory_price_currency_mismatch(api):
    client, db = api
    _seed_accessory_price(db, currency="USD")
    payload = _submission()
    payload["currency"] = "EUR"
    payload["items"] = [_accessory_line()]
    issue = _issue(client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    ))
    assert issue["code"] == "ACCESSORY_PRICE_NOT_CONFIGURED"
    assert issue["field"] == "items[0].catalog_ref"


def test_invoice_validation_uses_configured_accessory_price_and_canonical_snapshot(api):
    client, db = api
    _seed_accessory_price(db)
    payload = _submission()
    payload["items"] = [_accessory_line()]
    response = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    assert response.status_code == 200, response.text
    item = response.json()["data"]["items"][0]
    assert item["description"]["product_name"] == "Canonical Clip"
    assert item["standard_price"] == "4.5000"
    assert item["customer_price"] == "4.5000"
    assert item["unit_price"] == "5.0000"
    assert response.json()["data"]["warnings"][0]["code"] == "PRICE_DIFFERS_FROM_CURRENT"


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
    issue = _schema_issue(incomplete_pair)
    assert issue["field"] == "catalog_ref.sku_id"


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


def test_seven_line_workbook_sample_recalculates_without_business_record_writes(api):
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
    # Integration-token last_used_at telemetry is allowed; validation must not
    # create invoice-domain business records.
    assert db.query(Invoice).count() == 0
    assert db.query(InvoiceIngestRequest).count() == 0


def test_public_endpoints_require_site_token_and_reject_jwt(api):
    client, _ = api
    paths_and_bodies = [
        ("/api/integrations/v1/customers/resolve", {"ark_customer_id": "1001"}),
        ("/api/integrations/v1/products/resolve", {"product_kind": "hair", "catalog_ref": {"product_id": 1, "sku_id": 1001}}),
        ("/api/integrations/v1/invoices/validate", _submission()),
    ]
    for path, body in paths_and_bodies:
        for headers in ({}, _headers("jwt-user-token")):
            response = client.post(path, json=body, headers=headers)
            error = _assert_external_error(
                response, 401, "AUTHENTICATION_FAILED",
            )
            assert error["data"]["field"] == "authorization"
            assert "Token" in error["data"]["action"]
            assert response.headers["www-authenticate"] == "Bearer"
            assert "jwt-user-token" not in response.text


def test_public_auth_disabled_app_and_revoked_scope_use_stable_safe_envelopes(api):
    client, db = api
    app_row = db.query(IntegrationApp).filter_by(public_id="app_invoice_contract").one()
    app_row.is_active = False
    db.commit()
    disabled = client.post(
        "/api/integrations/v1/invoices/validate",
        json=_submission(),
        headers=_headers(),
    )
    _assert_external_error(disabled, 401, "AUTHENTICATION_FAILED")
    assert TOKEN not in disabled.text

    app_row.is_active = True
    app_row.scopes = []
    db.commit()
    revoked_scope = client.post(
        "/api/integrations/v1/invoices/validate",
        json=_submission(),
        headers=_headers(),
    )
    error = _assert_external_error(
        revoked_scope, 403, "INTEGRATION_PERMISSION_DENIED",
    )
    assert error["data"]["field"] == "authorization"
    assert "权限" in error["data"]["action"]
    assert TOKEN not in revoked_scope.text


def test_public_auth_revoked_owner_permission_uses_same_403_envelope(api):
    client, db = api
    owner = db.get(ArkUser, 8101)
    owner.roles[0].permissions = []
    db.commit()
    response = client.post(
        "/api/integrations/v1/invoices/validate",
        json=_submission(),
        headers=_headers(),
    )
    _assert_external_error(response, 403, "INTEGRATION_PERMISSION_DENIED")
    assert TOKEN not in response.text


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

    openapi = app.openapi()
    success_models = {
        "/api/integrations/v1/customers/resolve": "CustomerResolveSuccessEnvelope",
        "/api/integrations/v1/products/resolve": "ProductResolveSuccessEnvelope",
        "/api/integrations/v1/invoices/validate": "InvoiceValidationSuccessEnvelope",
    }
    for path, success_model in success_models.items():
        operation = openapi["paths"][path]["post"]
        success_schema = operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert success_schema["$ref"].endswith(f"/{success_model}")
        response_schema = openapi["paths"][path]["post"]["responses"]["422"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema["$ref"].endswith("/InvoiceValidationErrorEnvelope")

    schemas = openapi["components"]["schemas"]
    assert schemas["InvoiceValidationLine"]["properties"]["unit_price"]["type"] == "string"
    assert schemas["InvoiceValidationFees"]["properties"]["shipping_amount"]["type"] == "string"
    assert schemas["InvoiceValidationTotals"]["properties"]["total_amount"]["type"] == "string"
    assert (
        openapi["paths"]["/api/integrations/v1/invoices/validate"]["post"]["summary"]
        == "Validate without creating invoice/ingest records"
    )


def test_create_invoice_is_atomic_external_provenance_and_never_pushes_okki(api, monkeypatch):
    client, db = api
    from app.invoice import okki_client, xiaoman_service

    calls = []
    monkeypatch.setattr(xiaoman_service, "sync_invoice", lambda *args, **kwargs: calls.append("sync"))
    monkeypatch.setattr(okki_client, "push_order", lambda *args, **kwargs: calls.append("push"))

    response = client.post(
        "/api/integrations/v1/invoices",
        json=_submission(),
        headers=_headers(),
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "code": 201,
        "message": "invoice created",
        "data": {
            "request_id": response.json()["data"]["request_id"],
            "replayed": False,
            "external_order_id": "SITE:2026-0001",
            "invoice_id": response.json()["data"]["invoice_id"],
            "invoice_no": response.json()["data"]["invoice_no"],
            "status": "ready",
            "sync_status": "not_synced",
            "totals": {"product_amount": "20.00", "total_amount": "20.00"},
            "review_url": "https://leshine.work/invoice/manage",
        },
    }
    request_row = db.query(InvoiceIngestRequest).one()
    invoice = db.query(Invoice).one()
    assert request_row.status == "created"
    assert request_row.invoice_id == invoice.id
    assert request_row.attempt_count == 1
    assert invoice.source_type == "external_api"
    assert invoice.source_order_id == request_row.public_id
    assert invoice.source_order_name == "SITE:2026-0001"
    assert invoice.source_order_no is None
    assert invoice.source_image_sha256 is None
    assert invoice.sync_status == "not_synced"
    assert invoice.xiaoman_order_id is None
    assert invoice.xiaoman_order_no is None
    assert db.query(InvoiceSyncLog).count() == 0
    assert calls == []


def test_external_invoice_cannot_be_deleted_and_remains_replayable(api):
    client, db = api
    from app.invoice import service as invoice_service

    created = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    assert created.status_code == 201, created.text
    invoice = invoice_service.get_invoice(db, created.json()["data"]["invoice_id"])

    with pytest.raises(ValueError, match="站点接入"):
        invoice_service.delete_invoice(db, invoice)

    replay = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    lookup = client.get(
        "/api/integrations/v1/invoices/by-external-id/SITE%3A2026-0001",
        headers=_headers(),
    )
    assert replay.status_code == 200, replay.text
    assert lookup.status_code == 200, lookup.text
    assert replay.json()["data"]["invoice_id"] == created.json()["data"]["invoice_id"]
    assert lookup.json()["data"]["invoice_id"] == created.json()["data"]["invoice_id"]
    assert db.query(InvoiceIngestRequest).one().status == "created"


def test_create_schema_failure_uses_stable_422_without_ingest(api):
    client, db = api
    payload = _submission()
    payload["sales_user_id"] = 999
    response = client.post(
        "/api/integrations/v1/invoices", json=payload, headers=_headers(),
    )
    issue = _schema_issue(response)
    assert issue["field"] == "sales_user_id"
    assert db.query(InvoiceIngestRequest).count() == 0
    assert db.query(Invoice).count() == 0


def test_same_canonical_request_replays_original_invoice_and_semantic_money_is_stable(api):
    client, db = api
    first_payload = _submission()
    first_payload["fees"]["packaging_amount"] = "0.00"
    first_payload["items"][0]["unit_price"] = "19.6700"
    first = client.post(
        "/api/integrations/v1/invoices", json=first_payload, headers=_headers(),
    )
    assert first.status_code == 201, first.text

    replay_payload = json.loads(json.dumps(first_payload, sort_keys=True))
    replay_payload["currency"] = " USD "
    replay_payload["customer"]["name"] = " Untrusted customer name "
    replay_payload["fees"]["packaging_amount"] = "0"
    replay_payload["items"][0]["unit_price"] = "19.67"
    replay = client.post(
        "/api/integrations/v1/invoices", json=replay_payload, headers=_headers(),
    )

    assert replay.status_code == 200, replay.text
    assert replay.json()["code"] == 200
    assert replay.json()["message"] == "invoice replayed"
    assert replay.json()["data"]["replayed"] is True
    assert replay.json()["data"]["invoice_id"] == first.json()["data"]["invoice_id"]
    assert db.query(Invoice).count() == 1
    assert db.query(InvoiceIngestRequest).one().attempt_count == 1


def test_changed_created_request_returns_stable_409_and_preserves_original(api):
    client, db = api
    first = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    invoice_id = first.json()["data"]["invoice_id"]
    original_digest = db.query(InvoiceIngestRequest).one().request_sha256
    changed = _submission()
    changed["remark"] = "changed after creation"

    response = client.post(
        "/api/integrations/v1/invoices", json=changed, headers=_headers(),
    )

    assert response.status_code == 409, response.text
    assert response.json()["data"]["error_code"] == "EXTERNAL_ORDER_CHANGED"
    assert "external_order_id" in response.json()["data"]["action"]
    row = db.query(InvoiceIngestRequest).one()
    assert row.request_sha256 == original_digest
    assert row.attempt_count == 1
    assert row.invoice_id == invoice_id
    assert db.query(Invoice).count() == 1


def test_rejected_request_records_stable_422_then_corrected_same_id_succeeds(api):
    client, db = api
    rejected_payload = _submission()
    rejected_payload["items"][0]["catalog_ref"]["sku_id"] = 9999
    rejected = client.post(
        "/api/integrations/v1/invoices", json=rejected_payload, headers=_headers(),
    )

    assert rejected.status_code == 422, rejected.text
    request_id = rejected.json()["data"]["request_id"]
    assert rejected.json()["data"]["issues"][0]["code"] == "PRODUCT_NOT_FOUND"
    row = db.query(InvoiceIngestRequest).one()
    assert row.public_id == request_id
    assert row.status == "rejected"
    assert row.error_code == "PRODUCT_NOT_FOUND"
    assert row.error_json["issues"] == rejected.json()["data"]["issues"]
    assert db.query(Invoice).count() == 0

    created = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    assert created.status_code == 201, created.text
    row = db.query(InvoiceIngestRequest).one()
    assert row.public_id == request_id
    assert row.status == "created"
    assert row.attempt_count == 2
    assert row.error_code is None
    assert row.error_json is None
    assert db.query(Invoice).count() == 1


def test_same_rejected_content_is_a_new_attempt_and_get_replays_original_422(api):
    client, db = api
    payload = _submission()
    payload["items"][0]["catalog_ref"]["sku_id"] = 9999
    first = client.post(
        "/api/integrations/v1/invoices", json=payload, headers=_headers(),
    )
    second = client.post(
        "/api/integrations/v1/invoices", json=payload, headers=_headers(),
    )
    recovered = client.get(
        "/api/integrations/v1/invoices/by-external-id/SITE:2026-0001",
        headers=_headers(),
    )

    assert first.status_code == second.status_code == recovered.status_code == 422
    assert second.json()["data"] == recovered.json()["data"]
    assert db.query(InvoiceIngestRequest).one().attempt_count == 2
    assert db.query(Invoice).count() == 0


def test_get_by_external_id_recovers_created_result_and_is_app_scoped(api):
    client, db = api
    created = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    recovered = client.get(
        "/api/integrations/v1/invoices/by-external-id/SITE:2026-0001",
        headers=_headers(),
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["data"]["invoice_id"] == created.json()["data"]["invoice_id"]
    assert recovered.json()["data"]["replayed"] is True

    other_token = "ark_live_other_app_token"
    db.add(IntegrationApp(
        public_id="app_other_invoice_contract",
        name="Other app",
        owner_user_id=8101,
        token_hash=hash_token(other_token),
        token_suffix=other_token[-6:],
        scopes=["invoice:write"],
    ))
    db.commit()
    isolated = client.get(
        "/api/integrations/v1/invoices/by-external-id/SITE:2026-0001",
        headers=_headers(other_token),
    )
    error = _assert_external_error(
        isolated, 404, "EXTERNAL_INVOICE_NOT_FOUND",
    )
    assert error["data"] == {
        "error_code": "EXTERNAL_INVOICE_NOT_FOUND",
        "field": "external_order_id",
        "external_order_id": "SITE:2026-0001",
        "action": "确认订单号和站点凭证后重试",
    }


def test_invoice_service_rounding_matches_validate_for_half_cent_and_fee_snapshots(api):
    client, db = api
    payload = _submission()
    payload["items"][0]["quantity"] = 1
    payload["items"][0]["unit_price"] = "10.0050"
    payload["items"][0]["discount_amount"] = "-0.01"
    payload["fees"] = {
        "packaging_amount": "2.00",
        "packaging_quantity": 3,
        "shipping_amount": "4.00",
        "surcharge": {"name": "Card fee", "amount": "1.00"},
    }
    validated = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    created = client.post(
        "/api/integrations/v1/invoices", json=payload, headers=_headers(),
    )
    assert validated.status_code == 200, validated.text
    assert created.status_code == 201, created.text
    assert created.json()["data"]["totals"] == validated.json()["data"]["totals"]
    invoice = db.query(Invoice).one()
    item = db.query(InvoiceItem).one()
    assert invoice.internal_accessory == Decimal("2.00")
    assert invoice.packaging_quantity == 3
    assert invoice.shipping_fee == Decimal("4.00")
    assert invoice.surcharge_name == "Card fee"
    assert invoice.surcharge_amount == Decimal("1.00")
    assert item.price_per_piece == Decimal("10.0050")
    assert item.discount_amount == Decimal("-0.01")


def test_invoice_create_value_error_becomes_safe_stable_rejection(api, monkeypatch):
    client, db = api
    from app.invoice import service as invoice_service

    def reject_after_validation(*_args, **_kwargs):
        raise ValueError("raw database/catalog detail must not leak")

    monkeypatch.setattr(invoice_service, "create_invoice", reject_after_validation)
    response = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    assert response.status_code == 422, response.text
    issue = response.json()["data"]["issues"][0]
    assert issue == {
        "code": "INVOICE_CREATE_REJECTED",
        "field": "invoice",
        "message": "发票创建条件已变化，请刷新客户或产品信息后重试",
    }
    assert "raw database" not in response.text
    row = db.query(InvoiceIngestRequest).one()
    assert row.status == "rejected"
    assert row.error_code == "INVOICE_CREATE_REJECTED"
    assert db.query(Invoice).count() == 0


def test_unexpected_create_error_rolls_back_invoice_and_ingest(api, monkeypatch):
    client, db = api
    from app.invoice import service as invoice_service

    original_create = invoice_service.create_invoice

    def crash_after_invoice_flush(*args, **kwargs):
        original_create(*args, **kwargs)
        raise RuntimeError("simulated server crash after invoice flush")

    monkeypatch.setattr(invoice_service, "create_invoice", crash_after_invoice_flush)
    response = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    error = _assert_external_error(response, 500, "INTERNAL_ERROR")
    assert error["data"]["external_order_id"] == "SITE:2026-0001"
    assert "相同 external_order_id" in error["data"]["action"]
    assert "simulated server crash" not in response.text
    assert db.query(Invoice).count() == 0
    assert db.query(InvoiceIngestRequest).count() == 0


def test_unexpected_validation_error_rolls_back_processing_ingest(
    api, monkeypatch, caplog,
):
    client, db = api
    from app.integration import validation_service

    secret = "secret@example.com +8613800000000"
    printed: list[str] = []

    def crash_during_validation(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(validation_service, "validate_submission", crash_during_validation)
    monkeypatch.setattr(
        "builtins.print",
        lambda *values, **_kwargs: printed.append(" ".join(map(str, values))),
    )
    caplog.set_level(logging.ERROR)
    response = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    error = _assert_external_error(response, 500, "INTERNAL_ERROR")
    assert error["data"]["external_order_id"] == "SITE:2026-0001"
    assert "相同 external_order_id" in error["data"]["action"]
    combined = "\n".join((response.text, caplog.text, *printed))
    assert secret not in combined
    assert "RuntimeError" in caplog.text
    assert "SITE:2026-0001" in caplog.text
    assert "RuntimeError" in "\n".join(printed)
    assert "SITE:2026-0001" in "\n".join(printed)
    assert db.query(Invoice).count() == 0
    assert db.query(InvoiceIngestRequest).count() == 0


def test_invoice_number_conflict_retries_the_whole_transaction(api, monkeypatch):
    client, db = api
    from app.invoice import service as invoice_service

    original_create = invoice_service.create_invoice
    create_calls = 0
    public_ids = iter(("req_first_attempt", "req_second_attempt"))

    def conflict_once(*args, **kwargs):
        nonlocal create_calls
        create_calls += 1
        if create_calls == 1:
            raise IntegrityError(
                "INSERT INTO ark_invoices (invoice_no) VALUES (?)",
                {"invoice_no": "integration-owner-KC-0801"},
                RuntimeError(
                    "UNIQUE constraint failed: ark_invoices.invoice_no"
                ),
            )
        return original_create(*args, **kwargs)

    monkeypatch.setattr(invoice_service, "create_invoice", conflict_once)
    monkeypatch.setattr(integration_service, "_request_public_id", lambda: next(public_ids))

    response = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"]["request_id"] == "req_second_attempt"
    assert create_calls == 2
    assert db.query(Invoice).count() == 1
    rows = db.query(InvoiceIngestRequest).all()
    assert [(row.public_id, row.status) for row in rows] == [
        ("req_second_attempt", "created"),
    ]


def test_different_external_ids_recover_from_simulated_invoice_number_race(
    api, monkeypatch,
):
    client, db = api
    from app.invoice import service as invoice_service

    first_payload = _submission()
    first_payload["external_order_id"] = "SITE:RACE-A"
    first = client.post(
        "/api/integrations/v1/invoices", json=first_payload, headers=_headers(),
    )
    assert first.status_code == 201, first.text
    first_number = first.json()["data"]["invoice_no"]

    original_create = invoice_service.create_invoice
    create_calls = 0

    def lose_stale_number_once(*args, **kwargs):
        nonlocal create_calls
        create_calls += 1
        if create_calls == 1:
            raise IntegrityError(
                "INSERT INTO ark_invoices (invoice_no) VALUES (?)",
                {"invoice_no": first_number},
                RuntimeError(
                    "UNIQUE constraint failed: ark_invoices.invoice_no"
                ),
            )
        return original_create(*args, **kwargs)

    monkeypatch.setattr(invoice_service, "create_invoice", lose_stale_number_once)
    second_payload = _submission()
    second_payload["external_order_id"] = "SITE:RACE-B"
    second = client.post(
        "/api/integrations/v1/invoices", json=second_payload, headers=_headers(),
    )

    assert second.status_code == 201, second.text
    assert create_calls == 2
    invoices = db.query(Invoice).order_by(Invoice.id).all()
    assert len(invoices) == 2
    assert len({invoice.invoice_no for invoice in invoices}) == 2
    ingests = db.query(InvoiceIngestRequest).order_by(
        InvoiceIngestRequest.external_order_id,
    ).all()
    assert [(row.external_order_id, row.status) for row in ingests] == [
        ("SITE:RACE-A", "created"),
        ("SITE:RACE-B", "created"),
    ]
    assert all(row.invoice_id is not None for row in ingests)


def test_non_invoice_unique_conflict_is_not_retried(api, monkeypatch):
    client, db = api
    from app.invoice import service as invoice_service

    create_calls = 0

    def different_unique_conflict(*_args, **_kwargs):
        nonlocal create_calls
        create_calls += 1
        raise IntegrityError(
            "INSERT INTO ark_invoices (source_type, source_order_id) VALUES (?, ?)",
            {"source_type": "external_api", "source_order_id": "secret"},
            RuntimeError(
                "UNIQUE constraint failed: ark_invoices.source_type, "
                "ark_invoices.source_order_id"
            ),
        )

    monkeypatch.setattr(invoice_service, "create_invoice", different_unique_conflict)
    response = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )

    _assert_external_error(response, 500, "INTERNAL_ERROR")
    assert create_calls == 1
    assert db.query(Invoice).count() == 0
    assert db.query(InvoiceIngestRequest).count() == 0


def test_exhausted_invoice_number_conflicts_return_stable_503(api, monkeypatch):
    client, db = api
    from app.invoice import service as invoice_service

    create_calls = 0

    def always_conflict(*_args, **_kwargs):
        nonlocal create_calls
        create_calls += 1
        raise IntegrityError(
            "INSERT INTO ark_invoices (invoice_no) VALUES (?)",
            {"invoice_no": "integration-owner-KC-0801"},
            RuntimeError("UNIQUE constraint failed: ark_invoices.invoice_no"),
        )

    monkeypatch.setattr(invoice_service, "create_invoice", always_conflict)
    response = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )

    _assert_external_error(response, 503, "SERVICE_UNAVAILABLE")
    assert create_calls in {2, 3}
    assert db.query(Invoice).count() == 0
    assert db.query(InvoiceIngestRequest).count() == 0


def test_operational_dependency_error_is_safe_503_and_rolls_back(api, monkeypatch):
    client, db = api
    from app.integration import validation_service

    def unavailable_dependency(*_args, **_kwargs):
        raise OperationalError(
            "SELECT secret FROM dependency",
            {},
            RuntimeError("database password and internal host must not leak"),
        )

    monkeypatch.setattr(validation_service, "validate_submission", unavailable_dependency)
    response = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    error = _assert_external_error(response, 503, "SERVICE_UNAVAILABLE")
    assert error["data"]["external_order_id"] == "SITE:2026-0001"
    assert "相同 external_order_id" in error["data"]["action"]
    assert "password" not in response.text
    assert "internal host" not in response.text
    assert db.query(Invoice).count() == 0
    assert db.query(InvoiceIngestRequest).count() == 0


def test_external_exception_logs_and_prints_are_redacted(
    api, monkeypatch, caplog,
):
    client, _ = api
    from app.integration import validation_service

    secret = "secret@example.com +8613800000000"
    printed: list[str] = []

    def unavailable_dependency(*_args, **_kwargs):
        raise OperationalError(
            "SELECT password FROM contacts WHERE email=:email",
            {"email": secret},
            RuntimeError(secret),
        )

    monkeypatch.setattr(validation_service, "validate_submission", unavailable_dependency)
    monkeypatch.setattr(
        "builtins.print",
        lambda *values, **_kwargs: printed.append(" ".join(map(str, values))),
    )
    caplog.set_level(logging.ERROR)

    response = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )

    _assert_external_error(response, 503, "SERVICE_UNAVAILABLE")
    combined = "\n".join((response.text, caplog.text, *printed))
    assert secret not in combined
    assert "SELECT password" not in combined
    assert "contacts WHERE" not in combined
    assert "OperationalError" in caplog.text
    assert "SITE:2026-0001" in caplog.text
    assert "OperationalError" in "\n".join(printed)
    assert "SITE:2026-0001" in "\n".join(printed)


def test_commit_failure_logs_and_prints_only_safe_metadata(monkeypatch, caplog):
    secret = "secret@example.com +8613800000000"
    printed: list[str] = []

    class FailingSession:
        rolled_back = False

        def commit(self):
            raise RuntimeError(secret)

        def rollback(self):
            self.rolled_back = True

    session = FailingSession()
    monkeypatch.setattr(
        "builtins.print",
        lambda *values, **_kwargs: printed.append(" ".join(map(str, values))),
    )
    caplog.set_level(logging.ERROR)

    with pytest.raises(RuntimeError, match="secret@example.com"):
        integration_service._commit_or_rollback(session, "create_invoice_ingest")

    combined = "\n".join((caplog.text, *printed))
    assert session.rolled_back is True
    assert secret not in combined
    assert "RuntimeError" in caplog.text
    assert "RuntimeError" in "\n".join(printed)


def test_rate_limit_http_exception_maps_to_public_error_contract():
    from app.integration.router import _http_error_response

    response = _http_error_response(
        HTTPException(status_code=429, detail="raw limiter detail"),
    )
    assert response.status_code == 429
    body = json.loads(response.body)
    assert body["data"]["error_code"] == "RATE_LIMITED"
    assert body["data"]["action"]
    assert "raw limiter detail" not in response.body.decode("utf-8")


def test_processing_lookup_is_stable_actionable_409(api):
    client, db = api
    app_row = db.query(IntegrationApp).filter_by(public_id="app_invoice_contract").one()
    db.add(InvoiceIngestRequest(
        public_id="req_processing_lookup",
        integration_app_id=app_row.id,
        external_order_id="SITE:PROCESSING",
        request_sha256="f" * 64,
        status="processing",
        attempt_count=1,
    ))
    db.commit()

    response = client.get(
        "/api/integrations/v1/invoices/by-external-id/SITE:PROCESSING",
        headers=_headers(),
    )
    assert response.status_code == 409, response.text
    assert response.json()["data"]["error_code"] == "INVOICE_PROCESSING"
    assert "external_order_id" in response.json()["data"]["action"]


def test_create_accepts_exact_numeric_capacity_without_amount_drift(api):
    client, db = api
    payload = _submission()
    payload["items"][0]["quantity"] = 10_000
    payload["items"][0]["unit_price"] = "99999999.9999"
    validated = client.post(
        "/api/integrations/v1/invoices/validate", json=payload, headers=_headers(),
    )
    created = client.post(
        "/api/integrations/v1/invoices", json=payload, headers=_headers(),
    )
    assert validated.status_code == 200, validated.text
    assert created.status_code == 201, created.text
    assert created.json()["data"]["totals"] == {
        "product_amount": "999999999999.00",
        "total_amount": "999999999999.00",
    }
    assert created.json()["data"]["totals"] == validated.json()["data"]["totals"]
    assert db.query(Invoice).one().total_amount == Decimal("999999999999.00")


def test_ordinary_jwt_invoice_create_cannot_forge_external_api_provenance(api):
    _, db = api
    from app.invoice.router import router as invoice_router

    app = FastAPI()
    app.include_router(invoice_router, prefix="/api/invoice")
    app.dependency_overrides[get_db] = lambda: db
    token = create_access_token({
        "sub": "8101",
        "username": "integration-owner",
        "roles": [],
        "permissions": ["invoice:write"],
    })
    with TestClient(app) as client:
        response = client.post(
            "/api/invoice/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "customer_id": "1001",
                "customer_name": "Acme Global",
                "invoice_date": "2026-08-26",
                "source_type": "external_api",
                "source_order_id": "forged-request",
                "items": [],
            },
        )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "外部 API 来源发票只能通过站点接入接口创建"
    assert db.query(Invoice).count() == 0


def test_internal_edit_preserves_existing_external_api_provenance(api):
    client, db = api
    from app.invoice import service as invoice_service
    from app.invoice.schemas import InvoiceItemPayload, InvoiceUpdate

    created = client.post(
        "/api/integrations/v1/invoices", json=_submission(), headers=_headers(),
    )
    assert created.status_code == 201, created.text
    invoice = invoice_service.get_invoice(db, created.json()["data"]["invoice_id"])
    item = invoice.items[0]
    original_source = (
        invoice.source_type,
        invoice.source_order_id,
        invoice.source_order_name,
    )
    update = InvoiceUpdate(
        invoice_no=invoice.invoice_no,
        sales_user_id=invoice.sales_user_id,
        customer_id=invoice.customer_id,
        customer_name=invoice.customer_name,
        order_type=invoice.order_type,
        contact_name=invoice.contact_name,
        contact_phone=invoice.contact_phone,
        contact_email=invoice.contact_email,
        delivery_address=invoice.delivery_address,
        invoice_date=invoice.invoice_date,
        currency=invoice.currency,
        express_channel=invoice.express_channel,
        shipping_fee=invoice.shipping_fee,
        surcharge_name=invoice.surcharge_name,
        surcharge_amount=invoice.surcharge_amount,
        payment_term=invoice.payment_term,
        packaging_quantity=invoice.packaging_quantity,
        internal_accessory=invoice.internal_accessory,
        remark="reviewed internally",
        source_type=invoice.source_type,
        source_order_id=invoice.source_order_id,
        source_order_no=invoice.source_order_no,
        source_order_name=invoice.source_order_name,
        source_image_sha256=invoice.source_image_sha256,
        items=[InvoiceItemPayload(
            id=item.id,
            product_kind=item.product_kind,
            item_type=item.item_type,
            product_id=item.product_id,
            sku_id=item.sku_id,
            product_name=item.product_name,
            product_display=item.product_display,
            net_weight_grams=item.net_weight_grams,
            model=item.model,
            color=item.color,
            length=item.length,
            quantity=item.quantity,
            price_per_piece=item.price_per_piece,
            discount_amount=item.discount_amount,
        )],
    )

    updated = invoice_service.update_invoice(db, invoice, update, user_id=8101)
    db.commit()
    assert updated.remark == "reviewed internally"
    assert (
        updated.source_type,
        updated.source_order_id,
        updated.source_order_name,
    ) == original_source


def test_external_invoice_openapi_declares_create_replay_lookup_and_error_models():
    app = FastAPI()
    app.include_router(integration_router, prefix="/api/integrations")
    openapi = app.openapi()

    common_errors = {"401", "403", "429", "500", "503"}
    public_operations = {
        ("/api/integrations/v1/customers/resolve", "post"): {"200", "422"},
        ("/api/integrations/v1/products/resolve", "post"): {"200", "422"},
        ("/api/integrations/v1/invoices/validate", "post"): {"200", "422"},
        ("/api/integrations/v1/invoices", "post"): {"200", "201", "409", "422"},
        (
            "/api/integrations/v1/invoices/by-external-id/{external_order_id}",
            "get",
        ): {"200", "404", "409", "422"},
    }
    for (path, method), expected in public_operations.items():
        responses = openapi["paths"][path][method]["responses"]
        assert set(responses) == expected | common_errors
        for code in common_errors:
            schema = responses[code]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith("/ExternalErrorEnvelope")

    create = openapi["paths"]["/api/integrations/v1/invoices"]["post"]
    assert create["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/InvoiceCreatedEnvelope"
    )
    assert create["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/InvoiceReplayedEnvelope"
    )
    lookup = openapi["paths"][
        "/api/integrations/v1/invoices/by-external-id/{external_order_id}"
    ]["get"]
    for code in ("404", "409"):
        assert "$ref" in lookup["responses"][code]["content"]["application/json"]["schema"]


def test_two_real_sessions_racing_same_app_order_create_one_invoice(tmp_path):
    database_path = tmp_path / "invoice-race.sqlite3"
    catalog_path = tmp_path / "invoice-race-catalog.sqlite3"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        escaped_catalog = str(catalog_path).replace("'", "''")
        dbapi_connection.execute(f"ATTACH DATABASE '{escaped_catalog}' AS lsordertest")

    Base.metadata.create_all(engine, tables=[
        Base.metadata.tables["ark_permissions"],
        Base.metadata.tables["ark_roles"],
        ArkUser.__table__,
        Base.metadata.tables["ark_role_permissions"],
        Base.metadata.tables["ark_user_roles"],
        IntegrationApp.__table__,
        Invoice.__table__,
        InvoiceItem.__table__,
        InvoiceIngestRequest.__table__,
        StdPrice.__table__,
        PriceColorType.__table__,
        CustomerPriceRule.__table__,
    ])
    Session = sessionmaker(bind=engine)
    setup = Session()
    try:
        setup.execute(text("""
            CREATE TABLE lsordertest.customer_info (
                company_id TEXT PRIMARY KEY, company_name TEXT,
                country_name TEXT, owner_user_ids TEXT
            )
        """))
        setup.execute(text("""
            CREATE TABLE lsordertest.customer_contacts (
                id INTEGER PRIMARY KEY, company_id TEXT, name TEXT,
                email TEXT, tel TEXT, is_main INTEGER
            )
        """))
        setup.execute(text("""
            CREATE TABLE lsordertest.okki_products (
                product_id INTEGER PRIMARY KEY, product_no TEXT, product_name TEXT,
                model TEXT, color TEXT, size TEXT, unit TEXT, disable_flag INTEGER
            )
        """))
        setup.execute(text("""
            CREATE TABLE lsordertest.okki_inventory (
                product_id INTEGER, sku_id INTEGER, disable_flag INTEGER
            )
        """))
        setup.execute(text("""
            CREATE TABLE lsordertest.okki_orders (
                order_id TEXT PRIMARY KEY, company_id TEXT, account_date TEXT
            )
        """))
        setup.execute(text("""
            INSERT INTO lsordertest.customer_info VALUES
                ('1001', 'Acme Global', 'US', '[]')
        """))
        setup.execute(text("""
            INSERT INTO lsordertest.okki_products VALUES
                (1, 'HAIR-001', 'Canonical Hair/16/Natural/20g',
                 'M1', 'Natural', '16', '20g', 0)
        """))
        setup.execute(text("INSERT INTO lsordertest.okki_inventory VALUES (1, 1001, 0)"))
        owner = ArkUser(
            id=8201,
            username="race-owner",
            real_name="Race Owner",
            password_hash="test",
        )
        setup.add_all([
            owner,
            IntegrationApp(
                public_id="app_invoice_race",
                name="Invoice race",
                owner_user_id=owner.id,
                token_hash="a" * 64,
                token_suffix="aaaaaa",
                scopes=["invoice:write"],
            ),
            StdPrice(
                product_kind="hair",
                series_grade="Canonical Hair",
                length="16",
                weight_unit="20g",
                color_type="solid",
                price=Decimal("10.0000"),
                currency="USD",
            ),
            PriceColorType(color_code="natural", color_type="solid"),
        ])
        setup.commit()
    finally:
        setup.close()

    initial_read_barrier = threading.Barrier(2)
    local = threading.local()
    unique_races: list[str] = []

    @event.listens_for(engine, "handle_error")
    def record_unique_race(exception_context):
        if isinstance(exception_context.sqlalchemy_exception, Exception) and (
            "uq_invoice_ingest_app_order" in str(exception_context.original_exception)
            or "ark_invoice_ingest_requests.integration_app_id" in str(
                exception_context.original_exception
            )
        ):
            unique_races.append(str(exception_context.original_exception))

    @event.listens_for(engine, "after_cursor_execute")
    def synchronize_initial_reads(_conn, _cursor, statement, _params, _context, _many):
        if (
            getattr(local, "race_participant", False)
            and "FROM ark_invoice_ingest_requests" in statement
            and not getattr(local, "initial_read_seen", False)
        ):
            local.initial_read_seen = True
            initial_read_barrier.wait(timeout=10)

    payload = InvoiceSubmission.model_validate(_submission())
    principal = SubmissionPrincipal(
        actor_user_id=8201,
        sales_user_id=8201,
        idempotency_namespace="app_invoice_race",
        scopes=frozenset({"invoice:write"}),
    )
    outcomes: list[tuple[dict, bool]] = []
    failures: list[BaseException] = []

    def create_from_one_session():
        session = Session()
        local.race_participant = True
        try:
            outcomes.append(
                integration_service.create_external_invoice(session, payload, principal)
            )
        except BaseException as exc:  # test thread must surface every failure
            failures.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=create_from_one_session) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    verify = Session()
    try:
        assert all(not thread.is_alive() for thread in threads)
        assert failures == []
        assert len(outcomes) == 2
        assert sorted(replayed for _, replayed in outcomes) == [False, True]
        assert len(unique_races) == 1
        assert verify.query(InvoiceIngestRequest).count() == 1
        assert verify.query(Invoice).count() == 1
        assert verify.query(InvoiceItem).count() == 1
        row = verify.query(InvoiceIngestRequest).one()
        assert row.status == "created"
        assert row.invoice_id == verify.query(Invoice).one().id
    finally:
        verify.close()
        engine.dispose()
