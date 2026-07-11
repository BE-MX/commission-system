from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.aftersales.query_service import search_customers, search_orders, search_products
from app.aftersales.schemas import CaseCreate


def test_customer_search_returns_snapshot_fields(db, seed_business_data):
    items = search_customers(db, "客户A", limit=10)

    assert items == [{"customer_id": "CUST001", "customer_name": "客户A"}]


def test_order_search_is_scoped_to_customer(db, seed_business_data):
    db.execute(
        text(
            "INSERT INTO lsordertest.okki_orders "
            "(order_id, order_no, company_id, amount_usd, account_date, status_name) "
            "VALUES ('order-other', 'SO-OTHER', 'cust-002', 88, '2026-07-01', 'Open')"
        )
    )
    db.commit()

    items = search_orders(db, customer_id="CUST001", keyword="NO001", limit=10)

    assert len(items) == 1
    assert items[0]["order_id"] == "ORD001"
    assert items[0]["customer_id"] == "CUST001"


def test_order_search_requires_customer(db):
    with pytest.raises(ValueError, match="客户"):
        search_orders(db, customer_id="", keyword="", limit=10)


def test_product_search_excludes_disabled_rows(db):
    db.execute(
        text(
            "CREATE TABLE lsordertest.okki_products ("
            "product_id INTEGER PRIMARY KEY, name TEXT, model TEXT, color TEXT, size TEXT, unit TEXT, disable_flag INTEGER)"
        )
    )
    db.execute(
        text(
            "INSERT INTO lsordertest.okki_products VALUES "
            "(1, 'Invisible Weft', 'IW', '#2B', '20 inch', '100g', 0),"
            "(2, 'Disabled Weft', 'DW', '#1B', '18 inch', '100g', 1)"
        )
    )
    db.commit()

    items = search_products(db, "Weft", limit=20)

    assert [item["product_id"] for item in items] == [1]
    assert items[0]["product_name"] == "Invisible Weft"


def _valid_case_payload():
    return {
        "customer_id": "cust-001",
        "customer_name_snapshot": "Acme Hair",
        "customer_grade": "A",
        "order_id": "order-001",
        "order_no_snapshot": "SO-001",
        "purchase_date": date(2026, 7, 1),
        "feedback_date": date(2026, 7, 10),
        "product_id": 1,
        "product_name_snapshot": "Invisible Weft",
        "is_custom_product": False,
        "color_value": "#2B",
        "length_value": "20 inch",
        "weight_value": Decimal("100"),
        "weight_unit": "g",
        "quantity": Decimal("2"),
        "primary_issue_type": "褪色",
        "problem_description": "客户使用三周后出现明显褪色，已经影响终端客户继续销售。",
        "occurred_stage": "使用几天",
        "care_storage_note": "客户使用无硫酸盐洗发水，低温护理，未游泳或暴晒。",
        "affects_end_customer": "yes",
        "affected_goods_value": Decimal("1150"),
        "affected_goods_currency": "USD",
    }


def test_feedback_date_cannot_precede_purchase_date():
    payload = _valid_case_payload()
    payload["feedback_date"] = date(2026, 6, 30)

    with pytest.raises(ValidationError, match="反馈日期"):
        CaseCreate.model_validate(payload)


def test_standard_product_requires_product_id():
    payload = _valid_case_payload()
    payload["product_id"] = None

    with pytest.raises(ValidationError, match="标准产品"):
        CaseCreate.model_validate(payload)


def test_custom_product_cannot_keep_standard_product_id():
    payload = _valid_case_payload()
    payload["is_custom_product"] = True

    with pytest.raises(ValidationError, match="定制产品"):
        CaseCreate.model_validate(payload)


@pytest.mark.parametrize("field", ["quantity", "affected_goods_value", "weight_value"])
def test_positive_business_numbers(field):
    payload = _valid_case_payload()
    payload[field] = Decimal("0")

    with pytest.raises(ValidationError):
        CaseCreate.model_validate(payload)
